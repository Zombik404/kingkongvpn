from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk
from app.models.enums import ActionTokenPurpose, UserStatus, check_in


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(check_in("status", UserStatus), name="status"),
        CheckConstraint("char_length(locale) BETWEEN 2 AND 8", name="locale"),
    )

    email: Mapped[str | None] = mapped_column(CITEXT, unique=True)
    email_verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    locale: Mapped[str] = mapped_column(String(8), default="en", server_default="en")
    status: Mapped[str] = mapped_column(
        String(16), default=UserStatus.ACTIVE, server_default=UserStatus.ACTIVE.value
    )
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), default=list, server_default=text("'{}'::varchar[]")
    )
    # Bumped to invalidate every access token at once (logout-all, password reset, suspension).
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_enabled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    totp_last_counter: Mapped[int | None] = mapped_column(BigInteger)
    trial_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    referral_code: Mapped[str | None] = mapped_column(String(16), unique=True)
    referred_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    @property
    def mfa_enabled(self) -> bool:
        return self.totp_enabled_at is not None


class AuthSession(UUIDPk, Base):
    """A login session == a refresh-token family (ADR-007)."""

    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(32))
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    user_agent: Mapped[str | None] = mapped_column(String(256))
    ip_prefix: Mapped[str | None] = mapped_column(String(64))


class RefreshToken(UUIDPk, Base):
    """Opaque refresh token, stored as HMAC-SHA256(pepper, token). Rotated on every use."""

    __tablename__ = "refresh_tokens"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_sessions.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )


class UserActionToken(UUIDPk, Base):
    """Single-use, expiring, hashed token for email verification / password reset."""

    __tablename__ = "user_action_tokens"
    __table_args__ = (CheckConstraint(check_in("purpose", ActionTokenPurpose), name="purpose"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
