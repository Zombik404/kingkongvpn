"""Checkout and payment processing (provider: Crypto Pay / @CryptoBot).

Trust model (ADR-008): access is granted only from a verified provider event — a webhook with
a valid signature or our own authenticated API call to the provider — never from a client
saying "I paid". The period granted comes from *our* price row, and the invoice amount and
currency reported by the provider must match what we asked for.
"""

from __future__ import annotations

import calendar
import datetime as dt
import logging
import uuid
from decimal import Decimal
from typing import Literal

from babel.dates import format_date
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import AppContext
from app.core.errors import AppError, NotFound
from app.core.ids import uuid7
from app.models import Payment, PaymentEvent, Plan, PlanPrice, User
from app.models.base import utcnow
from app.models.enums import (
    ActorType,
    AuditResult,
    PaymentKind,
    PaymentStatus,
    PeriodUnit,
    Provider,
)
from app.notifications.notify import notify
from app.payments.cryptobot import CryptoBotClient, Invoice
from app.services import audit, catalog
from app.subscriptions import service as subs

log = logging.getLogger(__name__)

SUPPORTED_FIAT = frozenset({"USD", "EUR", "RUB"})
MIN_AMOUNT_MINOR = 10  # below this an invoice makes no sense (and providers reject it)
Outcome = Literal["credited", "duplicate", "expired", "ignored", "unknown", "mismatch"]


class PaymentsDisabled(AppError):
    status_code = 503
    code = "payments_disabled"
    message = "Payments are not available right now."


class InviteRequired(AppError):
    status_code = 403
    code = "invite_required"
    message = "This is a closed test — enter your invite code first."


class TooManyPendingPayments(AppError):
    status_code = 429
    code = "too_many_pending_payments"
    message = "You have several unpaid invoices. Pay one or wait until they expire."


def add_period(start: dt.datetime, unit: str, count: int) -> dt.datetime:
    """Calendar-correct period end (Jan 31 + 1 month = Feb 28/29)."""
    if unit == PeriodUnit.DAY:
        return start + dt.timedelta(days=count)
    months = count * (12 if unit == PeriodUnit.YEAR else 1)
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def _price_is_live(price: PlanPrice, now: dt.datetime) -> bool:
    return (
        price.active
        and (price.valid_from is None or price.valid_from <= now)
        and (price.valid_until is None or price.valid_until > now)
    )


def describe(plan: Plan, price: PlanPrice) -> str:
    unit = {"day": "day", "month": "month", "year": "year"}[price.period_unit]
    plural = "" if price.period_count == 1 else "s"
    return f"{subs.plan_name(plan, 'en')} — {price.period_count} {unit}{plural}"


def _client(ctx: AppContext) -> CryptoBotClient:
    if ctx.cryptobot is None:
        raise PaymentsDisabled()
    return ctx.cryptobot


