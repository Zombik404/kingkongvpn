"""Referral program.

Each user gets a personal link (`t.me/<bot>?start=ref_<code>`).

- The **invited user** gets `referrals.percent_off` (default 30 %) off their **first** payment,
  applied automatically at checkout (not combined with a promo code — the promo price wins).
- The **referrer** gets `referrals.bonus_days` (default 14) free days for every invited user whose
  first payment succeeds — the live subscription is extended, or a new one started if they have
  none. No discount for the referrer.

One credit per invited user (unique `referral_rewards.referred_id`).

**Ranks** (`referrals.milestones`): counting invited users who *paid* (so empty sign-ups don't
count), the referrer reaches LEVELS below; each gives a one-time gift of free days and unlocks a
Mini App colour theme (cosmetic, chosen on the device).
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict
from app.core.ids import uuid7
from app.models import Payment, Plan, ReferralMilestone, ReferralReward, Subscription, User
from app.models.enums import ActorType, PaymentStatus, Provider
from app.services import audit
from app.services import settings as settings_service
from app.subscriptions import service as subs

if TYPE_CHECKING:
    from app.core.config import Settings

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True)
class Level:
    code: str  # rank id; names are translated by the clients / `referral.ranks.<code>`
    need: int  # invited users who paid
    days: int  # one-time gift
    theme: str  # Mini App theme unlocked


BASE_RANK = "chick"
LEVELS: tuple[Level, ...] = (
    Level("fox", 3, 7, "lava"),
    Level("hacker", 5, 30, "matrix"),
    Level("ambassador", 10, 90, "gold"),
    Level("legend", 25, 365, "cosmos"),
)


def rank_for(paid: int) -> str:
    reached = [lv.code for lv in LEVELS if paid >= lv.need]
    return reached[-1] if reached else BASE_RANK


@dataclass(frozen=True)
class Granted:
    """What the referrer earned (for the notifications after commit)."""

    referrer: User
    bonus_days: int  # per-friend days (0 = none this time)
    subscription: Subscription  # the referrer's subscription after all grants
    paid_friends: int
    milestones: tuple[Level, ...] = ()


class InvalidReferral(AppError):
    status_code = 422
    code = "invalid_referral"
    message = "This referral link isn't valid for your account."


async def ensure_code(db: AsyncSession, user_id: uuid.UUID) -> str:
    user = await db.get(User, user_id, with_for_update=True)
    assert user is not None
    if user.referral_code:
        return user.referral_code
    for _ in range(10):
        code = "".join(secrets.choice(ALPHABET) for _ in range(8))
        if await db.scalar(select(User.id).where(User.referral_code == code)) is None:
            user.referral_code = code
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                user = await db.get(User, user_id, with_for_update=True)
                assert user is not None
                continue
            return code
    raise Conflict("Couldn't create a referral code, try again.")


def link_for(settings: Settings, code: str) -> str | None:
    bot = settings.telegram_bot_username
    return f"https://t.me/{bot}?start=ref_{code}" if bot else None


async def claim(db: AsyncSession, user_id: uuid.UUID, code: str, ip: str | None) -> None:
    """Attach the referrer. Only for accounts that haven't paid yet and have no referrer."""
    user = await db.get(User, user_id, with_for_update=True)
    assert user is not None
    code = code.strip().upper()
    referrer = await db.scalar(select(User).where(User.referral_code == code))
    if referrer is None or not referrer.is_active or referrer.id == user.id:
        raise InvalidReferral()
    if user.referred_by_id is not None:
        if user.referred_by_id == referrer.id:
            return  # idempotent: the Mini App may claim again on every open
        raise InvalidReferral("You were already invited by someone else.")
    paid = await db.scalar(
        select(func.count())
        .select_from(Payment)
        .where(Payment.user_id == user.id, Payment.status == PaymentStatus.SUCCEEDED)
    )
    if paid:
        raise InvalidReferral("Referral links work only before the first payment.")
    user.referred_by_id = referrer.id
    audit.record(
        db,
        action="referral.claimed",
        actor_id=user.id,
        target_type="user",
        target_id=referrer.id,
        ip=ip,
    )
    await db.commit()


async def _has_paid(
    db: AsyncSession, user_id: uuid.UUID, *, except_id: uuid.UUID | None = None
) -> bool:
    q = (
        select(func.count())
        .select_from(Payment)
        .where(Payment.user_id == user_id, Payment.status == PaymentStatus.SUCCEEDED)
    )
    if except_id is not None:
        q = q.where(Payment.id != except_id)
    return bool(await db.scalar(q))


async def invitee_discount(db: AsyncSession, user: User) -> int:
    """Percent off the user's checkout for having come via a referral link (0 = none): only
    while they have never paid and the program is on."""
    if user.referred_by_id is None or not await settings_service.get_value(db, "referrals.enabled"):
        return 0
    if await _has_paid(db, user.id):
        return 0
    return int(await settings_service.get_value(db, "referrals.percent_off"))


