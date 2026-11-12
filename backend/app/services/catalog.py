"""Plans, prices and promo codes."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict, NotFound
from app.models import Plan, PlanPrice, PromoCode, PromoRedemption, Subscription
from app.models.base import utcnow
from app.models.enums import ActorType, PromoKind, Provider
from app.schemas.domain import PlanOut, PriceOut
from app.security import rate_limit as rl
from app.security.rate_limit import RateLimiter
from app.subscriptions import service as subs


class InvalidPromo(AppError):
    status_code = 422
    code = "invalid_promo_code"
    message = "This code is not valid."


def _price_live() -> ColumnElement[bool]:
    now = utcnow()
    clause: ColumnElement[bool] = (
        PlanPrice.active.is_(True)
        & or_(PlanPrice.valid_from.is_(None), PlanPrice.valid_from <= now)
        & or_(PlanPrice.valid_until.is_(None), PlanPrice.valid_until > now)
    )
    return clause


async def public_plans(db: AsyncSession, locale: str) -> list[PlanOut]:
    plans = (
        await db.scalars(
            select(Plan)
            .where(Plan.active.is_(True), Plan.is_trial.is_(False))
            .order_by(Plan.sort_order, Plan.code)
        )
    ).all()
    prices = (
        await db.scalars(
            select(PlanPrice)
            .where(_price_live(), PlanPrice.plan_id.in_([p.id for p in plans]))
            .order_by(PlanPrice.period_unit, PlanPrice.period_count, PlanPrice.currency)
        )
    ).all()
    by_plan: dict[uuid.UUID, list[PriceOut]] = {}
    for price in prices:
        by_plan.setdefault(price.plan_id, []).append(PriceOut.model_validate(price))
    return [
        PlanOut(
            id=p.id,
            code=p.code,
            name=subs.plan_name(p, locale),
            features=p.features,
            device_limit=p.device_limit,
            server_tiers=list(p.server_tiers),
            prices=by_plan.get(p.id, []),
        )
        for p in plans
        if by_plan.get(p.id)
    ]


async def plan_by_code(db: AsyncSession, code: str) -> Plan:
    plan = await db.scalar(select(Plan).where(Plan.code == code))
    if plan is None:
        raise NotFound(f"Plan {code!r} not found.")
    return plan


async def create_plan(db: AsyncSession, data: dict[str, Any]) -> Plan:
    plan = Plan(**data)
    db.add(plan)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("A plan with this code already exists.", code="plan_code_taken") from exc
    return plan


# --- promo -------------------------------------------------------------------------
async def _usable_promo(db: AsyncSession, code: str, *, lock: bool = False) -> PromoCode:
    stmt = select(PromoCode).where(PromoCode.code == code)
    if lock:
        stmt = stmt.with_for_update()
    promo = await db.scalar(stmt)
    now = utcnow()
    if (
        promo is None
        or not promo.active
        or (promo.valid_from is not None and promo.valid_from > now)
        or (promo.valid_until is not None and promo.valid_until <= now)
        or (promo.max_redemptions is not None and promo.redemption_count >= promo.max_redemptions)
    ):
        raise InvalidPromo()
    return promo


async def quote(
    db: AsyncSession, limiter: RateLimiter, user_id: uuid.UUID, code: str, price_id: uuid.UUID
) -> tuple[PromoCode, PlanPrice, int]:
    """Validate a discount code against a price. Redemption happens at checkout (Phase 10)."""
    await limiter.hit(rl.PROMO_PER_ACCOUNT, str(user_id))
    promo = await _usable_promo(db, code)
    price = await db.get(PlanPrice, price_id)
    if price is None or not price.active:
        raise NotFound("Price not found.")
    if promo.kind == PromoKind.FREE_DAYS:
        raise InvalidPromo("This code grants free days — redeem it instead.")
    if promo.plan_id is not None and promo.plan_id != price.plan_id:
        raise InvalidPromo("This code doesn't apply to this plan.")
    if await _already_redeemed(db, promo.id, user_id):
        raise InvalidPromo("You've already used this code.")
    if promo.kind == PromoKind.PERCENT_OFF:
        assert promo.percent_off is not None
        discounted = price.amount_minor - (price.amount_minor * promo.percent_off) // 100
    else:
        assert promo.amount_off_minor is not None
        if promo.currency != price.currency:
            raise InvalidPromo("This code doesn't apply to this currency.")
        discounted = max(0, price.amount_minor - promo.amount_off_minor)
    return promo, price, discounted


async def _already_redeemed(db: AsyncSession, promo_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return (
        await db.scalar(
            select(PromoRedemption.id).where(
                PromoRedemption.promo_code_id == promo_id, PromoRedemption.user_id == user_id
            )
        )
        is not None
    )


async def redeem_free_days(
    db: AsyncSession, limiter: RateLimiter, user_id: uuid.UUID, code: str, ip: str | None
) -> Subscription:
    await limiter.hit(rl.PROMO_PER_ACCOUNT, str(user_id))
    promo = await _usable_promo(db, code, lock=True)  # row lock serialises max_redemptions
    if promo.kind != PromoKind.FREE_DAYS:
        raise InvalidPromo("This is a discount code — use it at checkout.")
    if await _already_redeemed(db, promo.id, user_id):
        raise InvalidPromo("You've already used this code.")
    assert promo.plan_id is not None and promo.free_days is not None
    plan = await db.get(Plan, promo.plan_id)
    if plan is None or not plan.active:
        raise InvalidPromo()
    sub = await subs.grant_days(
        db,
        user_id=user_id,
        plan=plan,
        days=promo.free_days,
        provider=Provider.PROMO,
        actor_id=user_id,
        actor_type=ActorType.USER,
        ip=ip,
        reason=f"promo:{promo.id}",
    )
    db.add(PromoRedemption(promo_code_id=promo.id, user_id=user_id, subscription_id=sub.id))
    await db.execute(
        update(PromoCode)
        .where(PromoCode.id == promo.id)
        .values(redemption_count=PromoCode.redemption_count + 1)
    )
    await db.commit()
    return sub
