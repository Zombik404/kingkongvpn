"""Peer assignment (ADR-004/006) and the node-facing desired state (ADR-002).

A device has at most one *active* assignment: its tunnel addresses are the same on every node,
so connecting elsewhere moves the peer (old node gets it removed, new node gets it added).
The desired state re-checks entitlement and device status at read time, so a missed
revision bump can never keep a revoked or unpaid peer on a node for longer than one poll.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import random
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import AppContext
from app.core.errors import AppError, NotAuthenticated, NotFound
from app.models import Device, DeviceUsageDaily, Location, PeerAssignment, Server, Subscription
from app.models.base import utcnow
from app.models.enums import AssignmentState, DeviceStatus, ServerStatus
from app.subscriptions import service as subs


class NotEntitled(AppError):
    status_code = 402
    code = "subscription_required"
    message = "You need an active subscription to connect."


class NoServerAvailable(AppError):
    status_code = 503
    code = "no_server_available"
    message = "No server is available in this location right now. Try another one."


@dataclass(frozen=True)
class ConnectInfo:
    server_id: uuid.UUID
    location_id: uuid.UUID
    endpoint: str
    server_public_key: str
    addresses: list[str]
    dns: list[str]
    allowed_ips: list[str]
    persistent_keepalive: int


def _fresh(ctx: AppContext) -> Any:
    cutoff = utcnow() - dt.timedelta(seconds=ctx.settings.node_heartbeat_stale_seconds)
    return and_(
        Server.status == ServerStatus.ACTIVE,
        Server.last_heartbeat_at >= cutoff,
        Server.wg_public_key.is_not(None),
    )


async def locations(ctx: AppContext, db: AsyncSession) -> list[tuple[Location, int]]:
    """Enabled locations that have at least one healthy node (count of healthy nodes)."""
    rows = (
        await db.execute(
            select(Location, func.count(Server.id))
            .join(Server, Server.location_id == Location.id)
            .where(Location.enabled.is_(True), _fresh(ctx))
            .group_by(Location.id)
            .order_by(Location.sort_order, Location.country_code, Location.city)
        )
    ).all()
    return [(loc, int(n)) for loc, n in rows]


def _endpoint(server: Server) -> str:
    if server.public_ipv4 is not None:
        return f"{server.public_ipv4}:{server.endpoint_port}"
    return f"[{server.public_ipv6}]:{server.endpoint_port}"


async def connect(
    ctx: AppContext,
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    device_id: uuid.UUID,
    location_id: uuid.UUID | None,
) -> ConnectInfo:
    device = await db.scalar(
        select(Device).where(Device.id == device_id, Device.user_id == user_id).with_for_update()
    )
    if device is None or device.status != DeviceStatus.ACTIVE:
        raise NotFound("Device not found.")
    ent = await subs.entitlement(db, user_id)
    if ent is None:
        raise NotEntitled()

    load = (
        select(PeerAssignment.server_id, func.count().label("n"))
        .where(PeerAssignment.state == AssignmentState.ACTIVE)
        .group_by(PeerAssignment.server_id)
        .subquery()
    )
    stmt = (
        select(Server, func.coalesce(load.c.n, 0))
        .outerjoin(load, load.c.server_id == Server.id)
        .join(Location, Location.id == Server.location_id)
        .where(_fresh(ctx), Location.enabled.is_(True), Server.tier.in_(ent.plan.server_tiers))
    )
    if location_id is not None:
        stmt = stmt.where(Server.location_id == location_id)
    candidates = [(s, int(n)) for s, n in (await db.execute(stmt)).all() if n < s.max_peers]
    if not candidates:
        raise NoServerAvailable()

    current = await db.scalar(
        select(PeerAssignment).where(
            PeerAssignment.device_id == device.id, PeerAssignment.state == AssignmentState.ACTIVE
        )
    )
    sticky = next((s for s, _ in candidates if current and s.id == current.server_id), None)
    if sticky is not None:
        server = sticky
    else:
        # least loaded, with a little randomness so simultaneous connects spread out
        server = min(candidates, key=lambda c: c[1] / c[0].max_peers + random.random() * 0.05)[0]  # noqa: S311

    touched: set[uuid.UUID] = set()
    moved = await db.execute(
        update(PeerAssignment)
        .where(
            PeerAssignment.device_id == device.id,
            PeerAssignment.server_id != server.id,
            PeerAssignment.state != AssignmentState.REMOVING,
        )
        .values(state=AssignmentState.REMOVING.value)
        .returning(PeerAssignment.server_id)
    )
    touched |= {r[0] for r in moved.all()}
    existing = await db.scalar(
        select(PeerAssignment).where(
            PeerAssignment.device_id == device.id, PeerAssignment.server_id == server.id
        )
    )
    if existing is None:
        db.add(
            PeerAssignment(
                device_id=device.id, server_id=server.id, state=AssignmentState.ACTIVE.value
            )
        )
        touched.add(server.id)
    elif existing.state != AssignmentState.ACTIVE:
        existing.state = AssignmentState.ACTIVE.value
        existing.assigned_at = utcnow()
        touched.add(server.id)
    if touched:
        await db.execute(
            update(Server).where(Server.id.in_(touched)).values(revision=Server.revision + 1)
        )
    await db.commit()
    return ConnectInfo(
        server_id=server.id,
        location_id=server.location_id,
        endpoint=_endpoint(server),
        server_public_key=server.wg_public_key or "",
        addresses=[f"{device.ipv4}/32", f"{device.ipv6}/128"],
        dns=list(ctx.settings.vpn_client_dns),
        allowed_ips=["0.0.0.0/0", "::/0"],
        persistent_keepalive=ctx.settings.vpn_persistent_keepalive,
    )


# --- node side -----------------------------------------------------------------------------
def new_node_token() -> str:
    return secrets.token_urlsafe(32)


async def authenticate_node(
    ctx: AppContext, db: AsyncSession, server_id: uuid.UUID, token: str | None
) -> Server:
    server = await db.get(Server, server_id)
    expected = server.agent_token_hash if server else None
    given = ctx.tokens.hash_opaque(token or "")
    if (
        server is None
        or expected is None
        or not token
        or not secrets.compare_digest(expected, given)
        or server.status == ServerStatus.DISABLED
    ):
        raise NotAuthenticated("Unknown node or bad token.")
    return server


async def desired_state(db: AsyncSession, server: Server) -> dict[str, Any]:
    live = select(Subscription.user_id).where(Subscription.status.in_(subs.LIVE))
    rows = (
        await db.execute(
            select(Device.public_key, Device.ipv4, Device.ipv6)
            .join(PeerAssignment, PeerAssignment.device_id == Device.id)
            .where(
                PeerAssignment.server_id == server.id,
                PeerAssignment.state == AssignmentState.ACTIVE,
                Device.status == DeviceStatus.ACTIVE,
                Device.ipv4.is_not(None),
                Device.user_id.in_(live),
            )
            .order_by(Device.public_key)
        )
    ).all()
    return {
        "revision": server.revision,
        "peers": [
            {"public_key": pk, "allowed_ips": [f"{v4}/32", f"{v6}/128"]} for pk, v4, v6 in rows
        ],
    }


async def wait_for_revision(
    ctx: AppContext, db: AsyncSession, server_id: uuid.UUID, since: int
) -> None:
    """Long-poll: return as soon as the node's revision moves past `since` (or on timeout)."""
    deadline = asyncio.get_running_loop().time() + ctx.settings.node_longpoll_seconds
    while asyncio.get_running_loop().time() < deadline:
        rev = await db.scalar(select(Server.revision).where(Server.id == server_id))
        await db.rollback()  # end the snapshot so the next read sees new commits
        if rev is None or rev != since:
            return
        await asyncio.sleep(1.0)


