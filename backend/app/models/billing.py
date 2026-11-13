from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk
from app.models.enums import (
    PaymentKind,
    PaymentStatus,
    PeriodUnit,
    PromoKind,
    Provider,
    SubscriptionStatus,
    check_in,
)

# Statuses in which a user still has VPN access. Mirrors subscriptions.state_machine.ENTITLED.
LIVE_STATUSES_SQL = "status IN ('trialing', 'active', 'past_due', 'grace')"


class Plan(UUIDPk, Timestamps, Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("device_limit BETWEEN 1 AND 100", name="device_limit"),
        CheckConstraint("code ~ '^[a-z0-9][a-z0-9_-]{1,31}$'", name="code"),
    )

    code: Mapped[str] = mapped_column(String(32), unique=True)
    names: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, server_default="{}")
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    server_tiers: Mapped[list[str]] = mapped_column(
        ARRAY(String(16)), default=lambda: ["standard"], server_default=text("'{standard}'")
    )
    device_limit: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class PlanPrice(UUIDPk, Timestamps, Base):
    """Money is integer minor units + ISO-4217 currency (ADR-013)."""

    __tablename__ = "plan_prices"
    __table_args__ = (
        CheckConstraint(check_in("period_unit", PeriodUnit), name="period_unit"),
        CheckConstraint("period_count BETWEEN 1 AND 36", name="period_count"),
        CheckConstraint("amount_minor >= 0", name="amount_minor"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), index=True
    )
    period_unit: Mapped[str] = mapped_column(String(8))
    period_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    currency: Mapped[str] = mapped_column(String(3))
    amount_minor: Mapped[int] = mapped_column(Integer)
    # Store product/price identifiers per provider (stripe_price_id, apple_product_id, ...).
    provider_ids: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, server_default="{}")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    valid_from: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Subscription(UUIDPk, Timestamps, Base):
    """Provider-agnostic entitlement (ADR-008). At most one live row per user."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(check_in("status", SubscriptionStatus), name="status"),
        CheckConstraint(check_in("provider", Provider), name="provider"),
        CheckConstraint("current_period_end > current_period_start", name="period"),
        Index(
            "uq_subscriptions_one_live_per_user",
            "user_id",
            unique=True,
            postgresql_where=text(LIVE_STATUSES_SQL),
        ),
        UniqueConstraint(
            "provider", "provider_subscription_id", name="uq_subscriptions_provider_sub_id"
        ),
        Index("ix_subscriptions_status_period_end", "status", "current_period_end"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT")
    )
    plan_price_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_prices.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(16))
    provider_subscription_id: Mapped[str | None] = mapped_column(String(255))
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    current_period_start: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    canceled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    grace_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # The period end a reminder was last sent for — makes the reminder job idempotent.
    reminder_sent_for: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_threshold_days: Mapped[int | None] = mapped_column(Integer)


class FamilyMember(UUIDPk, Timestamps, Base):
    __tablename__ = "family_members"
    __table_args__ = (
        UniqueConstraint("subscription_id", "user_id", name="uq_family_members_sub_user"),
        CheckConstraint("role IN ('owner', 'member')", name="role"),
    )

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), default="member", server_default="member")


class Payment(UUIDPk, Timestamps, Base):
    """Never holds card data — only provider references, amounts and status."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider", "provider_payment_id", name="uq_payments_provider_payment_id"),
        CheckConstraint(check_in("provider", Provider), name="provider"),
        CheckConstraint(check_in("status", PaymentStatus), name="status"),
        CheckConstraint(check_in("kind", PaymentKind), name="kind"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
        CheckConstraint(
            "referral_percent_off IS NULL OR referral_percent_off BETWEEN 1 AND 100",
            name="referral_percent_off",
        ),
        Index("ix_payments_status_provider", "status", "provider"),
    )

    # SET NULL: accounting records outlive a deleted account.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(16))
    provider_payment_id: Mapped[str] = mapped_column(String(255))
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    # What was bought — the period to grant comes from the price, never from the provider.
    plan_price_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_prices.id", ondelete="SET NULL")
    )
    promo_code_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promo_codes.id", ondelete="SET NULL")
    )
    checkout_url: Mapped[str | None] = mapped_column(String(512))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # Crypto actually received (e.g. "GRAM", "1.2345") — informational, stored as reported.
    paid_asset: Mapped[str | None] = mapped_column(String(16))
    paid_amount: Mapped[str | None] = mapped_column(String(64))
    failure_reason: Mapped[str | None] = mapped_column(String(64))
    # Discount the buyer got for coming via a friend's referral link (first payment only).
    referral_percent_off: Mapped[int | None] = mapped_column(Integer)


class PaymentEvent(UUIDPk, Base):
    """Raw provider webhook events; unique (provider, event_id) gives idempotency."""

    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_payment_events_provider_event"),
        CheckConstraint(check_in("provider", Provider), name="provider"),
    )

    provider: Mapped[str] = mapped_column(String(16))
    event_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    received_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str | None] = mapped_column(String(64))


class Campaign(UUIDPk, Timestamps, Base):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(128))
    starts_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class PromoCode(UUIDPk, Timestamps, Base):
    __tablename__ = "promo_codes"
    __table_args__ = (
        CheckConstraint(check_in("kind", PromoKind), name="kind"),
        CheckConstraint(
            "(kind = 'percent_off' AND percent_off BETWEEN 1 AND 100)"
            " OR (kind = 'amount_off' AND amount_off_minor > 0 AND currency IS NOT NULL)"
            " OR (kind = 'free_days' AND free_days BETWEEN 1 AND 366 AND plan_id IS NOT NULL)",
            name="kind_fields",
        ),
        CheckConstraint("max_redemptions IS NULL OR max_redemptions > 0", name="max_redemptions"),
        CheckConstraint("redemption_count >= 0", name="redemption_count"),
    )

    code: Mapped[str] = mapped_column(CITEXT, unique=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(16))
    percent_off: Mapped[int | None] = mapped_column(Integer)
    amount_off_minor: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    free_days: Mapped[int | None] = mapped_column(Integer)
    # For free_days: the plan granted. For discounts: optional restriction to one plan.
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT")
    )
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    redemption_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    valid_from: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class PromoRedemption(UUIDPk, Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (
        UniqueConstraint("promo_code_id", "user_id", name="uq_promo_redemptions_code_user"),
    )

    promo_code_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promo_codes.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL")
    )
    redeemed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class ReferralReward(UUIDPk, Timestamps, Base):
    """One per referred user who paid: the referrer was credited `bonus_days` of free service.

    The unique `referred_id` makes the credit idempotent (a repeated webhook/poll can't add the
    days twice)."""

    __tablename__ = "referral_rewards"
    __table_args__ = (CheckConstraint("bonus_days BETWEEN 0 AND 365", name="bonus_days"),)

    referrer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    referred_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    source_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="SET NULL")
    )
    bonus_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