# --- checkout ----------------------------------------------------------------------------
async def checkout(
    ctx: AppContext,
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    price_id: uuid.UUID,
    promo_code: str | None,
    ip: str | None,
) -> Payment:
    client = _client(ctx)
    now = utcnow()
    user = await db.get(User, user_id, with_for_update=True)  # serialises per-user checkouts
    assert user is not None
    price = await db.get(PlanPrice, price_id)
    plan = await db.get(Plan, price.plan_id) if price else None
    if (
        price is None
        or plan is None
        or not plan.active
        or plan.is_trial
        or not _price_is_live(price, now)
    ):
        raise NotFound("Price not found.")
    if price.currency not in SUPPORTED_FIAT:
        raise NotFound("Price not available for this payment method.")
    if not await subs.has_access_to_purchase(db, user_id):
        raise InviteRequired()
    pending = await db.scalar(
        select(func.count())
        .select_from(Payment)
        .where(
            Payment.user_id == user_id,
            Payment.status == PaymentStatus.PENDING,
            or_(Payment.expires_at.is_(None), Payment.expires_at > now),
        )
    )
    if (pending or 0) >= ctx.settings.payment_pending_limit_per_user:
        raise TooManyPendingPayments()

    amount, promo_id = price.amount_minor, None
    if promo_code:
        promo, amount = await catalog.apply_discount(db, user_id, promo_code, price)
        promo_id = promo.id
    if amount < MIN_AMOUNT_MINOR:
        raise catalog.InvalidPromo("This code can't be used for a paid checkout.")

    payment_id = uuid7()
    invoice = await client.create_invoice(
        amount_minor=amount,
        fiat=price.currency,
        payload=str(payment_id),
        description=describe(plan, price),
    )
    live = await subs.get_live(db, user_id)
    payment = Payment(
        id=payment_id,
        user_id=user_id,
        provider=Provider.CRYPTOBOT.value,
        provider_payment_id=str(invoice.invoice_id),
        amount_minor=amount,
        currency=price.currency,
        status=PaymentStatus.PENDING.value,
        kind=(PaymentKind.RENEWAL if live else PaymentKind.INITIAL).value,
        plan_price_id=price.id,
        promo_code_id=promo_id,
        checkout_url=invoice.pay_url,
        expires_at=invoice.expires_at
        or now + dt.timedelta(seconds=ctx.settings.cryptobot_invoice_ttl_seconds),
    )
    db.add(payment)
    audit.record(
        db,
        action="payment.checkout_created",
        actor_id=user_id,
        target_type="payment",
        target_id=payment_id,
        ip=ip,
        details={
            "provider": "cryptobot",
            "plan": plan.code,
            "amount_minor": amount,
            "currency": price.currency,
            "promo": str(promo_id) if promo_id else None,
        },
    )
    await db.commit()
    return payment


# --- processing -----------------------------------------------------------------------------
async def record_event(
    db: AsyncSession, *, event_id: str, event_type: str, payload: dict[str, object]
) -> bool:
    """Store the raw provider event; False if this exact event was already stored."""
    result = await db.execute(
        pg_insert(PaymentEvent)
        .values(
            id=uuid7(),
            provider=Provider.CRYPTOBOT.value,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
        )
        .on_conflict_do_nothing(constraint="uq_payment_events_provider_event")
    )
    return bool(getattr(result, "rowcount", 0))


async def apply_invoice(
    ctx: AppContext, db: AsyncSession, invoice: Invoice, *, source: str
) -> Outcome:
    """Bring our payment in line with the provider's invoice. Idempotent; caller commits
    nothing — this commits itself. Safe to run concurrently (row lock on the payment)."""
    payment = await db.scalar(
        select(Payment)
        .where(
            Payment.provider == Provider.CRYPTOBOT,
            Payment.provider_payment_id == str(invoice.invoice_id),
        )
        .with_for_update()
    )
    if payment is None:
        log.warning("cryptobot invoice %s has no matching payment", invoice.invoice_id)
        return "unknown"
    if invoice.payload != str(payment.id):
        audit.record(
            db,
            action="payment.mismatch",
            actor_type=ActorType.SYSTEM,
            target_type="payment",
            target_id=payment.id,
            result=AuditResult.DENIED,
            details={"reason": "payload", "source": source},
        )
        await db.commit()
        return "mismatch"

    if invoice.status == "paid":
        if payment.status == PaymentStatus.SUCCEEDED:
            return "duplicate"
        expected = Decimal(payment.amount_minor) / 100
        if invoice.amount != expected or (invoice.fiat or "") != payment.currency:
            payment.status = PaymentStatus.FAILED.value
            payment.failure_reason = "amount_mismatch"
            audit.record(
                db,
                action="payment.mismatch",
                actor_type=ActorType.SYSTEM,
                target_type="payment",
                target_id=payment.id,
                result=AuditResult.DENIED,
                details={
                    "reason": "amount",
                    "expected": str(expected),
                    "got": str(invoice.amount),
                    "fiat": invoice.fiat,
                },
            )
            await db.commit()
            return "mismatch"
        return await _credit(ctx, db, payment, invoice, source)

    if invoice.status == "expired" and payment.status == PaymentStatus.PENDING:
        payment.status = PaymentStatus.FAILED.value
        payment.failure_reason = "expired"
        await db.commit()
        return "expired"
    return "ignored"


