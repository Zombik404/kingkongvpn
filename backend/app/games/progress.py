"""Blackjack progression (ADR-021): XP and levels, achievements, daily challenges, daily streak,
season statistics and rewards.

Everything here runs on the server inside the transaction that settles a round (or finalises a
season), so the client can never send a score. Every grant has a unique key — XP events, rewards,
achievements and challenge completions are each recorded at most once per player.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.games import wallet
from app.models import (
    Achievement,
    ChallengeTemplate,
    DailyChallenge,
    GameProfile,
    GameReward,
    PlayDay,
    Season,
    SeasonStat,
    UserAchievement,
    UserTitle,
    XpEvent,
)
from app.models.base import utcnow
from app.models.enums import ActorType
from app.services import audit

Event = dict[str, Any]
AVATARS = ("🦍", "🐒", "🦧", "🦜", "🐆", "🐍", "🐸", "🦥", "🐘", "🐯", "🦩", "🍌")
FRAME_RANK = {None: 0, "jade": 1, "bronze": 2, "silver": 3, "gold": 4}
MAX_LEVEL = 9999


# --- levels ------------------------------------------------------------------------------
def xp_to_reach(level: int, base: int, step: int) -> int:
    """Total XP needed to reach `level` (level 1 = 0). Level n → n+1 costs base + step·(n-1)."""
    n = max(0, level - 1)
    return n * base + step * n * (n - 1) // 2


def level_for(xp: int, base: int, step: int) -> int:
    lo, hi = 1, MAX_LEVEL
    while lo < hi:  # the highest level whose threshold is <= xp
        mid = (lo + hi + 1) // 2
        if xp_to_reach(mid, base, step) <= xp:
            lo = mid
        else:
            hi = mid - 1
    return lo


def level_title(level: int, titles: dict[str, str]) -> str:
    best = max((int(k) for k in titles if int(k) <= level), default=None)
    return titles[str(best)] if best is not None else ""


def level_info(xp: int, cfg: dict[str, Any]) -> dict[str, Any]:
    base, step = cfg["games.levels.base_xp"], cfg["games.levels.step_xp"]
    level = level_for(xp, base, step)
    start, nxt = xp_to_reach(level, base, step), xp_to_reach(level + 1, base, step)
    return {
        "level": level,
        "xp": xp,
        "level_xp": start,
        "next_level_xp": nxt,
        "progress": round((xp - start) / (nxt - start), 4) if nxt > start else 1.0,
        "level_title": level_title(level, cfg["games.levels.titles"]),
    }


def display_title(p: GameProfile, cfg: dict[str, Any]) -> str:
    return p.title or level_title(p.level, cfg["games.levels.titles"])


# --- time --------------------------------------------------------------------------------
def tz(cfg: dict[str, Any]) -> ZoneInfo:
    return ZoneInfo(cfg["games.timezone"])


def game_day(now: dt.datetime, cfg: dict[str, Any]) -> dt.date:
    return now.astimezone(tz(cfg)).date()


def next_day_start(now: dt.datetime, cfg: dict[str, Any]) -> dt.datetime:
    day = game_day(now, cfg) + dt.timedelta(days=1)
    return dt.datetime.combine(day, dt.time(0), tzinfo=tz(cfg)).astimezone(dt.UTC)


# --- XP ----------------------------------------------------------------------------------
async def add_xp(
    db: AsyncSession,
    cfg: dict[str, Any],
    profile: GameProfile,
    amount: int,
    kind: str,
    key: str,
    events: list[Event],
    *,
    source: str | None = None,
    seasons: list[Season] | None = None,
) -> int:
    """Add XP once per (user, key); returns what was added (0 for a repeat or amount 0)."""
    if amount <= 0:
        return 0
    inserted = await db.scalar(
        pg_insert(XpEvent)
        .values(
            id=uuid.uuid4(),
            user_id=profile.user_id,
            amount=amount,
            kind=kind,
            source=source,
            idem_key=key[:96],
        )
        .on_conflict_do_nothing(constraint="uq_game_xp_events_user_idem")
        .returning(XpEvent.id)
    )
    if inserted is None:
        return 0
    now = utcnow()
    before = profile.level
    profile.xp += amount
    profile.score_at = now
    info = level_info(profile.xp, cfg)
    profile.level = info["level"]
    events.append({"type": "xp", "amount": amount, "kind": kind})
    if profile.level > before:
        events.append({"type": "level", "level": profile.level, "title": info["level_title"]})
    for season in seasons or []:
        await db.execute(
            update(SeasonStat)
            .where(SeasonStat.season_id == season.id, SeasonStat.user_id == profile.user_id)
            .values(xp=SeasonStat.xp + amount, score_at=now)
        )
    return amount


# --- rewards (seasons, streaks) ----------------------------------------------------------
async def grant_reward(
    db: AsyncSession,
    cfg: dict[str, Any],
    profile: GameProfile,
    tier: dict[str, Any],
    *,
    source: str,
    ref: str,
    key: str,
    events: list[Event],
    seasons: list[Season] | None = None,
) -> bool:
    """One reward, once: XP, a title, a frame and — only if games.rewards.bonus_days_enabled —
    bonus days into the game wallet (never the paid subscription). Returns False on a repeat."""
    days = int(tier.get("bonus_days", 0) or 0)
    pay_days = days > 0 and bool(cfg["games.rewards.bonus_days_enabled"])
    rid = await db.scalar(
        pg_insert(GameReward)
        .values(
            id=uuid.uuid4(),
            user_id=profile.user_id,
            source=source,
            source_ref=ref[:64],
            xp=int(tier.get("xp", 0) or 0),
            title=tier.get("title"),
            frame=tier.get("frame"),
            bonus_days=days,
            bonus_paid=pay_days,
            idem_key=key[:96],
        )
        .on_conflict_do_nothing(constraint="uq_game_rewards_user_idem")
        .returning(GameReward.id)
    )
    if rid is None:
        return False
    await add_xp(
        db, cfg, profile, int(tier.get("xp", 0) or 0), source, f"reward:{key}", events,
        source=ref, seasons=seasons,
    )  # fmt: skip
    if tier.get("title"):
        await db.execute(
            pg_insert(UserTitle)
            .values(id=uuid.uuid4(), user_id=profile.user_id, title=tier["title"], source=source)
            .on_conflict_do_nothing(constraint="uq_game_user_titles")
        )
    frame = tier.get("frame")
    if frame and FRAME_RANK.get(frame, 0) >= FRAME_RANK.get(profile.frame, 0):
        profile.frame = frame
    if pay_days:
        await wallet.move(
            db, profile.user_id, days * wallet.HOURS_PER_DAY, "reward", f"reward:{key}",
            note=f"{source} {ref}"[:200],
        )  # fmt: skip
    events.append(
        {
            "type": "reward",
            "source": source,
            "xp": int(tier.get("xp", 0) or 0),
            "title": tier.get("title"),
            "frame": frame,
            "bonus_days": days if pay_days else 0,
        }
    )
    return True


# --- achievements ------------------------------------------------------------------------
def metric_value(p: GameProfile, metric: str) -> int:
    return int(
        {
            "wins": p.wins,
            "rounds": p.rounds,
            "blackjacks": p.blackjacks,
            "best_win_streak": p.best_streak,
            "perfect_wins": p.perfect_wins,
            "best_day_streak": p.best_day_streak,
            "days_played": p.days_played,
            "level": p.level,
            "xp": p.xp,
        }.get(metric, 0)
    )


async def unlock(
    db: AsyncSession,
    cfg: dict[str, Any],
    profile: GameProfile,
    ach: Achievement,
    events: list[Event],
    seasons: list[Season] | None = None,
) -> bool:
    got = await db.scalar(
        pg_insert(UserAchievement)
        .values(
            id=uuid.uuid4(),
            user_id=profile.user_id,
            achievement_id=ach.id,
            unlocked_at=utcnow(),
        )
        .on_conflict_do_nothing(constraint="uq_game_user_achievements")
        .returning(UserAchievement.id)
    )
    if got is None:
        return False
    events.append(
        {
            "type": "achievement",
            "code": ach.code,
            "names": ach.names,
            "icon": ach.icon,
            "xp": ach.xp_reward,
        }
    )
    if ach.title:
        await db.execute(
            pg_insert(UserTitle)
            .values(id=uuid.uuid4(), user_id=profile.user_id, title=ach.title, source="achievement")
            .on_conflict_do_nothing(constraint="uq_game_user_titles")
        )
    await add_xp(
        db, cfg, profile, ach.xp_reward, "achievement", f"ach:{ach.code}", events,
        source=ach.code, seasons=seasons,
    )  # fmt: skip
    return True


async def check_achievements(
    db: AsyncSession,
    cfg: dict[str, Any],
    profile: GameProfile,
    events: list[Event],
    seasons: list[Season] | None = None,
) -> None:
    if not cfg["games.achievements.enabled"]:
        return
    catalogue = (
        await db.scalars(
            select(Achievement).where(
                Achievement.enabled.is_(True), Achievement.category != "season"
            )
        )
    ).all()
    have = set(
        (
            await db.scalars(
                select(UserAchievement.achievement_id).where(
                    UserAchievement.user_id == profile.user_id
                )
            )
        ).all()
    )
    for _ in range(4):  # XP from one achievement can reach a level that unlocks another
        new = [
            a
            for a in catalogue
            if a.id not in have and metric_value(profile, a.metric) >= a.threshold
        ]
        if not new:
            return
        for a in new:
            await unlock(db, cfg, profile, a, events, seasons)
            have.add(a.id)


# --- daily challenges --------------------------------------------------------------------
async def todays_challenges(
    db: AsyncSession, cfg: dict[str, Any], user_id: uuid.UUID, day: dt.date
) -> list[tuple[DailyChallenge, ChallengeTemplate]]:
    """The player's challenges for `day`, handing out one easy, one medium and one hard first
    (picked from the enabled templates by a hash of user and day: stable, not guessable)."""
    rows = (
        await db.execute(
            select(DailyChallenge, ChallengeTemplate)
            .join(ChallengeTemplate, ChallengeTemplate.id == DailyChallenge.template_id)
            .where(DailyChallenge.user_id == user_id, DailyChallenge.day == day)
        )
    ).all()
    if rows or not cfg["games.challenges.enabled"]:
        return [(c, t) for c, t in rows]
    templates = (
        await db.scalars(
            select(ChallengeTemplate)
            .where(ChallengeTemplate.enabled.is_(True))
            .order_by(ChallengeTemplate.code)
        )
    ).all()
    for difficulty in ("easy", "medium", "hard"):
        pool = [t for t in templates if t.difficulty == difficulty]
        if not pool:
            continue
        h = hashlib.sha256(f"{user_id}:{day.isoformat()}:{difficulty}".encode()).digest()
        t = pool[int.from_bytes(h[:4], "big") % len(pool)]
        await db.execute(
            pg_insert(DailyChallenge)
            .values(
                id=uuid.uuid4(),
                user_id=user_id,
                day=day,
                template_id=t.id,
                target=t.target,
                xp_reward=t.xp_reward,
            )
            .on_conflict_do_nothing(constraint="uq_game_daily_challenges")
        )
    rows = (
        await db.execute(
            select(DailyChallenge, ChallengeTemplate)
            .join(ChallengeTemplate, ChallengeTemplate.id == DailyChallenge.template_id)
            .where(DailyChallenge.user_id == user_id, DailyChallenge.day == day)
            .with_for_update(of=DailyChallenge)
        )
    ).all()
    return [(c, t) for c, t in rows]


def _challenge_step(c: DailyChallenge, metric: str, r: dict[str, Any], high_win: bool) -> None:
    win = r["result"] == "win"
    if metric == "rounds":
        c.progress += 1
    elif metric == "wins" and win:
        c.progress += 1
    elif metric == "blackjacks" and r["blackjack"]:
        c.progress += 1
    elif metric == "high_wins" and high_win:
        c.progress += 1
    elif metric == "win_run":
        if win:
            c.run += 1
        elif r["result"] == "lose":
            c.run = 0  # a push neither extends nor breaks the run
        c.progress = max(c.progress, c.run)


# --- seasons -----------------------------------------------------------------------------
async def active_seasons(db: AsyncSession, now: dt.datetime) -> list[Season]:
    return list(
        (
            await db.scalars(
                select(Season).where(
                    Season.status == "active", Season.starts_at <= now, Season.ends_at > now
                )
            )
        ).all()
    )


# --- one finished round ------------------------------------------------------------------
async def record_round(
    db: AsyncSession,
    cfg: dict[str, Any],
    profile: GameProfile,
    round_id: uuid.UUID,
    r: dict[str, Any],
    *,
    now: dt.datetime | None = None,
    seasons: list[Season] | None = None,
) -> list[Event]:
    """Apply a settled round to the player's progression. `r` is the engine's result for the
    seat (server-side truth); the caller has already updated wins/losses/streaks."""
    now = now or utcnow()
    events: list[Event] = []
    uid = profile.user_id
    day = game_day(now, cfg)
    win = r["result"] == "win"
    hands = r.get("hands") or []
    winning = [h for h in hands if h["outcome"] in ("win", "blackjack")]
    if win and any(h["outcome"] == "win" and h["total"] == 21 for h in hands):
        profile.perfect_wins += 1
    high_win = win and any(h["total"] in (20, 21) for h in winning)
    if win:
        profile.score_at = now

    # play day
    pd = await db.scalar(
        pg_insert(PlayDay)
        .values(user_id=uid, day=day, rounds=1)
        .on_conflict_do_update(
            index_elements=[PlayDay.user_id, PlayDay.day], set_={"rounds": PlayDay.rounds + 1}
        )
        .returning(PlayDay.round_xp)
    )
    # season statistics
    for season in seasons or []:
        await db.execute(
            pg_insert(SeasonStat)
            .values(
                season_id=season.id,
                user_id=uid,
                rounds=1,
                wins=int(win),
                losses=int(r["result"] == "lose"),
                pushes=int(r["result"] not in ("win", "lose")),
                blackjacks=int(r["blackjack"]),
                score_at=now,
            )
            .on_conflict_do_update(
                index_elements=[SeasonStat.season_id, SeasonStat.user_id],
                set_={
                    "rounds": SeasonStat.rounds + 1,
                    "wins": SeasonStat.wins + int(win),
                    "losses": SeasonStat.losses + int(r["result"] == "lose"),
                    "pushes": SeasonStat.pushes + int(r["result"] not in ("win", "lose")),
                    "blackjacks": SeasonStat.blackjacks + int(r["blackjack"]),
                    **({"score_at": now} if win else {}),
                },
            )
        )

    # daily streak (rewards after the season row exists, so their XP counts there too)
    if profile.last_play_day != day:
        yesterday = day - dt.timedelta(days=1)
        profile.day_streak = profile.day_streak + 1 if profile.last_play_day == yesterday else 1
        profile.best_day_streak = max(profile.best_day_streak, profile.day_streak)
        profile.last_play_day = day
        profile.days_played += 1
        events.append({"type": "streak", "days": profile.day_streak})
        tier = cfg["games.streak.rewards"].get(str(profile.day_streak))
        if tier:
            start = day - dt.timedelta(days=profile.day_streak - 1)
            await grant_reward(
                db, cfg, profile, tier, source="streak", ref=f"{profile.day_streak} days",
                key=f"streak:{profile.day_streak}:{start.isoformat()}", events=events,
                seasons=seasons,
            )  # fmt: skip

    # XP for the round, within the daily cap
    amount = (
        cfg["games.xp.round"]
        + (cfg["games.xp.win"] if win else 0)
        + (cfg["games.xp.blackjack"] if r["blackjack"] else 0)
    )
    cap = cfg["games.xp.daily_round_cap"]
    used = int(pd or 0)
    give = min(amount, max(0, cap - used)) if cap else amount
    if give:
        await db.execute(
            update(PlayDay)
            .where(and_(PlayDay.user_id == uid, PlayDay.day == day))
            .values(round_xp=PlayDay.round_xp + give)
        )
        await add_xp(
            db, cfg, profile, give, "round", f"round:{round_id}", events,
            source=str(round_id), seasons=seasons,
        )  # fmt: skip
    if cap and used < cap <= used + amount:
        events.append({"type": "xp_cap"})
        audit.record(
            db,
            action="game.xp_daily_cap",
            actor_id=uid,
            actor_type=ActorType.USER,
            target_type="user",
            target_id=uid,
            details={"day": day.isoformat(), "cap": cap},
        )

    # daily challenges
    for c, t in await todays_challenges(db, cfg, uid, day):
        if c.completed_at is not None:
            continue
        _challenge_step(c, t.metric, r, high_win)
        if c.progress >= c.target:
            c.progress = c.target
            c.completed_at = now
            events.append({"type": "challenge", "names": t.names, "xp": c.xp_reward})
            await add_xp(
                db, cfg, profile, c.xp_reward, "challenge", f"challenge:{c.id}", events,
                source=t.code, seasons=seasons,
            )  # fmt: skip

    await check_achievements(db, cfg, profile, events, seasons)
    return events
