"""User-facing routes: profile, sessions, devices, plans, subscription, promo codes."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from app.api.deps import Client, Ctx, CurrentPrincipal, Db
from app.core.errors import NotFound
from app.i18n import negotiate
from app.models import AuthSession, Plan, User
from app.models.base import utcnow
from app.schemas.domain import (
    DeleteAccountIn,
    DeviceIn,
    DeviceListOut,
    DeviceOut,
    DeviceRenameIn,
    PlanOut,
    PromoCodeIn,
    PromoQuoteOut,
    PromoValidateIn,
    SessionOut,
    SubscriptionOut,
    SubscriptionStatusOut,
    UserOut,
    UserUpdateIn,
)
from app.services import catalog, devices, referrals, users
from app.services import settings as settings_service
from app.subscriptions import service as subs

users_router = APIRouter(prefix="/users/me", tags=["account"])
devices_router = APIRouter(prefix="/devices", tags=["devices"])
plans_router = APIRouter(prefix="/plans", tags=["plans"])
subs_router = APIRouter(prefix="/subscription", tags=["subscription"])
promo_router = APIRouter(prefix="/promo", tags=["promo"])
referral_router = APIRouter(prefix="/referrals", tags=["referrals"])


# --- profile ------------------------------------------------------------------------
@users_router.get("", response_model=UserOut)
async def me(principal: CurrentPrincipal) -> UserOut:
    return users.user_out(principal.user)


@users_router.patch("", response_model=UserOut)
async def update_me(body: UserUpdateIn, principal: CurrentPrincipal, db: Db) -> UserOut:
    user = await db.get(User, principal.user.id, with_for_update=True)
    assert user is not None
    if body.locale is not None:
        user.locale = body.locale
    await db.commit()
    return users.user_out(user)


@users_router.get("/export")
async def export_me(principal: CurrentPrincipal, db: Db) -> dict[str, Any]:
    """All personal data we hold, as JSON."""
    return await users.export_data(db, principal.user)


@users_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    body: DeleteAccountIn, principal: CurrentPrincipal, ctx: Ctx, db: Db, client: Client
) -> Response:
    """Irreversible: anonymises the account, revokes devices, ends access."""
    await users.delete_account(db, ctx.passwords, principal.user.id, body.password, client)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@users_router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(principal: CurrentPrincipal, db: Db) -> list[SessionOut]:
    rows = (
        await db.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == principal.user.id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utcnow(),
            )
            .order_by(AuthSession.last_used_at.desc())
        )
    ).all()
    return [
        SessionOut(
            id=s.id,
            created_at=s.created_at,
            last_used_at=s.last_used_at,
            user_agent=s.user_agent,
            current=s.id == principal.session.id,
        )
        for s in rows
    ]


@users_router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(session_id: uuid.UUID, principal: CurrentPrincipal, db: Db) -> Response:
    result = await db.execute(
        update(AuthSession)
        .where(
            AuthSession.id == session_id,
            AuthSession.user_id == principal.user.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow(), revoke_reason="user_revoked")
    )
    await db.commit()
    if getattr(result, "rowcount", 0) == 0:
        raise NotFound("Session not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- devices ------------------------------------------------------------------------
@devices_router.get("", response_model=DeviceListOut)
async def list_devices(
    principal: CurrentPrincipal, db: Db, include_revoked: Annotated[bool, Query()] = False
) -> DeviceListOut:
    items = await devices.list_devices(db, principal.user.id, include_revoked)
    return DeviceListOut(
        devices=[devices.device_out(d) for d in items],
        limit=await devices.device_limit(db, principal.user.id),
        active_count=await devices.active_count(db, principal.user.id),
    )


@devices_router.post("", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
async def register_device(
    body: DeviceIn, principal: CurrentPrincipal, ctx: Ctx, db: Db, client: Client
) -> DeviceOut:
    """Register a device by its WireGuard **public** key; returns its tunnel addresses.

    The private key must be generated and kept on the device (ADR-003)."""
    device = await devices.register(
        ctx,
        db,
        principal.user.id,
        name=body.name,
        platform=body.platform.value,
        public_key=body.public_key,
        client=client,
    )
    return devices.device_out(device)


@devices_router.patch("/{device_id}", response_model=DeviceOut)
async def rename_device(
    device_id: uuid.UUID, body: DeviceRenameIn, principal: CurrentPrincipal, db: Db
) -> DeviceOut:
    return devices.device_out(await devices.rename(db, principal.user.id, device_id, body.name))


@devices_router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    device_id: uuid.UUID, principal: CurrentPrincipal, db: Db, client: Client
) -> Response:
    """Revoke: the key stops working on every node and can't be registered again."""
    await devices.revoke(db, principal.user.id, device_id, client)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- plans --------------------------------------------------------------------------
@plans_router.get("", response_model=list[PlanOut])
async def list_plans(
    request: Request, db: Db, locale: Annotated[str | None, Query(max_length=8)] = None
) -> list[PlanOut]:
    """Purchasable plans with their currently valid prices (public)."""
    return await catalog.public_plans(db, negotiate(locale, request.headers.get("accept-language")))


