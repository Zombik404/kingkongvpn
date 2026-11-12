"""Device registration (public keys only, ADR-003) with plan-based limits."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import AppContext
from app.core.db import violated_constraint
from app.core.errors import AppError, Conflict, NotFound
from app.models import Device, PeerAssignment, Server, User
from app.models.base import utcnow
from app.models.enums import AssignmentState, DeviceStatus
from app.schemas.domain import DeviceOut
from app.security.principal import ClientInfo
from app.services import audit
from app.services import settings as settings_service
from app.subscriptions import service as subs
from app.vpn import allocator


class DeviceLimitReached(AppError):
    status_code = 409
    code = "device_limit_reached"
    message = "You've reached the device limit for your plan. Remove a device or upgrade."


class PublicKeyInUse(Conflict):
    code = "public_key_in_use"
    message = "This key is already registered. Generate a new key on the device."


def device_out(d: Device) -> DeviceOut:
    return DeviceOut(
        id=d.id,
        name=d.name,
        platform=d.platform,
        public_key=d.public_key,
        ipv4=str(d.ipv4) if d.ipv4 is not None else None,
        ipv6=str(d.ipv6) if d.ipv6 is not None else None,
        status=d.status,
        last_handshake_at=d.last_handshake_at,
        created_at=d.created_at,
        revoked_at=d.revoked_at,
    )


async def device_limit(db: AsyncSession, user_id: uuid.UUID) -> int:
    ent = await subs.entitlement(db, user_id)
    if ent is not None:
        return ent.plan.device_limit
    return int(await settings_service.get_value(db, "devices.limit_without_subscription"))


async def active_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(Device)
            .where(Device.user_id == user_id, Device.status == DeviceStatus.ACTIVE)
        )
        or 0
    )


async def list_devices(db: AsyncSession, user_id: uuid.UUID, include_revoked: bool) -> list[Device]:
    stmt = select(Device).where(Device.user_id == user_id).order_by(Device.created_at)
    if not include_revoked:
        stmt = stmt.where(Device.status == DeviceStatus.ACTIVE)
    return list((await db.scalars(stmt)).all())


async def register(
    ctx: AppContext,
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    name: str,
    platform: str,
    public_key: str,
    client: ClientInfo,
) -> Device:
    # Lock the user row: serialises concurrent registrations so the limit check can't race.
    await db.get(User, user_id, with_for_update=True)
    if await db.scalar(select(Device.id).where(Device.public_key == public_key)) is not None:
        raise PublicKeyInUse()
    limit = await device_limit(db, user_id)
    if await active_count(db, user_id) >= limit:
        raise DeviceLimitReached(details={"limit": limit})
    device = Device(user_id=user_id, name=name, platform=platform, public_key=public_key)
    try:
        await allocator.insert_with_address(db, device, ctx.address_pool)
    except IntegrityError as exc:
        if violated_constraint(exc) == "uq_devices_public_key":
            raise PublicKeyInUse() from exc
        raise
    audit.record(
        db,
        action="device.registered",
        actor_id=user_id,
        target_type="device",
        target_id=device.id,
        ip=client.ip,
        details={"platform": platform},
    )
    await db.commit()
    await db.refresh(device)
    return device


async def _owned(
    db: AsyncSession, user_id: uuid.UUID, device_id: uuid.UUID, lock: bool = False
) -> Device:
    stmt = select(Device).where(Device.id == device_id, Device.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    device = await db.scalar(stmt)
    if device is None:  # same answer for "not yours" and "doesn't exist"
        raise NotFound("Device not found.")
    return device


async def rename(db: AsyncSession, user_id: uuid.UUID, device_id: uuid.UUID, name: str) -> Device:
    device = await _owned(db, user_id, device_id, lock=True)
    if device.status != DeviceStatus.ACTIVE:
        raise Conflict("Revoked devices can't be renamed.", code="device_revoked")
    device.name = name
    await db.commit()
    await db.refresh(device)
    return device


async def revoke(
    db: AsyncSession, user_id: uuid.UUID, device_id: uuid.UUID, client: ClientInfo
) -> None:
    device = await _owned(db, user_id, device_id, lock=True)
    if device.status == DeviceStatus.REVOKED:
        return  # idempotent
    device.status = DeviceStatus.REVOKED.value
    device.revoked_at = utcnow()
    result = await db.execute(
        update(PeerAssignment)
        .where(
            PeerAssignment.device_id == device.id, PeerAssignment.state != AssignmentState.REMOVING
        )
        .values(state=AssignmentState.REMOVING.value)
        .returning(PeerAssignment.server_id)
    )
    servers = {r[0] for r in result.all()}
    if servers:
        await db.execute(
            update(Server).where(Server.id.in_(servers)).values(revision=Server.revision + 1)
        )
    audit.record(
        db,
        action="device.revoked",
        actor_id=user_id,
        target_type="device",
        target_id=device.id,
        ip=client.ip,
    )
    await db.commit()