async def on_payment_succeeded(
    db: AsyncSession, payment: Payment, user: User, paid_plan: Plan
) -> Granted | None:
    """On the invited user's first successful payment, credit the referrer with free days (and a
    rank gift when a new level is reached). Caller commits, then notifies `Granted.referrer`."""
    if user.referred_by_id is None or not await settings_service.get_value(db, "referrals.enabled"):
        return None
    if await _has_paid(db, user.id, except_id=payment.id):
        return None
    # Row lock: concurrent payments by two friends count towards a rank one after the other.
    referrer = await db.get(User, user.referred_by_id, with_for_update=True)
    if referrer is None:
        return None
    days = int(await settings_service.get_value(db, "referrals.bonus_days"))
    if not referrer.is_active:
        days = 0  # suspended/deleted accounts get nothing new
    result = await db.execute(
        pg_insert(ReferralReward)
        .values(
            id=uuid7(),
            referrer_id=referrer.id,
            referred_id=user.id,
            source_payment_id=payment.id,
            bonus_days=days,
        )
        .on_conflict_do_nothing(index_elements=["referred_id"])
    )
    if not getattr(result, "rowcount", 0):
        return None  # already credited for this invitee
    audit.record(
        db,
        action="referral.reward_granted",
        actor_type=ActorType.SYSTEM,
        target_type="user",
        target_id=referrer.id,
        details={"referred": str(user.id), "bonus_days": days},
    )
    sub: Subscription | None = None
    if days:
        sub = await _grant_bonus_days(db, referrer.id, paid_plan, days, f"referral:{user.id}")
    paid = await _paid_friends(db, referrer.id)
    reached: list[Level] = []
    if referrer.is_active and await settings_service.get_value(db, "referrals.milestones"):
        for level in LEVELS:
            if paid < level.need:
                break
            ins = await db.execute(
                pg_insert(ReferralMilestone)
                .values(id=uuid7(), user_id=referrer.id, level=level.code, bonus_days=level.days)
                .on_conflict_do_nothing(index_elements=["user_id", "level"])
            )
            if not getattr(ins, "rowcount", 0):
                continue  # this rank's gift was already given
            sub = await _grant_bonus_days(
                db, referrer.id, paid_plan, level.days, f"referral_rank:{level.code}"
            )
            reached.append(level)
            audit.record(
                db,
                action="referral.rank_reached",
                actor_type=ActorType.SYSTEM,
                target_type="user",
                target_id=referrer.id,
                details={"rank": level.code, "paid_friends": paid, "bonus_days": level.days},
            )
    if sub is None:
        return None
    return Granted(
        referrer=referrer,
        bonus_days=days,
        subscription=sub,
        paid_friends=paid,
        milestones=tuple(reached),
    )


async def _paid_friends(db: AsyncSession, user_id: uuid.UUID) -> int:
    n = await db.scalar(
        select(func.count())
        .select_from(ReferralReward)
        .where(ReferralReward.referrer_id == user_id)
    )
    return int(n or 0)


async def _grant_bonus_days(
    db: AsyncSession, referrer_id: uuid.UUID, paid_plan: Plan, days: int, reason: str
) -> Subscription:
    """Extend the referrer's live subscription on its current plan. A trial (or no subscription)
    is upgraded to the plan the invitee bought, so the bonus is real paid-plan access."""
    live = await subs.get_live(db, referrer_id)
    plan = paid_plan
    if live is not None:
        current = await db.get(Plan, live.plan_id)
        if current is not None and not current.is_trial:
            plan = current
    return await subs.grant_days(
        db,
        user_id=referrer_id,
        plan=plan,
        days=days,
        provider=Provider.PROMO,
        actor_id=None,
        actor_type=ActorType.SYSTEM,
        ip=None,
        reason=reason,
    )


async def summary(db: AsyncSession, settings: Settings, user: User) -> dict[str, Any]:
    code = await ensure_code(db, user.id)
    invited = await db.scalar(
        select(func.count()).select_from(User).where(User.referred_by_id == user.id)
    )
    paid = await _paid_friends(db, user.id)
    ranks_on = bool(await settings_service.get_value(db, "referrals.milestones"))
    got = set(
        (
            await db.scalars(
                select(ReferralMilestone.level).where(ReferralMilestone.user_id == user.id)
            )
        ).all()
    )
    levels = [
        {
            "code": lv.code,
            "need": lv.need,
            "days": lv.days,
            "theme": lv.theme,
            "reached": lv.code in got or (ranks_on and paid >= lv.need),
        }
        for lv in LEVELS
    ]
    nxt = next((lv for lv in levels if not lv["reached"]), None)
    return {
        "enabled": bool(await settings_service.get_value(db, "referrals.enabled")),
        "code": code,
        "link": link_for(settings, code),
        "percent_off": int(await settings_service.get_value(db, "referrals.percent_off")),
        "bonus_days": int(await settings_service.get_value(db, "referrals.bonus_days")),
        "invited": int(invited or 0),
        "paid": paid,
        "my_discount": await invitee_discount(db, user),
        "ranks_enabled": ranks_on,
        "rank": next((lv["code"] for lv in reversed(levels) if lv["reached"]), BASE_RANK),
        "levels": levels,
        "next_level": nxt if ranks_on else None,
        "themes": [lv["theme"] for lv in levels if lv["reached"]],
    }
