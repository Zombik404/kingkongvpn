"""String enums stored as VARCHAR with CHECK constraints (no native PG enums: easier migrations)."""

from __future__ import annotations

from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class Role(StrEnum):
    SUPPORT = "support"
    OPS = "ops"
    FINANCE = "finance"
    SUPERADMIN = "superadmin"


class ActionTokenPurpose(StrEnum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"  # noqa: S105 - enum label, not a secret


class DevicePlatform(StrEnum):
    ANDROID = "android"
    IOS = "ios"
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    ROUTER = "router"
    OTHER = "other"


class DeviceStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class ServerStatus(StrEnum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    DRAINING = "draining"
    MAINTENANCE = "maintenance"
    DISABLED = "disabled"


class AssignmentState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REMOVING = "removing"


class PeriodUnit(StrEnum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"


class SubscriptionStatus(StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    GRACE = "grace"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REFUNDED = "refunded"


class Provider(StrEnum):
    TRIAL = "trial"
    PROMO = "promo"
    ADMIN = "admin"
    STRIPE = "stripe"
    APPLE = "apple"
    GOOGLE = "google"
    TELEGRAM = "telegram"
    PAYPAL = "paypal"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentKind(StrEnum):
    INITIAL = "initial"
    RENEWAL = "renewal"
    REFUND = "refund"


class PromoKind(StrEnum):
    PERCENT_OFF = "percent_off"
    AMOUNT_OFF = "amount_off"
    FREE_DAYS = "free_days"


class TicketStatus(StrEnum):
    OPEN = "open"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationChannel(StrEnum):
    EMAIL = "email"
    TELEGRAM = "telegram"
    PUSH = "push"


class NotificationStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class ActorType(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"
    SERVICE = "service"
    ANONYMOUS = "anonymous"


class AuditResult(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILURE = "failure"


def check_in(column: str, enum: type[StrEnum]) -> str:
    values = ", ".join(f"'{m.value}'" for m in enum)
    return f"{column} IN ({values})"