async def _credit(
    ctx: AppContext, db: AsyncSession, payment: Payment, invoice: Invoice, source: str
) -> Outcome:
    assert payment.user_id is not None and payment.plan_price_id is not None
    price = await db.get(PlanPrice, payment.plan_price_id)
    plan = await db.get(Plan, price.plan_id) if price else None
    user = await db.get(User, payment.user_id)
    if price is None or plan is None or user is None:
        # Money arrived but we can't map it to a product: flag for support, don't lose it.
        payment.status = PaymentStatus.SUCCEEDED.value
        payment.failure_reason = "needs_manual_review"
        payment.paid_at = invoice.paid_at or utcnow()
        audit.record(
            db,
            action="payment.needs_review",
            actor_type=ActorType.SYSTEM,
            target_type="payment",
            target_id=payment.id,
            result=AuditResult.FAILURE,
        )
        await db.commit()
        return "credited"

    now = utcnow()
    live = await subs.get_live(db, user.id)
    base = max(live.current_period_end, now) if live else now
    days = max(1, (add_period(base, price.period_unit, price.period_count) - base).days)
    sub = await subs.grant_days(
        db,
        user_id=user.id,
        plan=plan,
        days=days,
        provider=Provider.CRYPTOBOT,
        actor_id=None,
        actor_type=ActorType.SYSTEM,
        ip=None,
        reason=f"payment:{payment.id}",
    )
    payment.status = PaymentStatus.SUCCEEDED.value
    payment.failure_reason = None
    payment.subscription_id = sub.id
    payment.paid_at = invoice.paid_at or now
    payment.paid_asset = invoice.paid_asset
    payment.paid_amount = invoice.paid_amount
    if payment.promo_code_id is not None:
        await catalog.record_redemption(db, payment.promo_code_id, user.id, sub.id)
    audit.record(
        db,
        action="payment.succeeded",
        actor_type=ActorType.SYSTEM,
        target_type="payment",
        target_id=payment.id,
        details={
            "source": source,
            "user": str(user.id),
            "plan": plan.code,
            "days": days,
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
            "paid_asset": invoice.paid_asset,
        },
    )
    await db.commit()
    await notify(
        ctx,
        user,
        "payment_received",
        {
            "plan": subs.plan_name(plan, user.locale),
            "date": format_date(sub.current_period_end, format="long", locale=user.locale),
        },
        f"{ctx.settings.public_web_url}/account/subscription",
    )
    return "credited"


async def poll_pending(ctx: AppContext, db: AsyncSession, *, batch: int = 100) -> dict[str, int]:
    """Safety net for lost webhooks (and the only path when no webhook URL is configured)."""
    if ctx.cryptobot is None:
        return {}
    since = utcnow() - dt.timedelta(days=2)
    rows = (
        (
            await db.execute(
                select(Payment.provider_payment_id)
                .where(
                    Payment.provider == Provider.CRYPTOBOT,
                    Payment.status == PaymentStatus.PENDING,
                    Payment.created_at >= since,
                )
                .order_by(Payment.created_at)
                .limit(batch)
            )
        )
        .scalars()
        .all()
    )
    await db.rollback()  # don't hold a transaction open across the HTTP call
    counts: dict[str, int] = {}
    if not rows:
        return counts
    invoices = await ctx.cryptobot.get_invoices([int(r) for r in rows])
    for invoice in invoices:
        if invoice.status == "active":
            continue
        await record_event(
            db,
            event_id=f"invoice:{invoice.invoice_id}:{invoice.status}",
            event_type=f"poll:{invoice.status}",
            payload={"invoice_id": invoice.invoice_id, "status": invoice.status},
        )
        outcome = await apply_invoice(ctx, db, invoice, source="poll")
        counts[outcome] = counts.get(outcome, 0) + 1
    await db.commit()
    return counts
