"""Staff API for blackjack progression (ADR-021): player profiles, achievements, daily challenges,
seasons and prizes, excluding confirmed cheats from the boards. XP values, level curve, streak
and season prizes, the bonus-days switch are ordinary settings (`games.*` via /admin/settings).
Same rules as the rest of the admin API: permission + MFA session, an audit row per change."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import Client, Ctx, Db, require
from app.core.errors import Conflict, NotFound
from app.games import boards, progress, views
from app.games import service as games
from app.models import (
    Achievement,
    ChallengeTemplate,
    DailyChallenge,
    GameProfile,
    Season,
    SeasonStat,
)
from app.models.base import utcnow
from app.models.enums import ActorType
from app.security.principal import Principal
from app.security.rbac import Perm
from app.services import audit
from app.services.settings import RewardTier

router = APIRouter(prefix="/admin/games", tags=["admin", "games"])

Reader = Annotated[Principal, Depends(require(Perm.GAMES_READ))]
Writer = Annotated[Principal, Depends(require(Perm.GAMES_WRITE))]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100_000)]
Text = dict[
    Literal["ru", "en", "uk", "de", "hu"], Annotated[str, Field(min_length=1, max_length=120)]
]
Code = Annotated[str, Field(pattern=r"^[a-z0-9_]{3,32}$")]
Reason = Annotated[str, Field(min_length=3, max_length=200)]
ACH_METRICS = Literal[
    "wins", "rounds", "blackjacks", "best_win_streak", "perfect_wins", "best_day_streak",
    "days_played", "level", "xp", "season_rank",
]  # fmt: skip
CH_METRICS = Literal["rounds", "wins", "blackjacks", "high_wins", "win_run"]


def _audit(
    db: Db, p: Principal, client: Client, action: str, kind: str, target: Any, details: Any
) -> None:
    audit.record(
        db, action=action, actor_id=p.user.id, actor_type=ActorType.ADMIN, target_type=kind,
        target_id=target, ip=client.ip, details=details,
    )  # fmt: skip


class ReasonIn(BaseModel):
    reason: Reason


# --- players -----------------------------------------------------------------------------
@router.get("/progress/players")
async def players(
    _: Reader,
    db: Db,
    q: Annotated[str | None, Query(max_length=64)] = None,
    excluded: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict[str, Any]]:
    """Game profiles by XP. `q`: nickname part or user id; `excluded`: only hidden ones."""
    cfg = await games.config(db)
    stmt = select(GameProfile).order_by(GameProfile.xp.desc(), GameProfile.user_id)
    if q:
        try:
            stmt = stmt.where(GameProfile.user_id == uuid.UUID(q.strip()))
        except ValueError:
            escaped = q.strip().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
            stmt = stmt.where(GameProfile.nickname.ilike(f"%{escaped}%"))
    if excluded:
        stmt = stmt.where(GameProfile.excluded_at.is_not(None))
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return [
        {
            "user_id": str(p.user_id),
            **views.card(p, cfg),
            "excluded_at": p.excluded_at.isoformat() if p.excluded_at else None,
        }
        for p in rows
    ]


@router.get("/progress/players/{user_id}")
async def player(user_id: uuid.UUID, _: Reader, db: Db) -> dict[str, Any]:
    cfg = await games.config(db)
    p = await db.get(GameProfile, user_id)
    if p is None:
        raise NotFound("This user hasn't played yet.")
    day = progress.game_day(utcnow(), cfg)
    today = (
        await db.execute(
            select(DailyChallenge, ChallengeTemplate)
            .join(ChallengeTemplate, ChallengeTemplate.id == DailyChallenge.template_id)
            .where(DailyChallenge.user_id == user_id, DailyChallenge.day == day)
        )
    ).all()
    seasons = (
        await db.execute(
            select(Season, SeasonStat)
            .join(SeasonStat, SeasonStat.season_id == Season.id)
            .where(SeasonStat.user_id == user_id)
            .order_by(Season.starts_at.desc())
            .limit(10)
        )
    ).all()
    return {
        "user_id": str(user_id),
        **views.card(p, cfg),
        "excluded_at": p.excluded_at.isoformat() if p.excluded_at else None,
        "titles": await views.titles_of(db, p, cfg),
        "achievements": [a for a in await views.achievements(db, p) if a["unlocked_at"]],
        "challenges_today": [
            {
                "code": t.code,
                "progress": c.progress,
                "target": c.target,
                "completed_at": c.completed_at.isoformat() if c.completed_at else None,
            }
            for c, t in today
        ],
        "seasons": [
            {
                "name": s.name,
                "kind": s.kind,
                "status": s.status,
                "rounds": st.rounds,
                "wins": st.wins,
                "losses": st.losses,
                "xp": st.xp,
            }
            for s, st in seasons
        ],
        "xp_history": await views.xp_history(db, user_id, 0, 30),
        "rewards": await views.rewards(db, user_id, 0, 30),
    }


async def _profile(db: Db, user_id: uuid.UUID) -> GameProfile:
    p = await db.get(GameProfile, user_id, with_for_update=True)
    if p is None:
        raise NotFound("This user hasn't played yet.")
    return p


@router.post("/progress/players/{user_id}/exclude")
async def exclude(
    user_id: uuid.UUID, body: ReasonIn, actor: Writer, db: Db, client: Client
) -> dict[str, Any]:
    """Hide a player from every leaderboard and from season prizes (confirmed cheating)."""
    p = await _profile(db, user_id)
    if p.excluded_at is None:
        p.excluded_at = utcnow()
        _audit(db, actor, client, "game.player_excluded", "user", user_id, {"reason": body.reason})
    await db.commit()
    return {"user_id": str(user_id), "excluded_at": p.excluded_at.isoformat()}


@router.post("/progress/players/{user_id}/include")
async def include(
    user_id: uuid.UUID, body: ReasonIn, actor: Writer, db: Db, client: Client
) -> dict[str, Any]:
    p = await _profile(db, user_id)
    if p.excluded_at is not None:
        p.excluded_at = None
        _audit(db, actor, client, "game.player_included", "user", user_id, {"reason": body.reason})
    await db.commit()
    return {"user_id": str(user_id), "excluded_at": None}


# --- achievements ------------------------------------------------------------------------
class AchievementIn(BaseModel):
    code: Code
    category: Literal["game", "activity", "progress", "season"]
    names: Text
    descriptions: Text
    icon: Annotated[str, Field(min_length=1, max_length=8)]
    metric: ACH_METRICS
    threshold: Annotated[int, Field(ge=1, le=10_000_000)]
    xp_reward: Annotated[int, Field(ge=0, le=100_000)] = 0
    title: Annotated[str | None, Field(max_length=32)] = None
    sort_order: int = 0
    enabled: bool = True

    @model_validator(mode="after")
    def _season_metric(self) -> AchievementIn:
        if (self.category == "season") != (self.metric == "season_rank"):
            raise ValueError("season achievements (and only they) use metric season_rank")
        if "ru" not in self.names or "en" not in self.names:
            raise ValueError("names need at least ru and en")
        return self


class AchievementPatch(BaseModel):
    names: Text | None = None
    descriptions: Text | None = None
    icon: Annotated[str | None, Field(min_length=1, max_length=8)] = None
    threshold: Annotated[int | None, Field(ge=1, le=10_000_000)] = None
    xp_reward: Annotated[int | None, Field(ge=0, le=100_000)] = None
    title: Annotated[str | None, Field(max_length=32)] = None
    sort_order: int | None = None
    enabled: bool | None = None


def _ach_out(a: Achievement, unlocked: int = 0) -> dict[str, Any]:
    return {
        "id": str(a.id), "code": a.code, "category": a.category, "names": a.names,
        "descriptions": a.descriptions, "icon": a.icon, "metric": a.metric,
        "threshold": a.threshold, "xp_reward": a.xp_reward, "title": a.title,
        "sort_order": a.sort_order, "enabled": a.enabled, "unlocked_by": unlocked,
    }  # fmt: skip


@router.get("/achievements")
async def list_achievements(_: Reader, db: Db) -> list[dict[str, Any]]:
    from app.models import UserAchievement

    counts = dict(
        (
            await db.execute(
                select(UserAchievement.achievement_id, func.count()).group_by(
                    UserAchievement.achievement_id
                )
            )
        ).all()
    )
    rows = (
        await db.scalars(select(Achievement).order_by(Achievement.category, Achievement.sort_order))
    ).all()
    return [_ach_out(a, int(counts.get(a.id, 0))) for a in rows]


@router.post("/achievements", status_code=201)
async def create_achievement(
    body: AchievementIn, actor: Writer, db: Db, client: Client
) -> dict[str, Any]:
    a = Achievement(**body.model_dump())
    db.add(a)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("An achievement with this code exists.", code="achievement_exists") from exc
    _audit(db, actor, client, "game.achievement_created", "achievement", a.id, {"code": a.code})
    await db.commit()
    return _ach_out(a)


@router.patch("/achievements/{achievement_id}")
async def update_achievement(
    achievement_id: uuid.UUID, body: AchievementPatch, actor: Writer, db: Db, client: Client
) -> dict[str, Any]:
    a = await db.get(Achievement, achievement_id, with_for_update=True)
    if a is None:
        raise NotFound("No such achievement.")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(a, k, v)
    if changes:
        _audit(db, actor, client, "game.achievement_updated", "achievement", a.id,
               {"code": a.code, "fields": sorted(changes)})  # fmt: skip
    await db.commit()
    return _ach_out(a)


# --- daily challenges --------------------------------------------------------------------
class ChallengeIn(BaseModel):
    code: Code
    difficulty: Literal["easy", "medium", "hard"]
    names: Text
    metric: CH_METRICS
    target: Annotated[int, Field(ge=1, le=1000)]
    xp_reward: Annotated[int, Field(ge=0, le=100_000)]
    enabled: bool = True


class ChallengePatch(BaseModel):
    names: Text | None = None
    target: Annotated[int | None, Field(ge=1, le=1000)] = None
    xp_reward: Annotated[int | None, Field(ge=0, le=100_000)] = None
    enabled: bool | None = None


def _ch_out(t: ChallengeTemplate) -> dict[str, Any]:
    return {
        "id": str(t.id), "code": t.code, "difficulty": t.difficulty, "names": t.names,
        "metric": t.metric, "target": t.target, "xp_reward": t.xp_reward, "enabled": t.enabled,
    }  # fmt: skip


@router.get("/challenges")
async def list_challenges(_: Reader, db: Db) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(ChallengeTemplate).order_by(ChallengeTemplate.difficulty, ChallengeTemplate.code)
        )
    ).all()
    return [_ch_out(t) for t in rows]


@router.post("/challenges", status_code=201)
async def create_challenge(
    body: ChallengeIn, actor: Writer, db: Db, client: Client
) -> dict[str, Any]:
    t = ChallengeTemplate(**body.model_dump())
    db.add(t)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("A challenge with this code exists.", code="challenge_exists") from exc
    _audit(db, actor, client, "game.challenge_created", "challenge", t.id, {"code": t.code})
    await db.commit()
    return _ch_out(t)


@router.patch("/challenges/{challenge_id}")
async def update_challenge(
    challenge_id: uuid.UUID, body: ChallengePatch, actor: Writer, db: Db, client: Client
) -> dict[str, Any]:
    """Changes apply to challenges handed out from now on (today's keep their target)."""
    t = await db.get(ChallengeTemplate, challenge_id, with_for_update=True)
    if t is None:
        raise NotFound("No such challenge.")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(t, k, v)
    if changes:
        _audit(db, actor, client, "game.challenge_updated", "challenge", t.id,
               {"code": t.code, "fields": sorted(changes)})  # fmt: skip
    await db.commit()
    return _ch_out(t)


# --- seasons -----------------------------------------------------------------------------
class SeasonIn(BaseModel):
    name: Annotated[str, Field(min_length=3, max_length=64)]
    starts_at: dt.datetime
    ends_at: dt.datetime
    board: Literal["xp", "wins"] = "xp"
    rewards: list[RewardTier] | None = None  # default: the weekly prizes

    @model_validator(mode="after")
    def _dates(self) -> SeasonIn:
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("give dates with a time zone, e.g. 2026-12-01T00:00:00+03:00")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.ends_at - self.starts_at > dt.timedelta(days=92):
            raise ValueError("a season lasts at most 92 days")
        return self


class SeasonPatch(BaseModel):
    reason: Reason
    name: Annotated[str | None, Field(min_length=3, max_length=64)] = None
    starts_at: dt.datetime | None = None
    ends_at: dt.datetime | None = None
    board: Literal["xp", "wins"] | None = None
    rewards: list[RewardTier] | None = None


@router.get("/seasons")
async def list_seasons(
    _: Reader,
    db: Db,
    status: Annotated[Literal["active", "closed"] | None, Query()] = None,
    limit: Limit = 30,
    offset: Offset = 0,
) -> list[dict[str, Any]]:
    stmt = select(Season).order_by(Season.status, Season.ends_at.desc())
    if status:
        stmt = stmt.where(Season.status == status)
    seasons = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    counts = dict(
        (
            await db.execute(
                select(SeasonStat.season_id, func.count())
                .where(SeasonStat.season_id.in_([s.id for s in seasons]))
                .group_by(SeasonStat.season_id)
            )
        ).all()
    )
    out = []
    for s in seasons:
        winners = await boards.results(db, s.id, s.board, 3) if s.status == "closed" else []
        out.append(
            {**boards.season_out(s), "participants": int(counts.get(s.id, 0)), "winners": winners}
        )
    return out


@router.post("/seasons", status_code=201)
async def create_season(body: SeasonIn, actor: Writer, db: Db, client: Client) -> dict[str, Any]:
    """A special event season with its own dates and prizes, next to the weekly/monthly ones."""
    cfg = await games.config(db)
    s = Season(
        kind="event", name=body.name, starts_at=body.starts_at, ends_at=body.ends_at,
        board=body.board, rewards=body.rewards or cfg["games.seasons.rewards_weekly"],
    )  # fmt: skip
    db.add(s)
    await db.flush()
    span = {"name": s.name, "starts_at": s.starts_at.isoformat(), "ends_at": s.ends_at.isoformat()}
    _audit(db, actor, client, "game.season_created", "season", s.id, span)
    await db.commit()
    return boards.season_out(s)


@router.patch("/seasons/{season_id}")
async def update_season(
    season_id: uuid.UUID, body: SeasonPatch, actor: Writer, db: Db, client: Client
) -> dict[str, Any]:
    """Change an active season: name, dates (the start only before it begins), prize board,
    prizes. Closed seasons are history and can't change."""
    s = await db.get(Season, season_id, with_for_update=True)
    if s is None:
        raise NotFound("No such season.")
    if s.status != "active":
        raise Conflict("A finished season can't be changed.", code="season_closed")
    now = utcnow()
    changes: dict[str, Any] = {}
    if body.starts_at is not None and body.starts_at != s.starts_at:
        if s.starts_at <= now:
            raise Conflict("The season has already started.", code="season_started")
        changes["starts_at"] = [s.starts_at.isoformat(), body.starts_at.isoformat()]
        s.starts_at = body.starts_at
    if body.ends_at is not None and body.ends_at != s.ends_at:
        changes["ends_at"] = [s.ends_at.isoformat(), body.ends_at.isoformat()]
        s.ends_at = body.ends_at
    if s.ends_at <= s.starts_at:
        raise Conflict("The end must be after the start.", code="season_dates")
    for field in ("name", "board", "rewards"):
        value = getattr(body, field)
        if value is not None and value != getattr(s, field):
            changes[field] = value if field != "rewards" else "changed"
            setattr(s, field, value)
    if changes:
        _audit(
            db,
            actor,
            client,
            "game.season_updated",
            "season",
            s.id,
            {"reason": body.reason, **changes},
        )
    await db.commit()
    return boards.season_out(s)


@router.post("/seasons/{season_id}/finish")
async def finish_season(
    season_id: uuid.UUID, body: ReasonIn, actor: Writer, ctx: Ctx, db: Db, client: Client
) -> dict[str, Any]:
    """End an active season now: freeze the tables and give the prizes (once)."""
    cfg = await games.config(db)
    s = await db.get(Season, season_id, with_for_update=True)
    if s is None:
        raise NotFound("No such season.")
    if s.status != "active":
        raise Conflict("This season is already closed.", code="season_closed")
    now = utcnow()
    if s.ends_at > now:
        s.ends_at = max(now, s.starts_at + dt.timedelta(seconds=1))
    _audit(db, actor, client, "game.season_finished", "season", s.id, {"reason": body.reason})
    await db.flush()
    prizes = await boards.finalize(db, cfg, s.id, now=max(now, s.ends_at))
    await db.commit()
    return {**boards.season_out(s), "prizes": len(prizes)}


@router.get("/seasons/{season_id}/results")
async def season_results(
    season_id: uuid.UUID,
    _: Reader,
    db: Db,
    board: Annotated[Literal["wins", "winrate", "xp"], Query()] = "xp",
) -> dict[str, Any]:
    """Final table of a closed season, or the live ranking of an active one."""
    cfg = await games.config(db)
    s = await db.get(Season, season_id)
    if s is None:
        raise NotFound("No such season.")
    if s.status == "closed":
        return {
            "season": boards.season_out(s),
            "board": board,
            "rows": await boards.results(db, s.id, board),
        }
    live = await boards.board(db, cfg, board, season=s, user_id=None, limit=100)
    return {"season": boards.season_out(s), "board": board, "rows": live["rows"], "live": True}
