"""Staff API. Every route needs a permission (app.security.rbac) on an MFA-verified session;
every mutation writes an audit-log row in the same transaction."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import Client, Db, require
from app.api.v1.account import subscription_out
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.models import AuditLog, AuthSession, Device, Plan, PlanPrice, PromoCode, User
from app.models.base import utcnow
from app.models.enums import ActorType, DeviceStatus, Provider, Role, UserStatus
from app.schemas.domain import (
    AdminRolesIn,
    AdminUserOut,
    AdminUserStatusIn,
    AuditLogOut,
    GrantIn,
    PlanAdminOut,
    PlanCreateIn,
    PlanUpdateIn,
    PriceAdminOut,
    PriceCreateIn,
    PriceUpdateIn,
    PromoAdminOut,
    PromoCreateIn,
    PromoUpdateIn,
    RevokeIn,
    SettingIn,
    SubscriptionOut,
)
from app.security.principal import Principal
from app.security.rbac import Perm, is_staff
from app.services import audit, catalog
from app.services import settings as settings_service
from app.subscriptions import service as subs

router = APIRouter(prefix="/admin", tags=["admin"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100_000)]


def _audit(
    db: Db,
    principal: Principal,
    client: Client,
    action: str,
    target_type: str,
    target_id: Any,
    details: dict[str, Any] | None = None,
) -> None:
    audit.record(
        db,
        action=action,
        actor_id=principal.user.id,
        actor_type=ActorType.ADMIN,
        target_type=target_type,
        target_id=target_id,
        ip=client.ip,
        details=details,
    )


# --- users --------------------------------------------------------------------------
async def _admin_user_out(db: Db, user: User) -> AdminUserOut:
    count = await db.scalar(
        select(func.count())
        .select_from(Device)
        .where(Device.user_id == user.id, Device.status == DeviceStatus.ACTIVE)
    )
    return AdminUserOut(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        status=user.status,
        roles=list(user.roles),
        mfa_enabled=user.mfa_enabled,
        has_telegram=user.telegram_id is not None,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        active_devices=int(count or 0),
        subscription=await subscription_out(db, user),
    )


@router.get("/users", response_model=list[AdminUserOut])
async def search_users(
    db: Db,
    _: Annotated[Principal, Depends(require(Perm.USERS_READ))],
    q: Annotated[str | None, Query(max_length=254)] = None,
    status: Annotated[UserStatus | None, Query()] = None,
    staff_only: bool = False,
    limit: Limit = 25,
    offset: Offset = 0,
) -> list[AdminUserOut]:
    """Newest first. `q`: exact user ID, a Telegram ID (digits), a referral code, or an email
    prefix."""
    stmt = select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
    if status is not None:
        stmt = stmt.where(User.status == status)
    if staff_only:
        stmt = stmt.where(func.cardinality(User.roles) > 0)
    q = (q or "").strip()
    if q:
        try:
            stmt = stmt.where(User.id == uuid.UUID(q))
        except ValueError:
            if q.isdigit() and len(q) <= 15:
                stmt = stmt.where(User.telegram_id == int(q))
            elif len(q) == 8 and q.isalnum() and q.upper() == q:
                stmt = stmt.where(User.referral_code == q)
            else:
                escaped = q.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
                stmt = stmt.where(User.email.ilike(f"{escaped}%"))
    return [await _admin_user_out(db, u) for u in (await db.scalars(stmt)).all()]


async def _get_user(db: Db, user_id: uuid.UUID, lock: bool = False) -> User:
    user = await db.get(User, user_id, with_for_update=lock)
    if user is None:
        raise NotFound("User not found.")
    return user


@router.get("/users/{user_id}", response_model=AdminUserOut)
async def get_user(
    user_id: uuid.UUID, db: Db, _: Annotated[Principal, Depends(require(Perm.USERS_READ))]
) -> AdminUserOut:
    return await _admin_user_out(db, await _get_user(db, user_id))


@router.post("/users/{user_id}/status", response_model=AdminUserOut)
async def set_user_status(
    user_id: uuid.UUID,
    body: AdminUserStatusIn,
    db: Db,
    client: Client,
    principal: Annotated[Principal, Depends(require(Perm.USERS_WRITE))],
) -> AdminUserOut:
    """Suspend (signs out everywhere) or reactivate an account."""
    user = await _get_user(db, user_id, lock=True)
    if user.id == principal.user.id:
        raise Conflict("You can't change your own status.", code="self_action")
    if is_staff(user.roles) and Role.SUPERADMIN not in principal.user.roles:
        raise PermissionDenied("Only a superadmin can change a staff account.")
    if user.status == UserStatus.DELETED:
        raise Conflict("Deleted accounts can't be changed.", code="user_deleted")
    if user.status != body.status:
        user.status = body.status
        if body.status == UserStatus.SUSPENDED.value:
            user.token_version += 1
            await db.execute(
                update(AuthSession)
                .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=utcnow(), revoke_reason="suspended")
            )
            await subs.revoke_peer_access(db, user.id)
        _audit(
            db,
            principal,
            client,
            f"admin.user_{body.status}",
            "user",
            user.id,
            {"reason": body.reason},
        )
    await db.commit()
    return await _admin_user_out(db, user)


@router.put("/users/{user_id}/roles", response_model=AdminUserOut)
async def set_roles(
    user_id: uuid.UUID,
    body: AdminRolesIn,
    db: Db,
    client: Client,
    principal: Annotated[Principal, Depends(require(Perm.ROLES_WRITE))],
) -> AdminUserOut:
    user = await _get_user(db, user_id, lock=True)
    roles: list[str] = sorted(set(body.roles))
    if user.id == principal.user.id and Role.SUPERADMIN not in roles:
        raise Conflict("You can't remove your own superadmin role.", code="self_action")
    if user.status != UserStatus.ACTIVE:
        raise Conflict("Only active accounts can hold roles.", code="user_inactive")
    before = list(user.roles)
    user.roles = roles
    # Role changes take effect immediately: staff sessions are re-established with MFA.
    user.token_version += 1
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoke_reason="roles_changed")
    )
    _audit(
        db,
        principal,
        client,
        "admin.roles_changed",
        "user",
        user.id,
        {"before": before, "after": roles},
    )
    await db.commit()
    return await _admin_user_out(db, user)


@router.post("/users/{user_id}/subscription/grant", response_model=SubscriptionOut)
async def grant_subscription(
    user_id: uuid.UUID,
    body: GrantIn,
    db: Db,
    client: Client,
    principal: Annotated[Principal, Depends(require(Perm.SUBSCRIPTIONS_GRANT))],
) -> SubscriptionOut:
    """Goodwill / support: extend (or start) access by N days on a plan."""
    user = await _get_user(db, user_id, lock=True)
    if user.status != UserStatus.ACTIVE:
        raise Conflict("Only active accounts can receive access.", code="user_inactive")
    plan = await catalog.plan_by_code(db, body.plan_code)
    await subs.grant_days(
        db,
        user_id=user.id,
        plan=plan,
        days=body.days,
        provider=Provider.ADMIN,
        actor_id=principal.user.id,
        actor_type=ActorType.ADMIN,
        ip=client.ip,
        reason=body.reason,
    )
    await db.commit()
    out = await subscription_out(db, user)
    assert out is not None
    return out


@router.post("/users/{user_id}/subscription/revoke", status_code=204)
async def revoke_subscription(
    user_id: uuid.UUID,
    body: RevokeIn,
    db: Db,
    client: Client,
    principal: Annotated[Principal, Depends(require(Perm.SUBSCRIPTIONS_GRANT))],
) -> None:
    sub = await subs.get_live(db, user_id, lock=True)
    if sub is None:
        raise NotFound("No active subscription.")
    await subs.revoke(
        db,
        sub,
        actor_id=principal.user.id,
        actor_type=ActorType.ADMIN,
        ip=client.ip,
        reason=body.reason,
    )
    await db.commit()


# --- plans & prices ---------------------------------------------------------------------
@router.get("/plans", response_model=list[PlanAdminOut])
async def list_plans(
    db: Db, _: Annotated[Principal, Depends(require(Perm.PLANS_READ))]
) -> list[Plan]:
    return list((await db.scalars(select(Plan).order_by(Plan.sort_order, Plan.code))).all())


@router.post("/plans", response_model=PlanAdminOut, status_code=201)
async def create_plan(
    body: PlanCreateIn,
    db: Db,
    client: Client,
    principal: Annotated[Principal, Depends(require(Perm.PLANS_WRITE))],
) -> Plan:
    plan = await catalog.create_plan(db, body.model_dump())
    _audit(db, principal, client, "admin.plan_created", "plan", plan.id, {"plan": plan.code})
    await db.commit()
    return plan


async def _get_plan(db: Db, plan_id: uuid.UUID) -> Plan:
    plan = await db.get(Plan, plan_id, with_for_update=True)
    if plan is None:
        raise NotFound("Plan not found.")
    return plan


@router.patch("/plans/{plan_id}", response_model=PlanAdminOut)
async def update_plan(
    plan_id: uuid.UUID,
    body: PlanUpdateIn,
    db: Db,
    client: Client,
    principal: Annotated[Principal, Depends(require(Perm.PLANS_WRITE))],
) -> Plan:
    plan = await _get_plan(db, plan_id)
    changes = body.model_dump(exclude_unset=True)
    if "names" in changes and "en" not in changes["names"]:
        raise Conflict("names must include 'en'", code="validation_error")
    for key, value in changes.items():
        setattr(plan, key, value)
    _audit(
        db, principal, client, "admin.plan_updated", "plan", plan.id, {"fields": sorted(changes)}
    )
    await db.commit()
    await db.refresh(plan)
    return plan


@router.get("/plans/{plan_id}/prices", response_model=list[PriceAdminOut])
async def list_prices(
    plan_id: uuid.UUID, db: Db, _: Annotated[Principal, Depends(require(Perm.PLANS_READ))]
) -> list[PlanPrice]:
    return list(
        (
            await db.scalars(
                select(PlanPrice).where(PlanPrice.plan_id == plan_id).order_by(PlanPrice.created_at)
            )
        ).all()
    )


@router.post("/plans/{plan_id}/prices", response_model=PriceAdminOut, status_code=201)
async def create_price(
    plan_id: uuid.UUID,
    body: PriceCreateIn,
    db: Db,
    client: Client,
    principal: Annotated[Principal, Depends(require(Perm.PLANS_WRITE))],
) -> PlanPrice:
    """Prices are append-only in practice: deactivate and add a new one instead of editing
    amounts, so past payments keep pointing at what was actually charged."""
    await _get_plan(db, plan_id)
    if body.valid_from and body.valid_until and body.valid_until <= body.valid_from:
        raise Conflict("valid_until must be after valid_from", code="validation_error")
    price = PlanPrice(plan_id=plan_id, **body.model_dump(mode="python"))
    price.period_unit = body.period_unit.value
    db.add(price)
    await db.flush()
    _audit(
        db,
        principal,
        client,
        "admin.price_created",
        "plan_price",
        price.id,
        {"plan": str(plan_id), "amount_minor": price.amount_minor, "currency": price.currency},
    )
    await db.commit()
    await db.refresh(price)
    return price


@router.patch("/prices/{price_id}", response_model=PriceAdminOut)
async def update_price(
    price_id: uuid.UUID,
    body: PriceUpdateIn,
    db: Db,
    client: Client,
    principal: Annotated[Principal, Depends(require(Perm.PLANS_WRITE))],
) -> PlanPrice:
    price = await db.get(PlanPrice, price_id, with_for_update=True)
    if price is None:
        raise NotFound("Price not found.")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(price, key, value)
    _audit(
        db,
        principal,
        client,
        "admin.price_updated",
        "plan_price",
        price.id,
        {"fields": sorted(changes)},
    )
    await db.commit()
    await db.refresh(price)
    return price


# --- promo codes ----------------------------------------------------------------------
@router.get("/promo-codes", response_model=list[PromoAdminOut])
async def list_promo(
    db: Db,
    _: Annotated[Principal, Depends(require(Perm.PLANS_READ))],
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[PromoCode]:
    return list(
        (
            await db.scalars(
                select(PromoCode).order_by(PromoCode.created_at.desc()).limit(limit).offset(offset)
            )
        ).all()
    )


@router.post("/promo-codes", response_model=PromoAdminOut, status_code=201)
async def create_promo(
    body: PromoCreateIn,
    db: Db,
    client: Client,
    principal: Annotated[Principal, Depends(require(Perm.PROMO_WRITE))],
) -> PromoCode:
    plan_id = (await catalog.plan_by_code(db, body.plan_code)).id if body.plan_code else None
    data = body.model_dump(exclude={"plan_code"})
    data["kind"] = body.kind.value
    promo = PromoCode(**data, plan_id=plan_id)
    db.add(promo)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("This code already exists.", code="promo_code_taken") from exc
    _audit(
        db, principal, client, "admin.promo_created", "promo_code", promo.id, {"kind": promo.kind}
    )
    await db.commit()
    await db.refresh(promo)
    return promo


@router.patch("/promo-codes/{promo_id}", response_model=PromoAdminOut)
async def update_promo(
    promo_id: uuid.UUID,
    body: PromoUpdateIn,
    db: Db,
    client: Client,
    principal: Annotated[Principal, Depends(require(Perm.PROMO_WRITE))],
) -> PromoCode:
    promo = await db.get(PromoCode, promo_id, with_for_update=True)
    if promo is None:
        raise NotFound("Promo code not found.")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(promo, key, value)
    _audit(
        db,
        principal,
        client,
        "admin.promo_updated",
        "promo_code",
        promo.id,
        {"fields": sorted(changes)},
    )
    await db.commit()
    await db.refresh(promo)
    return promo


# --- settings & audit -------------------------------------------------------------------
@router.get("/settings")
async def list_settings(
    db: Db, _: Annotated[Principal, Depends(require(Perm.SETTINGS_READ))]
) -> dict[str, dict[str, Any]]:
    values = await settings_service.get_all(db)
    return {
        k: {"value": values[k], "default": d.default, "description": d.description}
        for k, d in settings_service.REGISTRY.items()
    }


@router.put("/settings/{key}")
async def put_setting(
    key: str,
    body: SettingIn,
    db: Db,
    client: Client,
    principal: Annotated[Principal, Depends(require(Perm.SETTINGS_WRITE))],
) -> dict[str, Any]:
    before = await settings_service.get_value(db, key)
    value = await settings_service.set_value(db, key, body.value, actor_id=principal.user.id)
    _audit(
        db,
        principal,
        client,
        "admin.setting_changed",
        "setting",
        key,
        {"before": before, "after": value},
    )
    await db.commit()
    return {"key": key, "value": value}


@router.get("/audit-logs", response_model=list[AuditLogOut])
async def audit_logs(
    db: Db,
    _: Annotated[Principal, Depends(require(Perm.AUDIT_READ))],
    action: Annotated[str | None, Query(max_length=64)] = None,
    actor_id: uuid.UUID | None = None,
    target_id: Annotated[str | None, Query(max_length=64)] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if action:
        stmt = stmt.where(or_(AuditLog.action == action, AuditLog.action.startswith(action + ".")))
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if target_id:
        stmt = stmt.where(AuditLog.target_id == target_id)
    return list((await db.scalars(stmt.limit(limit).offset(offset))).all())
