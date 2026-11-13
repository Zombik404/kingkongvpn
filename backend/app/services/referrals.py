"""Referral program.

Each user gets a personal link (`t.me/<bot>?start=ref_<code>`). When someone who signed up via
that link makes their **first** successful payment, the referrer earns a one-time discount
(`referrals.percent_off`, default 30 %) that is applied automatically to their next checkout.
One reward per referred user; rewards don't stack within one payment and don't combine with a
promo code (the customer gets the promo code's price instead).
"""

from __future__ import annotations

import secrets
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict
from app.core.ids import uuid7
from app.models import Payment, ReferralReward, User
from app.models.enums import ActorType, PaymentStatus
from app.services import audit
from app.services import settings as settings_service

if TYPE_CHECKING:
    from app.core.config import Settings

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


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


async def reserve_reward(db: AsyncSession, user_id: uuid.UUID) -> ReferralReward | None:
    """Lock one available reward for a checkout (caller commits with the payment)."""
    reward = await db.scalar(
        select(ReferralReward)
        .where(ReferralReward.referrer_id == user_id, ReferralReward.status == "available")
        .order_by(ReferralReward.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if reward is not None:
        reward.status = "reserved"
    return reward


async def release_reward(db: AsyncSession, payment: Payment) -> None:
    if payment.referral_reward_id is None:
        return
    reward = await db.get(ReferralReward, payment.referral_reward_id, with_for_update=True)
    if reward is not None and reward.status == "reserved":
        reward.status = "available"


async def on_payment_succeeded(db: AsyncSession, payment: Payment, user: User) -> User | None:
    """Consume the reward used by this payment; grant one to the referrer on the referred user's
    first payment. Returns the referrer to notify (caller commits, then notifies)."""
    if payment.referral_reward_id is not None:
        reward = await db.get(ReferralReward, payment.referral_reward_id, with_for_update=True)
        if reward is not None:
            reward.status = "used"
            reward.used_payment_id = payment.id
    if user.referred_by_id is None or not await settings_service.get_value(db, "referrals.enabled"):
        return None
    earlier = await db.scalar(
        select(func.count())
        .select_from(Payment)
        .where(
            Payment.user_id == user.id,
            Payment.status == PaymentStatus.SUCCEEDED,
            Payment.id != payment.id,
        )
    )
    if earlier:
        return None
    percent = int(await settings_service.get_value(db, "referrals.percent_off"))
    result = await db.execute(
        pg_insert(ReferralReward)
        .values(
            id=uuid7(),
            referrer_id=user.referred_by_id,
            referred_id=user.id,
            source_payment_id=payment.id,
            percent_off=percent,
            status="available",
        )
        .on_conflict_do_nothing(index_elements=["referred_id"])
    )
    if not getattr(result, "rowcount", 0):
        return None
    audit.record(
        db,
        action="referral.reward_granted",
        actor_type=ActorType.SYSTEM,
        target_type="user",
        target_id=user.referred_by_id,
        details={"referred": str(user.id), "percent": percent},
    )
    return await db.get(User, user.referred_by_id)


async def summary(db: AsyncSession, settings: Settings, user_id: uuid.UUID) -> dict[str, Any]:
    code = await ensure_code(db, user_id)
    invited = await db.scalar(
        select(func.count()).select_from(User).where(User.referred_by_id == user_id)
    )
    rewards = (
        await db.execute(
            select(ReferralReward.status, func.count())
            .where(ReferralReward.referrer_id == user_id)
            .group_by(ReferralReward.status)
        )
    ).all()
    by_status = {s: int(n) for s, n in rewards}
    return {
        "enabled": bool(await settings_service.get_value(db, "referrals.enabled")),
        "code": code,
        "link": link_for(settings, code),
        "percent_off": int(await settings_service.get_value(db, "referrals.percent_off")),
        "invited": int(invited or 0),
        "paid": sum(by_status.values()),
        "rewards_available": by_status.get("available", 0),
        "rewards_used": by_status.get("used", 0),
    }