# --- subscription -------------------------------------------------------------------
async def subscription_out(db: Db, user: User) -> SubscriptionOut | None:
    ent = await subs.entitlement(db, user.id)
    if ent is None:
        return None
    s, plan = ent.subscription, ent.plan
    return SubscriptionOut(
        id=s.id,
        plan_code=plan.code,
        plan_name=subs.plan_name(plan, user.locale),
        status=s.status,
        provider=s.provider,
        auto_renew=s.auto_renew,
        current_period_start=s.current_period_start,
        current_period_end=s.current_period_end,
        cancel_at_period_end=s.cancel_at_period_end,
        grace_until=s.grace_until,
        device_limit=plan.device_limit,
    )


@subs_router.get("", response_model=SubscriptionStatusOut)
async def get_subscription(principal: CurrentPrincipal, db: Db) -> SubscriptionStatusOut:
    out = await subscription_out(db, principal.user)
    trial_available = (
        out is None
        and principal.user.trial_used_at is None
        and bool(await settings_service.get_value(db, "trial.enabled"))
    )
    if trial_available:
        code = await settings_service.get_value(db, "trial.plan_code")
        trial_available = (
            await db.scalar(select(Plan.id).where(Plan.code == code, Plan.active.is_(True)))
            is not None
        )
    return SubscriptionStatusOut(
        entitled=out is not None, subscription=out, trial_available=trial_available
    )


@subs_router.post("/trial", response_model=SubscriptionOut, status_code=status.HTTP_201_CREATED)
async def start_trial(
    principal: CurrentPrincipal, ctx: Ctx, db: Db, client: Client
) -> SubscriptionOut:
    await subs.start_trial(ctx, db, principal.user.id, client.ip)
    out = await subscription_out(db, principal.user)
    assert out is not None
    return out


@subs_router.post("/cancel", response_model=SubscriptionOut)
async def cancel(principal: CurrentPrincipal, db: Db, client: Client) -> SubscriptionOut:
    """Stop at the end of the current period (access continues until then)."""
    await subs.set_cancel(db, principal.user.id, True, client.ip)
    out = await subscription_out(db, principal.user)
    assert out is not None
    return out


@subs_router.post("/resume", response_model=SubscriptionOut)
async def resume(principal: CurrentPrincipal, db: Db, client: Client) -> SubscriptionOut:
    await subs.set_cancel(db, principal.user.id, False, client.ip)
    out = await subscription_out(db, principal.user)
    assert out is not None
    return out


# --- promo --------------------------------------------------------------------------
@promo_router.post("/validate", response_model=PromoQuoteOut)
async def validate_promo(
    body: PromoValidateIn, principal: CurrentPrincipal, ctx: Ctx, db: Db
) -> PromoQuoteOut:
    """Preview a discount code against a price; it's applied at checkout."""
    promo, price, discounted = await catalog.quote(
        db, ctx.limiter, principal.user.id, body.code, body.price_id
    )
    return PromoQuoteOut(
        code=promo.code,
        kind=promo.kind,
        currency=price.currency,
        original_amount_minor=price.amount_minor,
        discounted_amount_minor=discounted,
    )


@promo_router.post("/redeem", response_model=SubscriptionOut)
async def redeem_promo(
    body: PromoCodeIn, principal: CurrentPrincipal, ctx: Ctx, db: Db, client: Client
) -> SubscriptionOut:
    """Redeem a free-days code: extends current access or starts it."""
    await catalog.redeem_free_days(db, ctx.limiter, principal.user.id, body.code, client.ip)
    out = await subscription_out(db, principal.user)
    assert out is not None
    return out


# --- referrals ------------------------------------------------------------------------
class ReferralOut(BaseModel):
    enabled: bool
    code: str
    link: str | None
    percent_off: int  # what a friend gets off their first payment via your link
    bonus_days: int  # what you get per friend whose first payment succeeds
    invited: int  # friends who joined via your link
    paid: int  # ...of them, have paid
    my_discount: int  # % off your own next checkout because a friend invited you (0 = none)


class ReferralClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=4, max_length=16, pattern=r"^[A-Za-z0-9]+$")


@referral_router.get("", response_model=ReferralOut)
async def my_referrals(principal: CurrentPrincipal, ctx: Ctx, db: Db) -> dict[str, Any]:
    """Your referral link and stats. A friend who joins via your link gets `percent_off` off their
    first payment; when that payment succeeds you get `bonus_days` free days."""
    return await referrals.summary(db, ctx.settings, principal.user)


@referral_router.post("/claim", status_code=status.HTTP_204_NO_CONTENT)
async def claim_referral(
    body: ReferralClaimIn, principal: CurrentPrincipal, db: Db, client: Client
) -> Response:
    """Attach the referrer from a `ref_<code>` link (only before your first payment)."""
    await referrals.claim(db, principal.user.id, body.code, client.ip)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
