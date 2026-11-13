"""User-facing VPN routes and the node-facing internal API."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import Client, Ctx, CurrentPrincipal, Db
from app.i18n import negotiate
from app.models import Server
from app.security.rate_limit import CONNECT_PER_ACCOUNT
from app.vpn import service as vpn

router = APIRouter(prefix="/vpn", tags=["vpn"])
# Mounted at /internal/v1 — NOT under /api, and never proxied publicly (see Caddyfile).
internal = APIRouter(prefix="/internal/v1", include_in_schema=False)


class LocationOut(BaseModel):
    id: uuid.UUID
    country_code: str
    city: str | None
    name: str
    servers: int


class ConnectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: uuid.UUID
    location_id: uuid.UUID | None = None


class ConnectOut(BaseModel):
    """Everything a client needs to build its WireGuard config locally (it adds its own
    private key — the platform never sees it)."""

    server_id: uuid.UUID
    location_id: uuid.UUID
    endpoint: str
    server_public_key: str
    addresses: list[str]
    dns: list[str]
    allowed_ips: list[str]
    persistent_keepalive: int


@router.get("/locations", response_model=list[LocationOut])
async def list_locations(
    request: Request,
    ctx: Ctx,
    db: Db,
    _: CurrentPrincipal,
    locale: Annotated[str | None, Query(max_length=8)] = None,
) -> list[LocationOut]:
    lang = negotiate(locale, request.headers.get("accept-language"))
    return [
        LocationOut(
            id=loc.id,
            country_code=loc.country_code,
            city=loc.city,
            name=loc.names.get(lang) or loc.names.get("en") or loc.country_code,
            servers=n,
        )
        for loc, n in await vpn.locations(ctx, db)
    ]


@router.post("/connect", response_model=ConnectOut)
async def connect(body: ConnectIn, principal: CurrentPrincipal, ctx: Ctx, db: Db) -> ConnectOut:
    """Assign the device to a node (least loaded in the location) and return its parameters.
    The node installs the peer within a couple of seconds."""
    await ctx.limiter.hit(CONNECT_PER_ACCOUNT, str(principal.user.id))
    info = await vpn.connect(
        ctx, db, user_id=principal.user.id, device_id=body.device_id, location_id=body.location_id
    )
    return ConnectOut(**info.__dict__)


class UsagePoint(BaseModel):
    date: str
    download: int
    upload: int


class UsageDevice(BaseModel):
    device_id: uuid.UUID
    name: str
    platform: str
    status: str
    download: int
    upload: int


class UsageOut(BaseModel):
    """Aggregate bytes per day for the user's devices (no destinations are ever recorded)."""

    days: int
    series: list[UsagePoint]
    total_download: int
    total_upload: int
    top_devices: list[UsageDevice]


@router.get("/usage", response_model=UsageOut)
async def usage(
    principal: CurrentPrincipal, db: Db, days: Annotated[int, Query(ge=1, le=90)] = 7
) -> dict[str, Any]:
    return await vpn.usage(db, principal.user.id, days)


class StatusOut(BaseModel):
    protected: bool  # this request came through our VPN
    via: str | None  # "tunnel" (a tunnel address) | "exit" (a node's public address) | None
    device_id: uuid.UUID | None  # which of your devices, when it can be told
    device_name: str | None


@router.get("/status", response_model=StatusOut)
async def status(principal: CurrentPrincipal, ctx: Ctx, db: Db, client: Client) -> dict[str, Any]:
    """Whether this device is connected through the VPN right now (judged by where the request
    comes from; nothing is stored). The Mini App polls it to show the "hidden in the jungle"
    effect while the tunnel is on."""
    return await vpn.protection_status(db, ctx, principal.user.id, client.ip)


# --- internal: node agent ---------------------------------------------------------------------
class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    wg_public_key: str | None = Field(default=None, min_length=44, max_length=44)
    applied_revision: int | None = None
    peers_total: int = Field(default=0, ge=0)
    peers_active: int = Field(default=0, ge=0)
    rx_bytes: int = Field(default=0, ge=0)
    tx_bytes: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list, max_length=50)
    agent_version: str | None = Field(default=None, max_length=32)
    handshakes: dict[str, int] = Field(default_factory=dict, max_length=20000)
    # public key → [rx_bytes, tx_bytes] cumulative WireGuard counters (server view)
    transfer: dict[str, list[int]] = Field(default_factory=dict, max_length=20000)


def _token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


@internal.get("/nodes/{server_id}/desired-state")
async def desired_state(
    server_id: uuid.UUID,
    ctx: Ctx,
    db: Db,
    authorization: Annotated[str | None, Header()] = None,
    since: Annotated[int | None, Query(ge=0)] = None,
) -> dict[str, Any]:
    """Long-poll: with `since`, waits (up to NODE_LONGPOLL_SECONDS) for a newer revision."""
    server = await vpn.authenticate_node(ctx, db, server_id, _token(authorization))
    if since is not None and since == server.revision:
        await vpn.wait_for_revision(ctx, db, server_id, since)  # ends the transaction
        refreshed = await db.get(Server, server_id, populate_existing=True)
        assert refreshed is not None
        server = refreshed
    return await vpn.desired_state(db, server)


@internal.post("/nodes/{server_id}/heartbeat")
async def heartbeat(
    server_id: uuid.UUID,
    body: HeartbeatIn,
    ctx: Ctx,
    db: Db,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    server = await vpn.authenticate_node(ctx, db, server_id, _token(authorization))
    await vpn.heartbeat(db, server, body.model_dump())
    return {"ok": True}
