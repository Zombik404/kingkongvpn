"""Subscription persistence + jobs. All status changes go through `state_machine`."""

from __future__ import annotations

import datetime as dt
import math
import uuid
from dataclasses import dataclass

from babel.dates import format_date
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import AppContext
from app.core.errors import AppError, Conflict, NotFound
from app.models import Device, PeerAssignment, Plan, Server, Subscription, User
from app.models.base import utcnow
from app.models.enums import (
    ActorType,
    AssignmentState,
    Provider,
    SubscriptionStatus,
)
from app.notifications.notify import notify
from app.services import audit
from app.services import settings as settings_service
from app.subscriptions import state_machine as sm

LIVE = [s.value for s in sm.ENTITLED]


class TrialUnavailable(AppError):
    status_code = 409
    code = "trial_unavailable"
    message = "A free trial isn't available for this account."


@dataclass(frozen=True)
class Entitlement:
    subscription: Subscription
    plan: Plan


def to_state(sub: Subscription) -> sm.SubState:
    return sm.SubState(
        status=SubscriptionStatus(sub.status),
        period_start=sub.current_period_start,
        period_end=sub.current_period_end,
        cancel_at_period_end=sub.cancel_at_period_end,
        grace_until=sub.grace_until,
        canceled_at=sub.canceled_at,
        ended_at=sub.ended_at,
    )


def write_state(sub: Subscription, state: sm.SubState) -> None:
    sub.status = state.status.value
    sub.current_period_start = state.period_start
    sub.current_period_end = state.period_end
    sub.cancel_at_period_end = state.cancel_at_period_end
    sub.grace_until = state.grace_until
    sub.canceled_at = state.canceled_at
    sub.ended_at = state.ended_at


def plan_name(plan: Plan, locale: str) -> str:
    return plan.names.get(locale) or plan.names.get("en") or plan.code


async def get_live(
    db: AsyncSession, user_id: uuid.UUID, *, lock: bool = False
) -> Subscription | None:
    stmt = select(Subscription).where(
        Subscription.user_id == user_id, Subscription.status.in_(LIVE)
    )
    if lock:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def entitlement(db: AsyncSession, user_id: uuid.UUID) -> Entitlement | None:
    row = (
        await db.execute(
            select(Subscription, Plan)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(Subscription.user_id == user_id, Subscription.status.in_(LIVE))
        )
    ).one_or_none()
    return Entitlement(row[0], row[1]) if row else None


async def revoke_peer_access(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Mark the user's peer assignments for removal and bump affected nodes' revisions.

    Node agents pick the change up on their next poll (Phase 3/4 wires the Redis wake-up)."""
    result = await db.execute(
        update(PeerAssignment)
        .where(
            PeerAssignment.device_id.in_(select(Device.id).where(Device.user_id == user_id)),
            PeerAssignment.state != AssignmentState.REMOVING,
        )
        .values(state=AssignmentState.REMOVING.value)
        .returning(PeerAssignment.server_id)
    )
    servers = {r[0] for r in result.all()}
    if servers:
        await db.execute(
            update(Server).where(Server.id.in_(servers)).values(revision=Server.revision + 1)
        )
    return len(servers)


async def has_access_to_purchase(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Closed-test gate (`access.invite_only`): only invited accounts may trial or pay."""
    if not await settings_service.get_value(db, "access.invite_only"):
        return True
    from app.models import PromoRedemption

    return (
        await db.scalar(select(PromoRedemption.id).where(PromoRedemption.user_id == user_id))
        is not None
    )


# --- user-facing operations ------------------------------------------------------
async def start_trial(
    ctx: AppContext, db: AsyncSession, user_id: uuid.UUID, ip: str | None
) -> Subscription:
    user = await db.get(User, user_id, with_for_update=True)
    assert user is not None
    if not await settings_service.get_value(db, "trial.enabled") or user.trial_used_at is not None:
        raise TrialUnavailable()
    if user.email_verified_at is None and user.telegram_id is None:
        raise TrialUnavailable("Confirm your email to start a trial.")
    if not await has_access_to_purchase(db, user.id):
        raise TrialUnavailable("This is a closed test — enter your invite code first.")
    if await get_live(db, user.id) is not None:
        raise TrialUnavailable("You already have access.")
    code = await settings_service.get_value(db, "trial.plan_code")
    plan = await db.scalar(select(Plan).where(Plan.code == code, Plan.active.is_(True)))
    if plan is None:
        raise TrialUnavailable()
    days = int(await settings_service.get_value(db, "trial.days"))
    now = utcnow()
    state = sm.start(sm.Event.START_TRIAL, now=now, period_end=now + dt.timedelta(days=days))
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        provider=Provider.TRIAL.value,
        auto_renew=False,
        status=state.status.value,
        current_period_start=now,
        current_period_end=state.period_end,
    )
    write_state(sub, state)
    db.add(sub)
    user.trial_used_at = now
    await db.flush()
    audit.record(
        db,
        action="subscription.trial_started",
        actor_id=user.id,
        target_type="subscription",
        target_id=sub.id,
        ip=ip,
        details={"plan": plan.code, "days": days},
    )
    await db.commit()
    return sub


