"""Checkout + provider webhooks."""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import Client, Ctx, CurrentPrincipal, Db
from app.core.errors import AppError, NotFound
from app.models import Payment, Plan, PlanPrice
from app.models.base import utcnow
from app.models.enums import PaymentStatus
from app.payments import cryptobot
from app.payments import service as payments
from app.security.rate_limit import Limit

log = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])
webhooks = APIRouter(prefix="/webhooks", tags=["webhooks"])

CHECKOUT_PER_ACCOUNT = Limit("checkout-acct", 10, 60 * 60)
REFRESH_PER_ACCOUNT = Limit("pay-refresh-acct", 30, 60 * 60)


class CheckoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price_id: uuid.UUID
    promo_code: str | None = Field(
        default=None, min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_-]+$"
    )


class PaymentOut(BaseModel):
    id: uuid.UUID
    provider: str
    status: str
    amount_minor: int
    currency: str
    plan_code: str | None
    period_unit: str | None
    period_count: int | None
    checkout_url: str | None
    expires_at: dt.datetime | None
    paid_at: dt.datetime | None
    failure_reason: str | None
    created_at: dt.datetime


async def _out(db: Db, p: Payment) -> PaymentOut:
    row = None
    if p.plan_price_id:
        row = (
            await db.execute(
                select(PlanPrice, Plan)
                .join(Plan, Plan.id == PlanPrice.plan_id)
                .where(PlanPrice.id == p.plan_price_id)
            )
        ).one_or_none()
    price, plan = (row[0], row[1]) if row else (None, None)
    return PaymentOut(
        id=p.id,
        provider=p.provider,
        status=p.status,
        amount_minor=p.amount_minor,
        currency=p.currency,
        plan_code=plan.code if plan else None,
        period_unit=price.period_unit if price else None,
        period_count=price.period_count if price else None,
        checkout_url=p.checkout_url if p.status == PaymentStatus.PENDING else None,
        expires_at=p.expires_at,
        paid_at=p.paid_at,
        failure_reason=p.failure_reason,
        created_at=p.created_at,
    )


@router.post("/checkout", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
async def checkout(
    body: CheckoutIn, principal: CurrentPrincipal, ctx: Ctx, db: Db, client: Client
) -> PaymentOut:
    """Create a crypto invoice (priced in fiat, paid in the accepted assets) and return the
    @CryptoBot payment link. Access is granted when the provider confirms payment."""
    await ctx.limiter.hit(CHECKOUT_PER_ACCOUNT, str(principal.user.id))
    payment = await payments.checkout(
        ctx,
        db,
        user_id=principal.user.id,
        price_id=body.price_id,
        promo_code=body.promo_code,
        ip=client.ip,
    )
    return await _out(db, payment)


@router.get("", response_model=list[PaymentOut])
async def list_payments(
    principal: CurrentPrincipal, db: Db, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[PaymentOut]:
    rows = (
        await db.scalars(
            select(Payment)
            .where(Payment.user_id == principal.user.id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [await _out(db, p) for p in rows]


@router.get("/{payment_id}", response_model=PaymentOut)
async def get_payment(
    payment_id: uuid.UUID, principal: CurrentPrincipal, ctx: Ctx, db: Db, refresh: bool = False
) -> PaymentOut:
    """`refresh=true` re-checks a pending invoice with the provider (the "I've paid" button)."""
    stmt = select(Payment).where(Payment.id == payment_id, Payment.user_id == principal.user.id)
    payment = await db.scalar(stmt)
    if payment is None:
        raise NotFound("Payment not found.")
    if refresh and payment.status == PaymentStatus.PENDING and ctx.cryptobot is not None:
        await ctx.limiter.hit(REFRESH_PER_ACCOUNT, str(principal.user.id))
        invoice_id = int(payment.provider_payment_id)
        await db.rollback()
        for invoice in await ctx.cryptobot.get_invoices([invoice_id]):
            if invoice.status != "active":
                await payments.apply_invoice(ctx, db, invoice, source="user_refresh")
        payment = await db.scalar(stmt.execution_options(populate_existing=True))
        assert payment is not None
    return await _out(db, payment)


class InvalidWebhook(AppError):
    status_code = 401
    code = "invalid_signature"
    message = "Invalid signature."


@webhooks.post("/cryptobot", include_in_schema=False)
async def cryptobot_webhook(request: Request, ctx: Ctx, db: Db) -> dict[str, Any]:
    if ctx.cryptobot is None:
        raise NotFound()
    raw = await request.body()
    token = ctx.settings.cryptobot_api_token.get_secret_value()
    if not cryptobot.verify_signature(token, raw, request.headers.get(cryptobot.SIGNATURE_HEADER)):
        log.warning("cryptobot webhook with bad signature")
        raise InvalidWebhook()
    try:
        update_type, invoice = cryptobot.parse_webhook(raw, now=utcnow())
    except (ValueError, KeyError, TypeError) as exc:
        raise AppError("Malformed update.", code="malformed_update") from exc
    await payments.record_event(
        db,
        event_id=f"invoice:{invoice.invoice_id}:{invoice.status}",
        event_type=update_type,
        payload={
            "invoice_id": invoice.invoice_id,
            "status": invoice.status,
            "amount": str(invoice.amount),
            "fiat": invoice.fiat,
            "paid_asset": invoice.paid_asset,
            "paid_amount": invoice.paid_amount,
        },
    )
    outcome = "ignored"
    if update_type == "invoice_paid":
        outcome = await payments.apply_invoice(ctx, db, invoice, source="webhook")
    await db.commit()
    # 200 for every authenticated update, so the provider doesn't retry things we've
    # deliberately rejected (they're audit-logged).
    return {"ok": True, "outcome": outcome}
