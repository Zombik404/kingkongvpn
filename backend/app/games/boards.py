"""Leaderboards and seasons (ADR-021).

Three boards — wins, win rate, XP — over three periods: all time (from the game profiles), the
current weekly and monthly season, or any season by id (archive). Ranks come from one window
function, so ties are ordered the same way everywhere: the higher score first, then whoever got
there first, then a stable id. Only active accounts that staff haven't excluded are ranked.

Seasons are created automatically (week from Monday 00:00, month from the 1st, in the game time
zone) and finalised once: final tables are frozen into `game_season_results`, prizes go out
through `progress.grant_reward` (idempotent), then the season is closed.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.games import progress
from app.models import Achievement, GameProfile, Season, SeasonResult, SeasonStat, User
from app.models.base import utcnow
from app.models.enums import UserStatus

BOARDS = ("wins", "winrate", "xp")
FINAL_TOP = 100  # places frozen per board when a season closes


class BoardError(ValueError):
    pass


def _ranked(board: str, season_id: uuid.UUID | None, min_rounds: int) -> Select[Any]:
    """user_id, nickname, avatar, level, title, frame, wins, losses, rounds, xp, value, rank."""
    if season_id is None:
        stats: Any = GameProfile
        base = select(GameProfile.user_id).join(User, User.id == GameProfile.user_id)
    else:
        stats = SeasonStat
        base = (
            select(SeasonStat.user_id)
            .join(GameProfile, GameProfile.user_id == SeasonStat.user_id)
            .join(User, User.id == SeasonStat.user_id)
            .where(SeasonStat.season_id == season_id)
        )
    wins, losses, xp, at = stats.wins, stats.losses, stats.xp, stats.score_at
    decided = wins + losses
    if board == "wins":
        value, cond = wins, wins > 0
        order = [wins.desc(), at.asc().nulls_last()]
    elif board == "xp":
        value, cond = xp, xp > 0
        order = [xp.desc(), at.asc().nulls_last()]
    elif board == "winrate":
        value = wins * 10000 / func.nullif(decided, 0)  # integer basis points
        cond = decided >= min_rounds
        order = [
            (wins * 10000.0 / func.nullif(decided, 0)).desc(),
            decided.desc(),
            at.asc().nulls_last(),
        ]
    else:
        raise BoardError(board)
    return base.add_columns(
        GameProfile.nickname,
        GameProfile.avatar,
        GameProfile.level,
        GameProfile.title,
        GameProfile.frame,
        wins.label("wins"),
        losses.label("losses"),
        stats.rounds.label("rounds"),
        xp.label("xp"),
        value.label("value"),
        func.row_number().over(order_by=[*order, GameProfile.user_id]).label("rank"),
    ).where(cond, User.status == UserStatus.ACTIVE, GameProfile.excluded_at.is_(None))


def _row(r: Any, cfg: dict[str, Any], me: uuid.UUID | None) -> dict[str, Any]:
    return {
        "rank": int(r.rank),
        "nickname": r.nickname,
        "avatar": r.avatar,
        "level": r.level,
        "title": r.title or progress.level_title(r.level, cfg["games.levels.titles"]),
        "frame": r.frame,
        "wins": int(r.wins),
        "losses": int(r.losses),
        "rounds": int(r.rounds),
        "xp": int(r.xp),
        "value": int(r.value or 0),  # win rate in basis points (6543 = 65.43 %)
        "me": me is not None and r.user_id == me,
    }


async def board(
    db: AsyncSession,
    cfg: dict[str, Any],
    name: str,
    *,
    season: Season | None,
    user_id: uuid.UUID | None,
    offset: int = 0,
    limit: int = 20,
    q: str | None = None,
) -> dict[str, Any]:
    min_rounds = int(cfg["games.leaderboard.min_rounds_winrate"])
    ranked = _ranked(name, season.id if season else None, min_rounds).subquery()
    total = int(await db.scalar(select(func.count()).select_from(ranked)) or 0)
    page = select(ranked).order_by(ranked.c.rank)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        page = page.where(ranked.c.nickname.ilike(f"%{escaped}%"))
    rows = (await db.execute(page.offset(offset).limit(limit))).all()
    mine = None
    if user_id is not None:
        r = (await db.execute(select(ranked).where(ranked.c.user_id == user_id))).first()
        mine = _row(r, cfg, user_id) if r is not None else None
    return {
        "board": name,
        "period": season.kind if season else "all",
        "season": season_out(season) if season else None,
        "total": total,
        "min_rounds": min_rounds if name == "winrate" else None,
        "rows": [_row(r, cfg, user_id) for r in rows],
        "me": mine,
    }


# --- seasons -----------------------------------------------------------------------------
def season_out(s: Season) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "kind": s.kind,
        "name": s.name,
        "starts_at": s.starts_at.isoformat(),
        "ends_at": s.ends_at.isoformat(),
        "status": s.status,
        "board": s.board,
        "rewards": s.rewards,
        "finalized_at": s.finalized_at.isoformat() if s.finalized_at else None,
    }


def bounds(
    kind: str, now: dt.datetime, cfg: dict[str, Any]
) -> tuple[dt.datetime, dt.datetime, str]:
    zone = progress.tz(cfg)
    local = now.astimezone(zone)
    if kind == "weekly":
        start_day = local.date() - dt.timedelta(days=local.weekday())
        end_day = start_day + dt.timedelta(days=7)
        y, w, _ = start_day.isocalendar()
        name = f"{y}-W{w:02d}"
    else:
        start_day = local.date().replace(day=1)
        end_day = (start_day + dt.timedelta(days=32)).replace(day=1)
        name = f"{start_day:%Y-%m}"
    start = dt.datetime.combine(start_day, dt.time(0), tzinfo=zone).astimezone(dt.UTC)
    end = dt.datetime.combine(end_day, dt.time(0), tzinfo=zone).astimezone(dt.UTC)
    return start, end, name


async def ensure_current(
    db: AsyncSession, cfg: dict[str, Any], now: dt.datetime | None = None
) -> list[Season]:
    """Open this week's and this month's season if they don't exist yet (safe to race)."""
    now = now or utcnow()
    if not cfg["games.seasons.enabled"]:
        return []
    for kind in ("weekly", "monthly"):
        start, end, name = bounds(kind, now, cfg)
        await db.execute(
            pg_insert(Season)
            .values(
                id=uuid.uuid4(),
                kind=kind,
                name=name,
                starts_at=start,
                ends_at=end,
                board=cfg["games.seasons.board"],
                rewards=cfg[f"games.seasons.rewards_{kind}"],
            )
            .on_conflict_do_nothing(
                index_elements=[Season.kind, Season.starts_at],
                index_where=Season.kind.in_(["weekly", "monthly"]),
            )
        )
    return await progress.active_seasons(db, now)


