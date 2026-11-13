"""What the Mini App shows about progression: profile, achievements, challenges, streak, XP and
reward history, seasons (ADR-021). Read-only, except handing out today's challenges."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.games import boards, progress
from app.models import (
    Achievement,
    ChallengeTemplate,
    DailyChallenge,
    GameProfile,
    GameReward,
    PlayDay,
    Season,
    SeasonResult,
    SeasonStat,
    UserAchievement,
    UserTitle,
    XpEvent,
)
from app.models.base import utcnow


class ProfileError(AppError):
    status_code = 422
    code = "invalid_profile"


def card(p: GameProfile, cfg: dict[str, Any]) -> dict[str, Any]:
    """The small profile block used on the hub and in lists."""
    decided = p.wins + p.losses
    return {
        "nickname": p.nickname,
        "avatar": p.avatar,
        "frame": p.frame,
        "title": progress.display_title(p, cfg),
        **progress.level_info(p.xp, cfg),
        "rounds": p.rounds,
        "wins": p.wins,
        "losses": p.losses,
        "pushes": p.pushes,
        "blackjacks": p.blackjacks,
        "win_rate": round(p.wins * 100 / decided, 1) if decided else None,
        "win_streak": p.streak,
        "best_win_streak": p.best_streak,
        "day_streak": p.day_streak,
        "best_day_streak": p.best_day_streak,
        "days_played": p.days_played,
    }


async def titles_of(db: AsyncSession, p: GameProfile, cfg: dict[str, Any]) -> list[str]:
    """Titles the player may wear: every level title reached plus titles won."""
    reached = [
        t for lv, t in sorted(cfg["games.levels.titles"].items(), key=lambda kv: int(kv[0]))
        if int(lv) <= p.level
    ]  # fmt: skip
    won = (
        await db.scalars(
            select(UserTitle.title)
            .where(UserTitle.user_id == p.user_id)
            .order_by(UserTitle.created_at)
        )
    ).all()
    return list(dict.fromkeys([*reached, *won]))


async def set_looks(
    db: AsyncSession,
    p: GameProfile,
    cfg: dict[str, Any],
    *,
    avatar: str | None,
    title: str | None,
) -> None:
    if avatar is not None:
        if avatar not in progress.AVATARS:
            raise ProfileError("Pick one of the offered avatars.")
        p.avatar = avatar
    if title is not None:
        if title == "":
            p.title = None  # back to the level title
        elif title not in await titles_of(db, p, cfg):
            raise ProfileError("You haven't earned that title yet.")
        else:
            p.title = title


async def ranks(db: AsyncSession, cfg: dict[str, Any], user_id: uuid.UUID) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for name in ("xp", "wins"):
        b = await boards.board(db, cfg, name, season=None, user_id=user_id, limit=0)
        out[name] = b["me"]["rank"] if b["me"] else None
    return out


async def achievements(db: AsyncSession, p: GameProfile) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(Achievement, UserAchievement.unlocked_at)
            .outerjoin(
                UserAchievement,
                (UserAchievement.achievement_id == Achievement.id)
                & (UserAchievement.user_id == p.user_id),
            )
            .where(Achievement.enabled.is_(True) | UserAchievement.unlocked_at.is_not(None))
            .order_by(Achievement.category, Achievement.sort_order, Achievement.threshold)
        )
    ).all()
    best_rank = await db.scalar(
        select(func.min(SeasonResult.rank))
        .join(Season, Season.id == SeasonResult.season_id)
        .where(SeasonResult.user_id == p.user_id, SeasonResult.board == Season.board)
    )
    out = []
    for a, unlocked in rows:
        if a.metric == "season_rank":
            value = 1 if unlocked else 0
            target = 1
            current = int(best_rank) if best_rank else None
        else:
            value, target, current = progress.metric_value(p, a.metric), a.threshold, None
        out.append(
            {
                "code": a.code,
                "category": a.category,
                "names": a.names,
                "descriptions": a.descriptions,
                "icon": a.icon,
                "xp": a.xp_reward,
                "title": a.title,
                "progress": min(value, target),
                "target": target,
                "best_rank": current,
                "unlocked_at": unlocked.isoformat() if unlocked else None,
            }
        )
    return out


async def challenges(
    db: AsyncSession, cfg: dict[str, Any], p: GameProfile, now: dt.datetime | None = None
) -> dict[str, Any]:
    now = now or utcnow()
    day = progress.game_day(now, cfg)
    today = await progress.todays_challenges(db, cfg, p.user_id, day)
    order = {"easy": 0, "medium": 1, "hard": 2}
    today.sort(key=lambda ct: order.get(ct[1].difficulty, 9))
    since = day - dt.timedelta(days=34)
    played = (
        await db.execute(
            select(PlayDay.day, PlayDay.rounds)
            .where(PlayDay.user_id == p.user_id, PlayDay.day >= since)
            .order_by(PlayDay.day)
        )
    ).all()
    done = (
        await db.execute(
            select(DailyChallenge, ChallengeTemplate)
            .join(ChallengeTemplate, ChallengeTemplate.id == DailyChallenge.template_id)
            .where(DailyChallenge.user_id == p.user_id, DailyChallenge.completed_at.is_not(None))
            .order_by(DailyChallenge.completed_at.desc())
            .limit(20)
        )
    ).all()
    alive = p.last_play_day is not None and p.last_play_day >= day - dt.timedelta(days=1)
    streak = p.day_streak if alive else 0
    rewards = cfg["games.streak.rewards"]
    upcoming = sorted(int(k) for k in rewards if int(k) > streak)
    return {
        "day": day.isoformat(),
        "resets_at": progress.next_day_start(now, cfg).isoformat(),
        "enabled": bool(cfg["games.challenges.enabled"]),
        "today": [
            {
                "id": str(c.id),
                "code": t.code,
                "difficulty": t.difficulty,
                "names": t.names,
                "progress": c.progress,
                "target": c.target,
                "xp": c.xp_reward,
                "completed_at": c.completed_at.isoformat() if c.completed_at else None,
            }
            for c, t in today
        ],
        "streak": {
            "current": streak,
            "best": p.best_day_streak,
            "played_today": p.last_play_day == day,
            "next_reward": (
                {"days": upcoming[0], **rewards[str(upcoming[0])]} if upcoming else None
            ),
            "rewards": [
                {"days": int(k), **v} for k, v in sorted(rewards.items(), key=lambda kv: int(kv[0]))
            ],
            "bonus_days_enabled": bool(cfg["games.rewards.bonus_days_enabled"]),
        },
        "calendar": [{"day": d.isoformat(), "rounds": n} for d, n in played],
        "history": [
            {"names": t.names, "xp": c.xp_reward, "day": c.day.isoformat()} for c, t in done
        ],
    }


async def xp_history(
    db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int
) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(XpEvent)
            .where(XpEvent.user_id == user_id)
            .order_by(XpEvent.created_at.desc(), XpEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [
        {"amount": e.amount, "kind": e.kind, "source": e.source, "at": e.created_at.isoformat()}
        for e in rows
    ]


async def rewards(
    db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int
) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(GameReward)
            .where(GameReward.user_id == user_id)
            .order_by(GameReward.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [
        {
            "source": r.source,
            "ref": r.source_ref,
            "xp": r.xp,
            "title": r.title,
            "frame": r.frame,
            "bonus_days": r.bonus_days,
            "bonus_paid": r.bonus_paid,
            "at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def seasons(
    db: AsyncSession, cfg: dict[str, Any], user_id: uuid.UUID, offset: int, limit: int
) -> dict[str, Any]:
    now = utcnow()
    current = []
    for kind in ("weekly", "monthly"):
        s = await boards.current(db, kind, now)
        if s is None:
            continue
        stat = await db.get(SeasonStat, (s.id, user_id))
        b = await boards.board(db, cfg, s.board, season=s, user_id=user_id, limit=3)
        current.append(
            {
                **boards.season_out(s),
                "participants": b["total"],
                "top": b["rows"],
                "me": b["me"],
                "my_rounds": stat.rounds if stat else 0,
                "min_rounds": cfg["games.seasons.min_rounds"],
            }
        )
    events = (
        await db.scalars(
            select(Season)
            .where(Season.kind == "event", Season.status == "active", Season.ends_at > now)
            .order_by(Season.starts_at)
        )
    ).all()
    closed = (
        await db.scalars(
            select(Season)
            .where(Season.status == "closed")
            .order_by(Season.ends_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    archive = []
    for s in closed:
        archive.append(
            {**boards.season_out(s), "winners": await boards.results(db, s.id, s.board, 3)}
        )
    return {
        "now": now.isoformat(),
        "current": current,
        "events": [boards.season_out(s) for s in events],
        "archive": archive,
        "bonus_days_enabled": bool(cfg["games.rewards.bonus_days_enabled"]),
    }
