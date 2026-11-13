"""Staff API pieces used by the admin panel (Phase 9): who am I, the overview, payments.

Same rules as the rest of the admin API: a staff permission on an MFA-verified session."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, cast, func, select

from app.api.deps import Ctx, Db, require
from app.models import (
    Device,
    GameRound,
    GameRoundPlayer,
    Payment,
    Plan,
    PlanPrice,
    ReferralReward,
    Server,
    Subscription,
    User,
)
from app.models.base import utcnow
from app.models.enums import DeviceStatus, PaymentStatus, ServerStatus, UserStatus
from app.security.principal import Principal
from app.security.rbac import Perm, permissions_for

router = APIRouter(prefix="/admin", tags=["admin"])

Staff = Annotated[Principal, Depends(require(Perm.USERS_READ))]  # every staff role has it
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100_000)]


@router.get("/me")
async def admin_me(principal: Staff) -> dict[str, Any]:
    """The signed-in staff member and what they may do (the panel hides the rest)."""
    return {
        "id": str(principal.user.id),
        "email": principal.user.email,
        "roles": list(principal.user.roles),
        "permissions": sorted(p.value for p in permissions_for(principal.user.roles)),
    }


def _days(n: int) -> list[str]:
    today = utcnow().date()
    return [(today - dt.timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


@router.get("/overview")
async def overview(db: Db, ctx: Ctx, principal: Staff) -> dict[str, Any]:
    """Headline numbers for the dashboard. Money only for those who may see payments."""
    now = utcnow()
    week, month, day = (
        now - dt.timedelta(days=7),
        now - dt.timedelta(days=30),
        now - dt.timedelta(days=1),
    )
    active_user = User.status == UserStatus.ACTIVE
    users_total = await db.scalar(select(func.count()).select_from(User).where(active_user))
    users_week = await db.scalar(
        select(func.count()).select_from(User).where(active_user, User.created_at >= week)
    )
    users_tg = await db.scalar(
        select(func.count()).select_from(User).where(active_user, User.telegram_id.is_not(None))
    )
    subs = {
        status: int(n)
        for status, n in (
            await db.execute(
                select(Subscription.status, func.count())
                .where(Subscription.status.in_(["active", "trialing", "past_due", "grace"]))
                .group_by(Subscription.status)
            )
        ).all()
    }
    devices = await db.scalar(
        select(func.count()).select_from(Device).where(Device.status == DeviceStatus.ACTIVE)
    )
    cutoff = now - dt.timedelta(seconds=ctx.settings.node_heartbeat_stale_seconds)
    servers_total = await db.scalar(select(func.count()).select_from(Server))
    servers_up = await db.scalar(
        select(func.count())
        .select_from(Server)
        .where(
            Server.status == ServerStatus.ACTIVE,
            Server.last_heartbeat_at >= cutoff,
            Server.wg_public_key.is_not(None),
        )
    )
    rounds_day = await db.scalar(
        select(func.count()).select_from(GameRound).where(GameRound.finished_at >= day)
    )
    players_day = await db.scalar(
        select(func.count(func.distinct(GameRoundPlayer.user_id)))
        .join(GameRound, GameRound.id == GameRoundPlayer.round_id)
        .where(GameRound.finished_at >= day)
    )
    referrals_month = await db.scalar(
        select(func.count()).select_from(ReferralReward).where(ReferralReward.created_at >= month)
    )
    signup_day = cast(User.created_at, Date)
    signups = dict(
        (
            await db.execute(
                select(signup_day, func.count())
                .where(User.created_at >= now - dt.timedelta(days=30))
                .group_by(signup_day)
            )
        ).all()
    )
    out: dict[str, Any] = {
        "generated_at": now,
        "users": {
            "total": int(users_total or 0),
            "new_7d": int(users_week or 0),
            "telegram": int(users_tg or 0),
        },
        "subscriptions": {
            "active": subs.get("active", 0),
            "trialing": subs.get("trialing", 0),
            "grace": subs.get("grace", 0) + subs.get("past_due", 0),
        },
        "devices_active": int(devices or 0),
        "servers": {"total": int(servers_total or 0), "accepting": int(servers_up or 0)},
        "games": {"rounds_24h": int(rounds_day or 0), "players_24h": int(players_day or 0)},
        "referral_rewards_30d": int(referrals_month or 0),
        "signups_30d": [
            {"day": d, "count": int(signups.get(dt.date.fromisoformat(d), 0))} for d in _days(30)
        ],
        "revenue_30d": None,
    }
    if Perm.PAYMENTS_READ in permissions_for(principal.user.roles):
        paid_day = cast(Payment.paid_at, Date)
        rows = (
            await db.execute(
                select(Payment.currency, paid_day, func.count(), func.sum(Payment.amount_minor))
                .where(Payment.status == PaymentStatus.SUCCEEDED, Payment.paid_at >= month)
                .group_by(Payment.currency, paid_day)
            )
        ).all()
        totals: dict[str, dict[str, int]] = {}
        daily: dict[str, int] = {}
        for cur, d, n, amount in rows:
            t = totals.setdefault(cur, {"count": 0, "amount_minor": 0})
            t["count"] += int(n)
            t["amount_minor"] += int(amount or 0)
            if cur == "USD":
                daily[d.isoformat()] = daily.get(d.isoformat(), 0) + int(amount or 0)
        out["revenue_30d"] = {
            "by_currency": totals,
            "usd_daily": [{"day": d, "amount_minor": daily.get(d, 0)} for d in _days(30)],
        }
    return out


@router.get("/payments")
async def list_payments(
    db: Db,
    _: Annotated[Principal, Depends(require(Perm.PAYMENTS_READ))],
    status: Annotated[PaymentStatus | None, Query()] = None,
    user_id: uuid.UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict[str, Any]]:
    """Payments, newest first. No card or wallet details exist here: @CryptoBot keeps those."""
    stmt = (
        select(Payment, Plan.code, PlanPrice.period_unit, PlanPrice.period_count)
        .outerjoin(PlanPrice, PlanPrice.id == Payment.plan_price_id)
        .outerjoin(Plan, Plan.id == PlanPrice.plan_id)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if status is not None:
        stmt = stmt.where(Payment.status == status)
    if user_id is not None:
        stmt = stmt.where(Payment.user_id == user_id)
    return [
        {
            "id": str(p.id),
            "user_id": str(p.user_id) if p.user_id else None,
            "provider": p.provider,
            "status": p.status,
            "kind": p.kind,
            "amount_minor": p.amount_minor,
            "currency": p.currency,
            "paid_asset": p.paid_asset,
            "paid_amount": p.paid_amount,
            "plan_code": code,
            "period": f"{count} {unit}" if unit else None,
            "discount": "promo"
            if p.promo_code_id
            else ("referral" if p.referral_percent_off else None),
            "failure_reason": p.failure_reason,
            "created_at": p.created_at,
            "paid_at": p.paid_at,
        }
        for p, code, unit, count in (await db.execute(stmt)).all()
    ]
