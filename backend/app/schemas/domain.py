"""Request/response models for users, devices, plans, subscriptions and promo codes."""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.core.config import SUPPORTED_LOCALES
from app.models.enums import DevicePlatform, PeriodUnit, PromoKind


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _locale(v: str) -> str:
    if v not in SUPPORTED_LOCALES:
        raise ValueError(f"unsupported locale; one of {', '.join(SUPPORTED_LOCALES)}")
    return v


def _wg_public_key(v: str) -> str:
    """32-byte X25519 key, standard base64 (44 chars, '=' padded) — what WireGuard emits."""
    if len(v) != 44 or not v.endswith("="):
        raise ValueError("public_key must be a 44-character base64 WireGuard key")
    try:
        raw = base64.b64decode(v, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("public_key is not valid base64") from exc
    if len(raw) != 32:
        raise ValueError("public_key must decode to 32 bytes")
    if raw == bytes(32):
        raise ValueError("public_key must not be all zeros")
    return v


def _name(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("must not be blank")
    if any(ord(c) < 32 for c in v):
        raise ValueError("must not contain control characters")
    return v


Locale = Annotated[str, AfterValidator(_locale)]
WgPublicKey = Annotated[str, AfterValidator(_wg_public_key)]
DeviceName = Annotated[str, Field(min_length=1, max_length=64), AfterValidator(_name)]
I18nText = dict[Locale, Annotated[str, Field(min_length=1, max_length=200)]]


# --- users ---------------------------------------------------------------------
class UserOut(_Out):
    id: uuid.UUID
    email: str | None
    email_verified: bool
    locale: str
    roles: list[str]
    mfa_enabled: bool
    has_telegram: bool
    created_at: dt.datetime


class UserUpdateIn(_In):
    locale: Locale | None = None


class DeleteAccountIn(_In):
    # Accounts with a password confirm with it; accounts made in Telegram (no password)
    # confirm with fresh `initData` from the Mini App.
    password: str | None = Field(default=None, min_length=1, max_length=256)
    telegram_init_data: str | None = Field(default=None, min_length=1, max_length=8192)
    confirm: Literal["DELETE"]


class SessionOut(_Out):
    id: uuid.UUID
    created_at: dt.datetime
    last_used_at: dt.datetime
    user_agent: str | None
    current: bool


# --- devices -------------------------------------------------------------------
class DeviceIn(_In):
    name: DeviceName
    platform: DevicePlatform
    public_key: WgPublicKey


class DeviceRenameIn(_In):
    name: DeviceName


class DeviceOut(_Out):
    id: uuid.UUID
    name: str
    platform: str
    public_key: str
    ipv4: str | None
    ipv6: str | None
    status: str
    last_handshake_at: dt.datetime | None
    created_at: dt.datetime
    revoked_at: dt.datetime | None


class DeviceListOut(BaseModel):
    devices: list[DeviceOut]
    limit: int
    active_count: int


# --- plans -----------------------------------------------------------------------
class PriceOut(_Out):
    id: uuid.UUID
    period_unit: str
    period_count: int
    currency: str
    amount_minor: int


class PlanOut(_Out):
    id: uuid.UUID
    code: str
    name: str
    features: dict[str, Any]
    device_limit: int
    server_tiers: list[str]
    prices: list[PriceOut]


class PlanAdminOut(_Out):
    id: uuid.UUID
    code: str
    names: dict[str, str]
    features: dict[str, Any]
    device_limit: int
    server_tiers: list[str]
    is_trial: bool
    active: bool
    sort_order: int


class PlanCreateIn(_In):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,31}$")
    names: I18nText
    features: dict[str, Any] = Field(default_factory=dict)
    device_limit: int = Field(ge=1, le=100)
    server_tiers: list[Annotated[str, Field(pattern=r"^[a-z0-9_-]{1,16}$")]] = Field(
        default_factory=lambda: ["standard"], min_length=1, max_length=10
    )
    is_trial: bool = False
    active: bool = True
    sort_order: int = 0

    @model_validator(mode="after")
    def _needs_en(self) -> PlanCreateIn:
        if "en" not in self.names:
            raise ValueError("names must include 'en'")
        return self


class PlanUpdateIn(_In):
    names: I18nText | None = None
    features: dict[str, Any] | None = None
    device_limit: int | None = Field(default=None, ge=1, le=100)
    server_tiers: list[Annotated[str, Field(pattern=r"^[a-z0-9_-]{1,16}$")]] | None = Field(
        default=None, min_length=1, max_length=10
    )
    active: bool | None = None
    sort_order: int | None = None


class PriceAdminOut(_Out):
    id: uuid.UUID
    plan_id: uuid.UUID
    period_unit: str
    period_count: int
    currency: str
    amount_minor: int
    provider_ids: dict[str, str]
    active: bool
    valid_from: dt.datetime | None
    valid_until: dt.datetime | None


class PriceCreateIn(_In):
    period_unit: PeriodUnit
    period_count: int = Field(default=1, ge=1, le=36)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount_minor: int = Field(ge=0, le=10_000_000)
    provider_ids: dict[
        Annotated[str, Field(pattern=r"^[a-z_]{1,32}$")], Annotated[str, Field(max_length=200)]
    ] = Field(default_factory=dict)
    active: bool = True
    valid_from: dt.datetime | None = None
    valid_until: dt.datetime | None = None


class PriceUpdateIn(_In):
    provider_ids: (
        dict[
            Annotated[str, Field(pattern=r"^[a-z_]{1,32}$")], Annotated[str, Field(max_length=200)]
        ]
        | None
    ) = None
    active: bool | None = None
    valid_from: dt.datetime | None = None
    valid_until: dt.datetime | None = None


# --- subscriptions ----------------------------------------------------------------
class SubscriptionOut(_Out):
    id: uuid.UUID
    plan_code: str
    plan_name: str
    status: str
    provider: str
    auto_renew: bool
    current_period_start: dt.datetime
    current_period_end: dt.datetime
    cancel_at_period_end: bool
    grace_until: dt.datetime | None
    device_limit: int


class SubscriptionStatusOut(BaseModel):
    entitled: bool
    subscription: SubscriptionOut | None
    trial_available: bool


class GrantIn(_In):
    plan_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,31}$")
    days: int = Field(ge=1, le=3660)
    reason: str = Field(min_length=3, max_length=200)


