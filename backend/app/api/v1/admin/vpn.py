"""Staff API for the VPN network: locations and servers (ROADMAP Phase 4 "server registry").

Same rules as the rest of the admin API: a permission on an MFA-verified session and an
audit-log row for every change. Node API tokens are shown once (on create / rotate) and stored
only as an HMAC; they never appear in the audit log.

Server status and what it does (ADR-006):
- ``active``       — gets new connections while its heartbeat is fresh.
- ``draining`` / ``maintenance`` — no new connections; peers already on it keep working.
- ``disabled``     — the node is refused (it can't fetch peers any more) and every assignment
                     on it is released, so the device's next connect picks another node.
- ``provisioning`` — registered, waiting to be switched on.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import AfterValidator, BaseModel, Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import Client, Ctx, Db, require
from app.core.errors import Conflict, NotFound
from app.models import Location, PeerAssignment, Server
from app.models.base import utcnow
from app.models.enums import ActorType, AssignmentState, ServerStatus
from app.schemas.domain import I18nText, WgPublicKey
from app.security.principal import Principal
from app.security.rbac import Perm
from app.services import audit
from app.vpn.service import new_node_token

router = APIRouter(prefix="/admin/vpn", tags=["admin", "vpn"])

Reader = Annotated[Principal, Depends(require(Perm.SERVERS_READ))]
Writer = Annotated[Principal, Depends(require(Perm.SERVERS_WRITE))]

_LABEL = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
_HOST = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(\.{_LABEL})*$")


def _hostname(v: str) -> str:
    v = v.strip().lower()
    if not _HOST.match(v):
        raise ValueError("hostname: letters, digits, '-' and '.' only")
    return v


def _country(v: str) -> str:
    v = v.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", v):
        raise ValueError("country_code must be two letters (ISO 3166-1)")
    return v


Hostname = Annotated[str, AfterValidator(_hostname)]
Country = Annotated[str, AfterValidator(_country)]
City = Annotated[str, Field(min_length=1, max_length=64)]
Tier = Annotated[str, Field(pattern=r"^[a-z0-9_-]{1,16}$")]
Reason = Annotated[str, Field(min_length=3, max_length=200)]


class LocationIn(BaseModel):
    country_code: Country
    city: City | None = None
    names: I18nText = Field(default_factory=dict)
    sort_order: int = Field(default=0, ge=-1000, le=1000)
    enabled: bool = True


class LocationPatch(BaseModel):
    names: I18nText | None = None
    sort_order: int | None = Field(default=None, ge=-1000, le=1000)
    enabled: bool | None = None


class ServerIn(BaseModel):
    hostname: Hostname
    location_id: uuid.UUID
    ipv4: ipaddress.IPv4Address | None = None
    ipv6: ipaddress.IPv6Address | None = None
    endpoint_port: int = Field(default=51820, ge=1, le=65535)
    wg_public_key: WgPublicKey | None = None  # else taken from the first heartbeat
    max_peers: int = Field(default=1500, ge=1, le=65_000)
    tier: Tier = "standard"
    status: ServerStatus = ServerStatus.ACTIVE

    @model_validator(mode="after")
    def _needs_an_address(self) -> ServerIn:
        if self.ipv4 is None and self.ipv6 is None:
            raise ValueError("give ipv4 and/or ipv6")
        return self


class ServerPatch(BaseModel):
    reason: Reason
    status: ServerStatus | None = None
    max_peers: int | None = Field(default=None, ge=1, le=65_000)
    tier: Tier | None = None
    location_id: uuid.UUID | None = None


class ReasonIn(BaseModel):
    reason: Reason


def _location_out(loc: Location, servers: int = 0, healthy: int = 0) -> dict[str, Any]:
    return {
        "id": str(loc.id),
        "country_code": loc.country_code,
        "city": loc.city,
        "names": loc.names,
        "sort_order": loc.sort_order,
        "enabled": loc.enabled,
        "servers": servers,
        "healthy_servers": healthy,
        "visible_to_users": loc.enabled and healthy > 0,
    }


def _stale_cutoff(ctx: Ctx) -> dt.datetime:
    return utcnow() - dt.timedelta(seconds=ctx.settings.node_heartbeat_stale_seconds)


def _server_out(ctx: Ctx, s: Server, peers: int) -> dict[str, Any]:
    fresh = s.last_heartbeat_at is not None and s.last_heartbeat_at >= _stale_cutoff(ctx)
    metrics = s.last_metrics or {}
    applied = metrics.get("applied_revision")
    return {
        "id": str(s.id),
        "hostname": s.hostname,
        "location_id": str(s.location_id),
        "ipv4": str(s.public_ipv4) if s.public_ipv4 is not None else None,
        "ipv6": str(s.public_ipv6) if s.public_ipv6 is not None else None,
        "endpoint_port": s.endpoint_port,
        "wg_public_key": s.wg_public_key,
        "tier": s.tier,
        "status": s.status,
        "max_peers": s.max_peers,
        "peers": peers,
        "load": round(peers / s.max_peers, 3),
        "heartbeat_fresh": fresh,
        # what users get: only an active node with a fresh heartbeat and a key takes connections
        "accepting": s.status == ServerStatus.ACTIVE and fresh and s.wg_public_key is not None,
        "last_heartbeat_at": s.last_heartbeat_at,
        "revision": s.revision,
        "applied_revision": applied,
        "in_sync": applied == s.revision if applied is not None else None,
        "agent_version": metrics.get("agent_version"),
        "agent_errors": metrics.get("errors"),
        "has_token": s.agent_token_hash is not None,
        "created_at": s.created_at,
    }


def _audit(
    db: Db, p: Principal, client: Client, action: str, kind: str, target: Any, details: Any
) -> None:
    audit.record(
        db,
        action=action,
        actor_id=p.user.id,
        actor_type=ActorType.ADMIN,
        target_type=kind,
        target_id=target,
        ip=client.ip,
        details=details,
    )


async def _peer_counts(db: Db, server_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not server_ids:
        return {}
    rows = await db.execute(
        select(PeerAssignment.server_id, func.count())
        .where(
            PeerAssignment.server_id.in_(server_ids),
            PeerAssignment.state == AssignmentState.ACTIVE,
        )
        .group_by(PeerAssignment.server_id)
    )
    return {sid: int(n) for sid, n in rows.all()}


async def _get_location(db: Db, location_id: uuid.UUID, *, lock: bool = False) -> Location:
    stmt = select(Location).where(Location.id == location_id)
    loc = await db.scalar(stmt.with_for_update() if lock else stmt)
    if loc is None:
        raise NotFound("Location not found.")
    return loc


async def _get_server(db: Db, server_id: uuid.UUID, *, lock: bool = False) -> Server:
    stmt = select(Server).where(Server.id == server_id)
    srv = await db.scalar(stmt.with_for_update() if lock else stmt)
    if srv is None:
        raise NotFound("Server not found.")
    return srv


# --- locations ----------------------------------------------------------------------------
@router.get("/locations")
async def list_locations(db: Db, ctx: Ctx, _: Reader) -> list[dict[str, Any]]:
    cutoff = _stale_cutoff(ctx)
    counts = {
        lid: (int(total), int(healthy or 0))
        for lid, total, healthy in (
            await db.execute(
                select(
                    Server.location_id,
                    func.count(),
                    func.count().filter(
                        Server.status == ServerStatus.ACTIVE,
                        Server.last_heartbeat_at >= cutoff,
                        Server.wg_public_key.is_not(None),
                    ),
                ).group_by(Server.location_id)
            )
        ).all()
    }
    locs = (
        await db.scalars(
            select(Location).order_by(Location.sort_order, Location.country_code, Location.city)
        )
    ).all()
    return [_location_out(loc, *counts.get(loc.id, (0, 0))) for loc in locs]


@router.post("/locations", status_code=201)
async def create_location(
    body: LocationIn, db: Db, client: Client, principal: Writer
) -> dict[str, Any]:
    loc = Location(
        country_code=body.country_code,
        city=body.city,
        names=dict(body.names)
        or {"en": f"{body.city}, {body.country_code}" if body.city else body.country_code},
        sort_order=body.sort_order,
        enabled=body.enabled,
    )
    db.add(loc)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("This location already exists.", code="location_exists") from exc
    _audit(
        db,
        principal,
        client,
        "admin.location_created",
        "location",
        loc.id,
        {"country": loc.country_code, "city": loc.city},
    )
    await db.commit()
    return _location_out(loc)


@router.patch("/locations/{location_id}")
async def update_location(
    location_id: uuid.UUID, body: LocationPatch, db: Db, ctx: Ctx, client: Client, principal: Writer
) -> dict[str, Any]:
    loc = await _get_location(db, location_id, lock=True)
    changes = body.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(loc, key, dict(value) if key == "names" else value)
    if changes:
        _audit(db, principal, client, "admin.location_updated", "location", loc.id, changes)
    await db.commit()
    return next(x for x in await list_locations(db, ctx, principal) if x["id"] == str(loc.id))


# --- servers ------------------------------------------------------------------------------
@router.get("/servers")
async def list_servers(
    db: Db,
    ctx: Ctx,
    _: Reader,
    location_id: uuid.UUID | None = None,
    status: Annotated[ServerStatus | None, Query()] = None,
) -> list[dict[str, Any]]:
    stmt = select(Server).order_by(Server.hostname)
    if location_id is not None:
        stmt = stmt.where(Server.location_id == location_id)
    if status is not None:
        stmt = stmt.where(Server.status == status)
    servers = (await db.scalars(stmt)).all()
    peers = await _peer_counts(db, [s.id for s in servers])
    return [_server_out(ctx, s, peers.get(s.id, 0)) for s in servers]


@router.get("/servers/{server_id}")
async def get_server(server_id: uuid.UUID, db: Db, ctx: Ctx, _: Reader) -> dict[str, Any]:
    srv = await _get_server(db, server_id)
    return _server_out(ctx, srv, (await _peer_counts(db, [srv.id])).get(srv.id, 0))


@router.post("/servers", status_code=201)
async def create_server(
    body: ServerIn, db: Db, ctx: Ctx, client: Client, principal: Writer
) -> dict[str, Any]:
    """Register a node. The response carries its API token once: put it in the node's
    `/etc/globalvpn/agent.env` (`GVPN_NODE_TOKEN`) together with the server id."""
    await _get_location(db, body.location_id)
    token = new_node_token()
    srv = Server(
        hostname=body.hostname,
        location_id=body.location_id,
        public_ipv4=body.ipv4,
        public_ipv6=body.ipv6,
        endpoint_port=body.endpoint_port,
        wg_public_key=body.wg_public_key,
        max_peers=body.max_peers,
        tier=body.tier,
        status=body.status.value,
        agent_token_hash=ctx.tokens.hash_opaque(token),
    )
    db.add(srv)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "A server with this hostname or WireGuard key already exists.", code="server_exists"
        ) from exc
    _audit(
        db,
        principal,
        client,
        "admin.server_created",
        "server",
        srv.id,
        {"hostname": srv.hostname, "location_id": str(srv.location_id), "status": srv.status},
    )
    await db.commit()
    return {"server": _server_out(ctx, srv, 0), "token": token}


async def _release_assignments(db: Db, server_id: uuid.UUID) -> int:
    released = await db.execute(
        update(PeerAssignment)
        .where(
            PeerAssignment.server_id == server_id,
            PeerAssignment.state != AssignmentState.REMOVING,
        )
        .values(state=AssignmentState.REMOVING.value)
        .returning(PeerAssignment.id)
    )
    return len(released.all())


@router.patch("/servers/{server_id}")
async def update_server(
    server_id: uuid.UUID, body: ServerPatch, db: Db, ctx: Ctx, client: Client, principal: Writer
) -> dict[str, Any]:
    srv = await _get_server(db, server_id, lock=True)
    changes: dict[str, Any] = {}
    if body.location_id is not None and body.location_id != srv.location_id:
        await _get_location(db, body.location_id)
        changes["location_id"] = [str(srv.location_id), str(body.location_id)]
        srv.location_id = body.location_id
    if body.max_peers is not None and body.max_peers != srv.max_peers:
        changes["max_peers"] = [srv.max_peers, body.max_peers]
        srv.max_peers = body.max_peers
    if body.tier is not None and body.tier != srv.tier:
        changes["tier"] = [srv.tier, body.tier]
        srv.tier = body.tier
    if body.status is not None and body.status != srv.status:
        changes["status"] = [srv.status, body.status.value]
        srv.status = body.status.value
        if body.status == ServerStatus.DISABLED:
            changes["released_peers"] = await _release_assignments(db, srv.id)
            srv.revision += 1
    if changes:
        _audit(
            db,
            principal,
            client,
            "admin.server_updated",
            "server",
            srv.id,
            {"reason": body.reason, **changes},
        )
    await db.commit()
    return _server_out(ctx, srv, (await _peer_counts(db, [srv.id])).get(srv.id, 0))


@router.post("/servers/{server_id}/rotate-token")
async def rotate_token(
    server_id: uuid.UUID, body: ReasonIn, db: Db, ctx: Ctx, client: Client, principal: Writer
) -> dict[str, Any]:
    """New node API token (shown once); the old one stops working immediately."""
    srv = await _get_server(db, server_id, lock=True)
    token = new_node_token()
    srv.agent_token_hash = ctx.tokens.hash_opaque(token)
    details = {"reason": body.reason}
    _audit(db, principal, client, "admin.server_token_rotated", "server", srv.id, details)
    await db.commit()
    return {"server_id": str(srv.id), "token": token}