async def current(db: AsyncSession, kind: str, now: dt.datetime | None = None) -> Season | None:
    now = now or utcnow()
    return await db.scalar(
        select(Season)
        .where(
            Season.kind == kind,
            Season.status == "active",
            Season.starts_at <= now,
            Season.ends_at > now,
        )
        .order_by(Season.starts_at.desc())
        .limit(1)
    )


def tier_for(rank: int, rewards: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((t for t in rewards if t["places"][0] <= rank <= t["places"][1]), None)


async def finalize(
    db: AsyncSession, cfg: dict[str, Any], season_id: uuid.UUID, *, now: dt.datetime | None = None
) -> list[tuple[uuid.UUID, dict[str, Any]]]:
    """Close a finished season exactly once: freeze the tables, give the prizes and season
    achievements, then mark it closed. Returns (user, prize) pairs for notices."""
    now = now or utcnow()
    season = await db.get(Season, season_id, with_for_update=True)
    if season is None or season.status != "active" or season.ends_at > now:
        return []
    min_rounds = int(cfg["games.seasons.min_rounds"])
    for name in BOARDS:
        ranked = _ranked(
            name, season.id, int(cfg["games.leaderboard.min_rounds_winrate"])
        ).subquery()
        rows = (
            await db.execute(
                select(ranked).where(ranked.c.rank <= FINAL_TOP).order_by(ranked.c.rank)
            )
        ).all()
        for r in rows:
            await db.execute(
                pg_insert(SeasonResult)
                .values(
                    season_id=season.id,
                    board=name,
                    rank=int(r.rank),
                    user_id=r.user_id,
                    nickname=r.nickname,
                    value=int(r.value or 0),
                    detail={
                        "wins": int(r.wins),
                        "losses": int(r.losses),
                        "rounds": int(r.rounds),
                        "xp": int(r.xp),
                        "avatar": r.avatar,
                        "level": r.level,
                        "frame": r.frame,
                    },
                )
                .on_conflict_do_nothing()
            )
    prizes: list[tuple[uuid.UUID, dict[str, Any]]] = []
    season_achievements = (
        await db.scalars(
            select(Achievement).where(
                Achievement.enabled.is_(True), Achievement.metric == "season_rank"
            )
        )
    ).all()
    ranked = _ranked(
        season.board, season.id, int(cfg["games.leaderboard.min_rounds_winrate"])
    ).subquery()
    winners = (
        await db.execute(
            select(ranked.c.user_id, ranked.c.rank, ranked.c.rounds)
            .where(ranked.c.rank <= FINAL_TOP)
            .order_by(ranked.c.rank)
        )
    ).all()
    for uid, rank, rounds in winners:
        if rounds < min_rounds:
            continue  # a prize needs a real season, not one lucky round
        profile = await db.get(GameProfile, uid, with_for_update=True)
        if profile is None:
            continue
        events: list[progress.Event] = []
        tier = tier_for(int(rank), season.rewards)
        if tier:
            await progress.grant_reward(
                db, cfg, profile, tier, source="season", ref=f"{season.name} #{rank}",
                key=f"season:{season.id}:place", events=events,
            )  # fmt: skip
            prizes.append(
                (uid, {"season": season.name, "kind": season.kind, "rank": int(rank), **tier})
            )
        if cfg["games.achievements.enabled"]:
            for a in season_achievements:
                if int(rank) <= a.threshold:
                    await progress.unlock(db, cfg, profile, a, events)
    part_xp = int(cfg["games.seasons.participation_xp"])
    if part_xp:
        players = (
            await db.scalars(
                select(SeasonStat.user_id).where(
                    SeasonStat.season_id == season.id, SeasonStat.rounds >= min_rounds
                )
            )
        ).all()
        for uid in players:
            profile = await db.get(GameProfile, uid, with_for_update=True)
            if profile is not None and profile.excluded_at is None:
                await progress.add_xp(
                    db, cfg, profile, part_xp, "season", f"season:{season.id}:played", [],
                    source=season.name,
                )  # fmt: skip
    season.status = "closed"
    season.finalized_at = now
    await db.flush()
    return prizes


async def due(db: AsyncSession, now: dt.datetime | None = None) -> list[uuid.UUID]:
    now = now or utcnow()
    return list(
        (
            await db.scalars(
                select(Season.id)
                .where(Season.status == "active", Season.ends_at <= now)
                .order_by(Season.ends_at)
            )
        ).all()
    )


async def results(
    db: AsyncSession, season_id: uuid.UUID, board: str, limit: int = FINAL_TOP
) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(SeasonResult)
            .where(SeasonResult.season_id == season_id, SeasonResult.board == board)
            .order_by(SeasonResult.rank)
            .limit(limit)
        )
    ).all()
    return [
        {
            "rank": r.rank,
            "nickname": r.nickname,
            "value": r.value,
            **(r.detail or {}),
            "user_id": str(r.user_id) if r.user_id else None,
        }
        for r in rows
    ]
