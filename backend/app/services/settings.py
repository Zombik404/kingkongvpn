"""Typed global settings ("everything commercial is data"). Each key has a schema and a default;
the DB row overrides the default. Admins change them through the API, never via code."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import Field, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFound
from app.models import Setting


@dataclass(frozen=True)
class SettingDef:
    adapter: TypeAdapter[Any]
    default: Any
    description: str


def _def(tp: Any, default: Any, description: str) -> SettingDef:
    adapter: TypeAdapter[Any] = TypeAdapter(tp)
    adapter.validate_python(default)
    return SettingDef(adapter, default, description)


REGISTRY: dict[str, SettingDef] = {
    "trial.enabled": _def(bool, False, "Offer a free trial to accounts that never had one."),
    "trial.days": _def(Annotated[int, Field(ge=1, le=30)], 3, "Trial length in days."),
    "trial.plan_code": _def(
        Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,31}$")],
        "trial",
        "Code of the plan whose entitlements a trial grants.",
    ),
    "subscription.grace_days": _def(
        Annotated[int, Field(ge=0, le=30)],
        3,
        "Days of continued access after a period ends without renewal.",
    ),
    "devices.limit_without_subscription": _def(
        Annotated[int, Field(ge=0, le=10)],
        1,
        "Devices an account may register before subscribing.",
    ),
    "reminders.days_before": _def(
        Annotated[list[Annotated[int, Field(ge=1, le=30)]], Field(max_length=5)],
        [3],
        "Days before a non-renewing period ends to email a reminder.",
    ),
    "access.invite_only": _def(
        bool,
        False,
        "Closed test: paying or a trial requires having redeemed an invite (free-days) code.",
    ),
    "referrals.enabled": _def(
        bool, True, "Referral program: discount for invited users, free days for referrers."
    ),
    "referrals.percent_off": _def(
        Annotated[int, Field(ge=1, le=100)],
        30,
        "Discount an invited user gets on their first payment.",
    ),
    "referrals.milestones": _def(
        bool, True, "Referral ranks (3/5/10/25 paying friends) with free days and app themes."
    ),
    "referrals.bonus_days": _def(
        Annotated[int, Field(ge=0, le=365)],
        14,
        "Free days for the referrer per invited user's first payment (0 = off).",
    ),
    "peers.idle_ttl_hours": _def(
        Annotated[int, Field(ge=1, le=24 * 30)],
        24,
        "Remove a peer from a node after this long without a handshake.",
    ),
}


class InvalidSetting(AppError):
    status_code = 422
    code = "invalid_setting"


async def get_value(session: AsyncSession, key: str) -> Any:
    definition = REGISTRY.get(key)
    if definition is None:
        raise NotFound(f"Unknown setting {key!r}.")
    row = await session.get(Setting, key)
    if row is None:
        return definition.default
    try:
        return definition.adapter.validate_python(row.value)
    except ValidationError:
        # A stored value that no longer matches the schema must not break requests.
        return definition.default


async def get_all(session: AsyncSession) -> dict[str, Any]:
    rows = {r.key: r for r in (await session.scalars(select(Setting))).all()}
    out: dict[str, Any] = {}
    for key, definition in REGISTRY.items():
        out[key] = definition.default
        if key in rows:
            try:
                out[key] = definition.adapter.validate_python(rows[key].value)
            except ValidationError:
                pass
    return out


async def set_value(
    session: AsyncSession, key: str, value: Any, *, actor_id: uuid.UUID | None
) -> Any:
    definition = REGISTRY.get(key)
    if definition is None:
        raise NotFound(f"Unknown setting {key!r}.")
    try:
        validated = definition.adapter.validate_python(value, strict=True)
    except ValidationError as exc:
        raise InvalidSetting(f"Invalid value for {key}: {exc.errors()[0]['msg']}") from exc
    stored = definition.adapter.dump_python(validated, mode="json")
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=stored, updated_by=actor_id))
    else:
        row.value = stored
        row.updated_by = actor_id
    return validated