class RevokeIn(_In):
    reason: str = Field(min_length=3, max_length=200)


# --- promo -------------------------------------------------------------------------
class PromoCodeIn(_In):
    code: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")


class PromoValidateIn(PromoCodeIn):
    price_id: uuid.UUID


class PromoQuoteOut(BaseModel):
    code: str
    kind: str
    currency: str
    original_amount_minor: int
    discounted_amount_minor: int


class PromoCreateIn(_In):
    code: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    kind: PromoKind
    percent_off: int | None = Field(default=None, ge=1, le=100)
    amount_off_minor: int | None = Field(default=None, ge=1)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    free_days: int | None = Field(default=None, ge=1, le=366)
    plan_code: str | None = None
    max_redemptions: int | None = Field(default=None, ge=1)
    valid_from: dt.datetime | None = None
    valid_until: dt.datetime | None = None
    active: bool = True

    @model_validator(mode="after")
    def _fields_match_kind(self) -> PromoCreateIn:
        need = {
            PromoKind.PERCENT_OFF: ("percent_off",),
            PromoKind.AMOUNT_OFF: ("amount_off_minor", "currency"),
            PromoKind.FREE_DAYS: ("free_days", "plan_code"),
        }[self.kind]
        missing = [f for f in need if getattr(self, f) is None]
        if missing:
            raise ValueError(f"{self.kind.value} requires {', '.join(missing)}")
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self


class PromoUpdateIn(_In):
    max_redemptions: int | None = Field(default=None, ge=1)
    valid_until: dt.datetime | None = None
    active: bool | None = None


class PromoAdminOut(_Out):
    id: uuid.UUID
    code: str
    kind: str
    percent_off: int | None
    amount_off_minor: int | None
    currency: str | None
    free_days: int | None
    plan_id: uuid.UUID | None
    max_redemptions: int | None
    redemption_count: int
    valid_from: dt.datetime | None
    valid_until: dt.datetime | None
    active: bool


# --- admin --------------------------------------------------------------------------
class AdminUserOut(_Out):
    id: uuid.UUID
    email: str | None
    email_verified: bool
    status: str
    roles: list[str]
    mfa_enabled: bool
    created_at: dt.datetime
    last_login_at: dt.datetime | None
    active_devices: int
    subscription: SubscriptionOut | None


class AdminUserStatusIn(_In):
    status: Literal["active", "suspended"]
    reason: str = Field(min_length=3, max_length=200)


class AdminRolesIn(_In):
    roles: list[Literal["support", "ops", "finance", "superadmin"]] = Field(max_length=4)


class SettingIn(_In):
    value: Any


class AuditLogOut(_Out):
    id: uuid.UUID
    created_at: dt.datetime
    actor_id: uuid.UUID | None
    actor_type: str
    action: str
    target_type: str | None
    target_id: str | None
    result: str
    ip_prefix: str | None
    details: dict[str, Any]
