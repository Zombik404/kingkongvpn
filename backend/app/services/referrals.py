"""Referral program.

Each user gets a personal link (`t.me/<bot>?start=ref_<code>`).

- The **invited user** gets `referrals.percent_off` (default 30 %) off their **first** payment,
  applied automatically at checkout (not combined with a promo code — the promo price wins).
- The **referrer** gets `referrals.bonus_days` (default 14) free days for every invited user whose
  first payment succeeds — the live subscription is extended, or a new one started if they have
  none. No discount for the referrer.

One credit per invited user (unique `referral_rewards.referred_id`).
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
from app.models import Payment, Plan, ReferralReward, Subscription, User
from app.models.enums import ActorType, PaymentStatus, Provider
from app.services import audit
from app.services import settings as settings_service
from app.subscriptions import service as subs

if TYPE_CHECKING:
    from app.core.config import Settings

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True)
class Granted:
    """What the referrer earned (for the notification after commit)."""

    referrer: User
    bonus_days: int
    subscription: Subscription


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
    """On the invited user's first successful payment, credit the referrer with free days.
    Caller commits, then notifies `Granted.referrer`."""
    if user.referred_by_id is None or not await settings_service.get_value(db, "referrals.enabled"):
        return None
    if await _has_paid(db, user.id, except_id=payment.id):
        return None
    referrer = await db.get(User, user.referred_by_id)
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
    if not days:
        return None
    sub = await _grant_bonus_days(db, referrer.id, paid_plan, days, invitee=user.id)
    return Granted(referrer=referrer, bonus_days=days, subscription=sub)


async def _grant_bonus_days(
    db: AsyncSession, referrer_id: uuid.UUID, paid_plan: Plan, days: int, *, invitee: uuid.UUID
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
        reason=f"referral:{invitee}",
    )


async def summary(db: AsyncSession, settings: Settings, user: User) -> dict[str, Any]:
    code = await ensure_code(db, user.id)
    invited = await db.scalar(
        select(func.count()).select_from(User).where(User.referred_by_id == user.id)
    )
    paid = await db.scalar(
        select(func.count())
        .select_from(ReferralReward)
        .where(ReferralReward.referrer_id == user.id)
    )
    return {
        "enabled": bool(await settings_service.get_value(db, "referrals.enabled")),
        "code": code,
        "link": link_for(settings, code),
        "percent_off": int(await settings_service.get_value(db, "referrals.percent_off")),
        "bonus_days": int(await settings_service.get_value(db, "referrals.bonus_days")),
        "invited": int(invited or 0),
        "paid": int(paid or 0),
        "my_discount": await invitee_discount(db, user),
    }