async def heartbeat(db: AsyncSession, server: Server, data: dict[str, Any]) -> None:
    now = utcnow()
    srv = await db.get(Server, server.id, with_for_update=True)
    assert srv is not None
    srv.last_heartbeat_at = now
    srv.last_metrics = {
        k: data[k]
        for k in (
            "peers_total",
            "peers_active",
            "rx_bytes",
            "tx_bytes",
            "applied_revision",
            "errors",
            "agent_version",
        )
        if k in data
    }
    if srv.wg_public_key is None and data.get("wg_public_key"):
        srv.wg_public_key = str(data["wg_public_key"])
    # "Last connected" at 1-hour resolution only (ADR-010).
    hour_ago_keys = [
        k
        for k, ts in (data.get("handshakes") or {}).items()
        if isinstance(ts, int) and ts > 0 and now.timestamp() - ts < 3600
    ]
    await record_transfer(db, srv.id, data.get("transfer") or {}, now.date())
    if hour_ago_keys:
        stamp = now.replace(minute=0, second=0, microsecond=0)
        await db.execute(
            update(Device)
            .where(Device.public_key.in_(hour_ago_keys[:5000]))
            .values(last_handshake_at=stamp)
        )
    await db.commit()


async def release_idle_assignments(db: AsyncSession, idle: dt.timedelta) -> int:
    """Take long-unused peers off their nodes (ADR-006 "on-demand assignment").

    Idle = no handshake within `idle` and assigned earlier than that (a fresh assignment
    gets the full window to make its first handshake). The device keeps its addresses, so
    the next `connect` puts it back. Returns the number of released assignments."""
    cutoff = utcnow() - idle
    idle_devices = select(Device.id).where(
        or_(Device.last_handshake_at.is_(None), Device.last_handshake_at < cutoff)
    )
    released = await db.execute(
        update(PeerAssignment)
        .where(
            PeerAssignment.state == AssignmentState.ACTIVE,
            PeerAssignment.assigned_at < cutoff,
            PeerAssignment.device_id.in_(idle_devices),
        )
        .values(state=AssignmentState.REMOVING.value)
        .returning(PeerAssignment.server_id)
    )
    servers = [r[0] for r in released.all()]
    if servers:
        await db.execute(
            update(Server).where(Server.id.in_(set(servers))).values(revision=Server.revision + 1)
        )
    await db.commit()
    return len(servers)


