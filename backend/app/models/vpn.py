from __future__ import annotations

import datetime as dt
import ipaddress
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk
from app.models.enums import AssignmentState, DevicePlatform, DeviceStatus, ServerStatus, check_in

IPAddr = ipaddress.IPv4Address | ipaddress.IPv6Address


class Device(UUIDPk, Timestamps, Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(check_in("platform", DevicePlatform), name="platform"),
        CheckConstraint(check_in("status", DeviceStatus), name="status"),
        CheckConstraint("char_length(public_key) = 44", name="public_key_len"),
        CheckConstraint("address_index IS NULL OR address_index >= 0", name="address_index"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    platform: Mapped[str] = mapped_column(String(16))
    # Public key only — private keys never reach the platform (ADR-003). Unique forever:
    # a revoked key can't be re-registered.
    public_key: Mapped[str] = mapped_column(String(44), unique=True)
    # Offset into the tunnel pools (ADR-004). NULL once the device row is purged of addresses.
    address_index: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    ipv4: Mapped[Any | None] = mapped_column(INET, unique=True)
    ipv6: Mapped[Any | None] = mapped_column(INET, unique=True)
    status: Mapped[str] = mapped_column(
        String(16), default=DeviceStatus.ACTIVE, server_default=DeviceStatus.ACTIVE.value
    )
    last_handshake_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Location(UUIDPk, Timestamps, Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("country_code", "city", name="uq_locations_country_city"),
        CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="country_code"),
    )

    country_code: Mapped[str] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(64))
    names: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, server_default="{}")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Server(UUIDPk, Timestamps, Base):
    """A VPN node. Metrics live in Prometheus; `last_metrics` keeps only the latest snapshot."""

    __tablename__ = "servers"
    __table_args__ = (
        CheckConstraint(check_in("status", ServerStatus), name="status"),
        CheckConstraint("endpoint_port BETWEEN 1 AND 65535", name="endpoint_port"),
        CheckConstraint("max_peers > 0", name="max_peers"),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="RESTRICT"), index=True
    )
    hostname: Mapped[str] = mapped_column(String(253), unique=True)
    public_ipv4: Mapped[Any | None] = mapped_column(INET)
    public_ipv6: Mapped[Any | None] = mapped_column(INET)
    endpoint_port: Mapped[int] = mapped_column(Integer, default=51820, server_default="51820")
    wg_public_key: Mapped[str | None] = mapped_column(String(44), unique=True)
    tier: Mapped[str] = mapped_column(String(16), default="standard", server_default="standard")
    status: Mapped[str] = mapped_column(
        String(16),
        default=ServerStatus.PROVISIONING,
        server_default=ServerStatus.PROVISIONING.value,
    )
    max_peers: Mapped[int] = mapped_column(Integer, default=1500, server_default="1500")
    bandwidth_capacity_mbps: Mapped[int | None] = mapped_column(Integer)
    agent_cert_fingerprint: Mapped[str | None] = mapped_column(String(64), unique=True)
    last_heartbeat_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class PeerAssignment(UUIDPk, Timestamps, Base):
    __tablename__ = "peer_assignments"
    __table_args__ = (
        UniqueConstraint("device_id", "server_id", name="uq_peer_assignments_device_server"),
        CheckConstraint(check_in("state", AssignmentState), name="state"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[str] = mapped_column(
        String(16), default=AssignmentState.PENDING, server_default=AssignmentState.PENDING.value
    )
    assigned_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
