"""Profile, data export and account deletion."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidCredentials
from app.models import AuthSession, Device, Payment, Subscription, User
from app.models.base import utcnow
from app.models.enums import ActorType, DeviceStatus, UserStatus
from app.schemas.domain import UserOut
from app.security.passwords import PasswordService
from app.security.principal import ClientInfo
from app.services import audit
from app.subscriptions import service as subs

DELETED_ACCOUNT_RETENTION_DAYS = 30


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        locale=user.locale,
        roles=list(user.roles),
        mfa_enabled=user.mfa_enabled,
        has_telegram=user.telegram_id is not None,
        created_at=user.created_at,
    )


def _iso(v: Any) -> Any:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


async def export_data(db: AsyncSession, user: User) -> dict[str, Any]:
    """Everything we hold about the user, machine-readable (GDPR Art. 15/20 style)."""
    devices = (await db.scalars(select(Device).where(Device.user_id == user.id))).all()
    subscriptions = (
        await db.scalars(select(Subscription).where(Subscription.user_id == user.id))
    ).all()
    payments = (await db.scalars(select(Payment).where(Payment.user_id == user.id))).all()
    sessions = (await db.scalars(select(AuthSession).where(AuthSession.user_id == user.id))).all()
    return {
        "exported_at": utcnow().isoformat(),
        "account": {
            "id": str(user.id),
            "email": user.email,
            "email_verified_at": _iso(user.email_verified_at),
            "locale": user.locale,
            "telegram_linked": user.telegram_id is not None,
            "mfa_enabled": user.mfa_enabled,
            "created_at": _iso(user.created_at),
            "last_login_at": _iso(user.last_login_at),
        },
        "devices": [
            {
                "id": str(d.id),
                "name": d.name,
                "platform": d.platform,
                "public_key": d.public_key,
                "ipv4": _iso(d.ipv4),
                "ipv6": _iso(d.ipv6),
                "status": d.status,
                "created_at": _iso(d.created_at),
                "revoked_at": _iso(d.revoked_at),
                "last_handshake_at": _iso(d.last_handshake_at),
            }
            for d in devices
        ],
        "subscriptions": [
            {
                "id": str(s.id),
                "status": s.status,
                "provider": s.provider,
                "period_start": _iso(s.current_period_start),
                "period_end": _iso(s.current_period_end),
            }
            for s in subscriptions
        ],
        "payments": [
            {
                "id": str(p.id),
                "provider": p.provider,
                "amount_minor": p.amount_minor,
                "currency": p.currency,
                "status": p.status,
                "kind": p.kind,
                "created_at": _iso(p.created_at),
            }
            for p in payments
        ],
        "sessions": [
            {
                "id": str(s.id),
                "created_at": _iso(s.created_at),
                "last_used_at": _iso(s.last_used_at),
                "user_agent": s.user_agent,
                "ip_prefix": s.ip_prefix,
                "revoked_at": _iso(s.revoked_at),
            }
            for s in sessions
        ],
    }


async def delete_account(
    db: AsyncSession, passwords: PasswordService, user_id: Any, password: str, client: ClientInfo
) -> None:
    """Anonymise immediately; the row itself is purged after the retention window.

    Personal identifiers (email, password hash, Telegram ID, TOTP seed) are cleared now so
    the address can be reused and nothing personal lingers. Payment rows are kept (accounting
    law) but lose their link to the user at purge time (FK SET NULL).
    """
    user = await db.get(User, user_id, with_for_update=True)
    assert user is not None
    if not (await passwords.verify(user.password_hash, password)).ok:
        raise InvalidCredentials("Password is incorrect.")
    now = utcnow()
    live = await subs.get_live(db, user.id, lock=True)
    if live is not None:
        await subs.revoke(
            db,
            live,
            actor_id=user.id,
            actor_type=ActorType.USER,
            ip=client.ip,
            reason="account_deleted",
        )
    await db.execute(
        update(Device)
        .where(Device.user_id == user.id, Device.status == DeviceStatus.ACTIVE)
        .values(status=DeviceStatus.REVOKED.value, revoked_at=now)
    )
    await subs.revoke_peer_access(db, user.id)
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason="account_deleted")
    )
    user.status = UserStatus.DELETED.value
    user.deleted_at = now
    user.email = None
    user.password_hash = None
    user.telegram_id = None
    user.totp_secret_encrypted = None
    user.totp_enabled_at = None
    user.roles = []
    user.token_version += 1
    audit.record(
        db,
        action="user.deleted",
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
        ip=client.ip,
    )
    await db.commit()