async def release_revoked_addresses(db: AsyncSession, older_than: dt.timedelta) -> int:
    """Give the tunnel addresses of devices revoked more than `older_than` ago back to the pool.

    By then their peers are long gone from every node (removal is picked up within one poll),
    so reusing an address can't route someone else's traffic to an old key."""
    result = await db.execute(
        update(Device)
        .where(
            Device.status == DeviceStatus.REVOKED,
            Device.revoked_at < utcnow() - older_than,
            Device.address_index.is_not(None),
        )
        .values(address_index=None, ipv4=None, ipv6=None)
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def purge_removed_assignments(db: AsyncSession, older_than: dt.timedelta) -> int:
    result = await db.execute(
        delete(PeerAssignment).where(
            PeerAssignment.state == AssignmentState.REMOVING,
            PeerAssignment.updated_at < utcnow() - older_than,
        )
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def record_transfer(
    db: AsyncSession, server_id: uuid.UUID, transfer: dict[str, Any], day: dt.date
) -> int:
    """Turn cumulative per-peer counters into per-device daily totals.

    WireGuard counters restart from 0 when a peer is re-added, so a counter smaller than the
    last one seen is treated as a fresh start. Returns the number of devices updated."""
    clean: dict[str, tuple[int, int]] = {}
    for key, pair in transfer.items():
        if (
            isinstance(key, str)
            and len(key) == 44
            and isinstance(pair, list | tuple)
            and len(pair) == 2
            and all(isinstance(v, int) and 0 <= v < 2**62 for v in pair)
        ):
            clean[key] = (int(pair[0]), int(pair[1]))
    if not clean:
        return 0
    rows = (
        await db.execute(
            select(PeerAssignment, Device.public_key)
            .join(Device, Device.id == PeerAssignment.device_id)
            .where(PeerAssignment.server_id == server_id, Device.public_key.in_(list(clean)))
            .with_for_update(of=PeerAssignment)
        )
    ).all()
    updated = 0
    for assignment, key in rows:
        rx, tx = clean[key]
        d_up = rx - assignment.last_rx_bytes if rx >= assignment.last_rx_bytes else rx
        d_down = tx - assignment.last_tx_bytes if tx >= assignment.last_tx_bytes else tx
        assignment.last_rx_bytes, assignment.last_tx_bytes = rx, tx
        if d_up or d_down:
            stmt = pg_insert(DeviceUsageDaily).values(
                device_id=assignment.device_id, day=day, download_bytes=d_down, upload_bytes=d_up
            )
            await db.execute(
                stmt.on_conflict_do_update(
                    index_elements=["device_id", "day"],
                    set_={
                        "download_bytes": DeviceUsageDaily.download_bytes + d_down,
                        "upload_bytes": DeviceUsageDaily.upload_bytes + d_up,
                    },
                )
            )
            updated += 1
    return updated


async def usage(db: AsyncSession, user_id: uuid.UUID, days: int) -> dict[str, Any]:
    """Daily totals for the user's devices over `days` (zero-filled) + top devices."""
    today = utcnow().date()
    start = today - dt.timedelta(days=days - 1)
    rows = (
        await db.execute(
            select(
                DeviceUsageDaily.day,
                func.sum(DeviceUsageDaily.download_bytes),
                func.sum(DeviceUsageDaily.upload_bytes),
            )
            .join(Device, Device.id == DeviceUsageDaily.device_id)
            .where(Device.user_id == user_id, DeviceUsageDaily.day >= start)
            .group_by(DeviceUsageDaily.day)
        )
    ).all()
    per_day = {d: (int(a or 0), int(b or 0)) for d, a, b in rows}
    series = []
    for i in range(days):
        d = start + dt.timedelta(days=i)
        down, up = per_day.get(d, (0, 0))
        series.append({"date": d.isoformat(), "download": down, "upload": up})
    top = (
        await db.execute(
            select(
                Device.id,
                Device.name,
                Device.platform,
                Device.status,
                func.sum(DeviceUsageDaily.download_bytes).label("down"),
                func.sum(DeviceUsageDaily.upload_bytes).label("up"),
            )
            .join(DeviceUsageDaily, DeviceUsageDaily.device_id == Device.id)
            .where(Device.user_id == user_id, DeviceUsageDaily.day >= start)
            .group_by(Device.id)
            .order_by(
                (
                    func.sum(DeviceUsageDaily.download_bytes)
                    + func.sum(DeviceUsageDaily.upload_bytes)
                ).desc()
            )
            .limit(5)
        )
    ).all()
    return {
        "days": days,
        "series": series,
        "total_download": sum(p["download"] for p in series),
        "total_upload": sum(p["upload"] for p in series),
        "top_devices": [
            {
                "device_id": str(i),
                "name": n,
                "platform": p,
                "status": s,
                "download": int(dn or 0),
                "upload": int(u or 0),
            }
            for i, n, p, s, dn, u in top
        ],
    }


async def purge_old_usage(db: AsyncSession, keep_days: int = 90) -> int:
    cutoff = utcnow().date() - dt.timedelta(days=keep_days)
    result = await db.execute(delete(DeviceUsageDaily).where(DeviceUsageDaily.day < cutoff))
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def protection_status(
    db: AsyncSession, ctx: AppContext, user_id: uuid.UUID, client_ip: str | None
) -> dict[str, Any]:
    """Is the caller's traffic going through our VPN right now?

    The Mini App's own requests tell: through the tunnel they arrive from a tunnel address (the
    API runs on the VPN node) or from one of our nodes' public addresses (API elsewhere, traffic
    leaves through a node). Nothing is stored; the IP is only compared.
    """
    off: dict[str, Any] = {"protected": False, "via": None, "device_id": None, "device_name": None}
    if not client_ip:
        return off
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return off
    s = ctx.settings
    if addr in s.vpn_tunnel_ipv4_pool or addr in s.vpn_tunnel_ipv6_pool:
        col = Device.ipv4 if addr.version == 4 else Device.ipv6
        dev = await db.scalar(
            select(Device).where(
                col == str(addr), Device.user_id == user_id, Device.status == DeviceStatus.ACTIVE
            )
        )
        return {
            "protected": True,
            "via": "tunnel",
            "device_id": dev.id if dev else None,
            "device_name": dev.name if dev else None,
        }
    col = Server.public_ipv4 if addr.version == 4 else Server.public_ipv6
    node = await db.scalar(
        select(Server.id).where(col == str(addr), Server.status == ServerStatus.ACTIVE).limit(1)
    )
    if node is not None:
        return {**off, "protected": True, "via": "exit"}
    return off
