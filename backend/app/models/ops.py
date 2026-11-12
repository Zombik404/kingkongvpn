"""Support, notifications, audit log and global settings."""

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
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.models.base import Base, Timestamps, UUIDPk
from app.models.enums import (
    ActorType,
    AuditResult,
    NotificationChannel,
    NotificationStatus,
    TicketPriority,
    TicketStatus,
    check_in,
)


class SupportTicket(UUIDPk, Timestamps, Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        CheckConstraint(check_in("status", TicketStatus), name="status"),
        CheckConstraint(check_in("priority", TicketPriority), name="priority"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(200))
    priority: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class TicketMessage(UUIDPk, Timestamps, Base):
    __tablename__ = "ticket_messages"
    __table_args__ = (CheckConstraint("author_type IN ('user', 'staff')", name="author_type"),)

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    author_type: Mapped[str] = mapped_column(String(8))
    body: Mapped[str] = mapped_column(Text)
    internal: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Notification(UUIDPk, Timestamps, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(check_in("channel", NotificationChannel), name="channel"),
        CheckConstraint(check_in("status", NotificationStatus), name="status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(255))


class NotificationPreference(Timestamps, Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    email_marketing: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    email_service: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    telegram: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    push: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class AuditLog(Base):
    """Append-only. Metadata is scrubbed of secrets before insert (services.audit)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(check_in("actor_type", ActorType), name="actor_type"),
        CheckConstraint(check_in("result", AuditResult), name="result"),
        Index("ix_audit_logs_target", "target_type", "target_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    actor_type: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16))
    ip_prefix: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class Setting(Base):
    """Typed global policy values; the schema of each key lives in services.settings."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