async def set_cancel(
    db: AsyncSession, user_id: uuid.UUID, cancel: bool, ip: str | None
) -> Subscription:
    sub = await get_live(db, user_id, lock=True)
    if sub is None:
        raise NotFound("No active subscription.")
    event = sm.Event.CANCEL if cancel else sm.Event.RESUME
    try:
        write_state(sub, sm.apply(to_state(sub), event, now=utcnow()))
    except sm.InvalidTransition as exc:
        raise Conflict(str(exc), code="invalid_subscription_state") from exc
    audit.record(
        db,
        action=f"subscription.{event.value}",
        actor_id=user_id,
        target_type="subscription",
        target_id=sub.id,
        ip=ip,
    )
    await db.commit()
    return sub


async def grant_days(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    plan: Plan,
    days: int,
    provider: Provider,
    actor_id: uuid.UUID | None,
    actor_type: ActorType,
    ip: str | None,
    reason: str | None = None,
) -> Subscription:
    """Extend the live subscription by `days` (switching plan if different) or start a new one.

    Caller commits."""
    if days <= 0:
        raise ValueError("days must be positive")
    now = utcnow()
    sub = await get_live(db, user_id, lock=True)
    if sub is not None:
        write_state(sub, sm.apply(to_state(sub), sm.Event.EXTEND, now=now, days=days))
        if sub.plan_id != plan.id:
            sub.plan_id = plan.id
        if sub.provider == Provider.TRIAL:
            sub.provider = provider.value
    else:
        state = sm.start(sm.Event.ACTIVATE, now=now, period_end=now + dt.timedelta(days=days))
        sub = Subscription(
            user_id=user_id,
            plan_id=plan.id,
            provider=provider.value,
            auto_renew=False,
            status=state.status.value,
            current_period_start=now,
            current_period_end=state.period_end,
        )
        write_state(sub, state)
        db.add(sub)
        await db.flush()
    audit.record(
        db,
        action="subscription.granted",
        actor_id=actor_id,
        actor_type=actor_type,
        target_type="subscription",
        target_id=sub.id,
        ip=ip,
        details={
            "user": str(user_id),
            "plan": plan.code,
            "days": days,
            "provider": provider.value,
            "reason": reason,
        },
    )
    return sub


async def revoke(
    db: AsyncSession,
    sub: Subscription,
    *,
    actor_id: uuid.UUID | None,
    actor_type: ActorType,
    ip: str | None,
    reason: str,
) -> None:
    """End access now (admin action or account deletion). Caller commits."""
    write_state(sub, sm.apply(to_state(sub), sm.Event.REVOKE, now=utcnow()))
    await revoke_peer_access(db, sub.user_id)
    audit.record(
        db,
        action="subscription.revoked",
        actor_id=actor_id,
        actor_type=actor_type,
        target_type="subscription",
        target_id=sub.id,
        ip=ip,
        details={"reason": reason},
    )


# --- periodic jobs ---------------------------------------------------------------
async def process_due(
    ctx: AppContext, db: AsyncSession, *, now: dt.datetime | None = None, batch: int = 500
) -> int:
    """Advance subscriptions whose period or grace has ended. Idempotent; safe to run in
    parallel (SKIP LOCKED). Returns the number of subscriptions changed."""
    now = now or utcnow()
    grace_days = int(await settings_service.get_value(db, "subscription.grace_days"))
    rows = (
        await db.execute(
            select(Subscription, User, Plan)
            .join(User, User.id == Subscription.user_id)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(
                or_(
                    Subscription.status.in_(
                        [
                            SubscriptionStatus.TRIALING,
                            SubscriptionStatus.ACTIVE,
                            SubscriptionStatus.PAST_DUE,
                        ]
                    )
                    & (Subscription.current_period_end <= now),
                    (Subscription.status == SubscriptionStatus.GRACE)
                    & (Subscription.grace_until <= now),
                )
            )
            .order_by(Subscription.current_period_end)
            .limit(batch)
            .with_for_update(of=Subscription, skip_locked=True)
        )
    ).all()
    notices: list[tuple[User, str, dict[str, str], str]] = []
    for sub, user, plan in rows:
        before = to_state(sub)
        event = (
            sm.Event.GRACE_END if before.status is SubscriptionStatus.GRACE else sm.Event.PERIOD_END
        )
        after = sm.apply(before, event, now=now, grace_days=grace_days)
        write_state(sub, after)
        audit.record(
            db,
            action="subscription.status_changed",
            actor_type=ActorType.SYSTEM,
            target_type="subscription",
            target_id=sub.id,
            details={"from": before.status.value, "to": after.status.value},
        )
        if not after.entitled:
            await revoke_peer_access(db, sub.user_id)
            notices.append(
                (
                    user,
                    "subscription_expired",
                    {"plan": plan_name(plan, user.locale)},
                    f"{ctx.settings.public_web_url}/pricing",
                )
            )
    await db.commit()
    for user, template, params, url in notices:
        await notify(ctx, user, template, params, url)
    return len(rows)


async def send_reminders(
    ctx: AppContext, db: AsyncSession, *, now: dt.datetime | None = None, batch: int = 500
) -> int:
    """Email users whose non-renewing access ends soon, once per configured threshold."""
    now = now or utcnow()
    thresholds = sorted(set(await settings_service.get_value(db, "reminders.days_before")))
    if not thresholds:
        return 0
    horizon = now + dt.timedelta(days=max(thresholds))
    rows = (
        await db.execute(
            select(Subscription, User, Plan)
            .join(User, User.id == Subscription.user_id)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(
                Subscription.status.in_([SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE]),
                Subscription.current_period_end > now,
                Subscription.current_period_end <= horizon,
                or_(
                    Subscription.auto_renew.is_(False), Subscription.cancel_at_period_end.is_(True)
                ),
            )
            .limit(batch)
            .with_for_update(of=Subscription, skip_locked=True)
        )
    ).all()
    jobs: list[tuple[User, dict[str, str]]] = []
    for sub, user, plan in rows:
        remaining = math.ceil((sub.current_period_end - now) / dt.timedelta(days=1))
        target = min(d for d in thresholds if remaining <= d)
        already = (
            sub.reminder_sent_for == sub.current_period_end
            and sub.reminder_threshold_days is not None
            and sub.reminder_threshold_days <= target
        )
        if already:
            continue
        sub.reminder_sent_for = sub.current_period_end
        sub.reminder_threshold_days = target
        if user.is_active and (user.email or user.telegram_id):
            jobs.append(
                (
                    user,
                    {
                        "plan": plan_name(plan, user.locale),
                        "date": format_date(
                            sub.current_period_end, format="long", locale=user.locale
                        ),
                    },
                )
            )
    await db.commit()
    for user, params in jobs:
        await notify(
            ctx,
            user,
            "subscription_ending",
            params,
            f"{ctx.settings.public_web_url}/account/subscription",
        )
    return len(jobs)
