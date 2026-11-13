"""Staff API for locations and VPN servers, and the idle-peer cleanup (ROADMAP Phase 4)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.config import Settings
from app.core.context import AppContext
from app.models import AuditLog, Device, PeerAssignment
from app.models.base import utcnow
from app.workers.tasks import release_idle_peers
from tests.conftest import make_settings
from tests.helpers import new_user, staff
from tests.test_telegram_vpn import (
    BOT_TOKEN,
    beat,
    entitled_user_with_device,
    node_get,
    wg_key,
)

AV = "/api/v1/admin/vpn"


@pytest.fixture
def settings() -> Settings:
    return make_settings(
        telegram_bot_token=BOT_TOKEN, node_longpoll_seconds=1, public_web_url="https://vpn.test"
    )


async def _ops(client: AsyncClient, outbox: list[Any], db: Any, email: str) -> Any:
    return (await staff(client, outbox, db, email, ["ops"])).headers


async def _location(client: AsyncClient, h: dict[str, str], **body: Any) -> dict[str, Any]:
    r = await client.post(f"{AV}/locations", headers=h, json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _server(client: AsyncClient, h: dict[str, str], **body: Any) -> tuple[str, str]:
    r = await client.post(f"{AV}/servers", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()["server"]["id"], r.json()["token"]


async def test_permissions(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    user = await new_user(client, outbox, "plain@example.com")
    assert (await client.get(f"{AV}/servers", headers=user.headers)).status_code == 403
    support = await staff(client, outbox, db, "sup@example.com", ["support"])
    assert (await client.get(f"{AV}/servers", headers=support.headers)).status_code == 200
    r = await client.post(
        f"{AV}/locations", headers=support.headers, json={"country_code": "DE", "city": "Berlin"}
    )
    assert r.status_code == 403
    finance = await staff(client, outbox, db, "fin@example.com", ["finance"])
    assert (await client.get(f"{AV}/locations", headers=finance.headers)).status_code == 403


async def test_register_node_connect_and_health(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    h = await _ops(client, outbox, db, "ops1@example.com")
    loc = await _location(client, h, country_code="de", city="Frankfurt", sort_order=5)
    assert loc["country_code"] == "DE" and loc["names"] == {"en": "Frankfurt, DE"}
    assert loc["visible_to_users"] is False
    r = await client.post(
        f"{AV}/locations", headers=h, json={"country_code": "DE", "city": "Frankfurt"}
    )
    assert r.status_code == 409

    # validation: an address is required, hostnames are checked
    bad = {"hostname": "de-fra-1", "location_id": loc["id"]}
    assert (await client.post(f"{AV}/servers", headers=h, json=bad)).status_code == 422
    bad = {"hostname": "bad host!", "location_id": loc["id"], "ipv4": "203.0.113.5"}
    assert (await client.post(f"{AV}/servers", headers=h, json=bad)).status_code == 422

    sid, token = await _server(
        client, h, hostname="DE-FRA-1", location_id=loc["id"], ipv4="203.0.113.5", max_peers=2
    )
    dup = {"hostname": "de-fra-1", "location_id": loc["id"], "ipv4": "203.0.113.6"}
    assert (await client.post(f"{AV}/servers", headers=h, json=dup)).status_code == 409

    srv = (await client.get(f"{AV}/servers/{sid}", headers=h)).json()
    assert srv["hostname"] == "de-fra-1" and srv["status"] == "active"
    assert srv["accepting"] is False and srv["heartbeat_fresh"] is False and srv["has_token"]

    # the node uses the token; its key arrives with the first heartbeat
    key = wg_key()
    assert (await node_get(client, sid, token)).status_code == 200
    await beat(client, sid, token, wg_public_key=key, applied_revision=0, agent_version="0.3.0")
    srv = (await client.get(f"{AV}/servers/{sid}", headers=h)).json()
    assert srv["accepting"] is True and srv["wg_public_key"] == key
    assert srv["in_sync"] is True and srv["agent_version"] == "0.3.0"
    locs = (await client.get(f"{AV}/locations", headers=h)).json()
    assert locs[0]["servers"] == 1 and locs[0]["healthy_servers"] == 1
    assert locs[0]["visible_to_users"] is True

    user, dev = await entitled_user_with_device(client, outbox, db, "vpnuser@example.com")
    r = await client.post(
        "/api/v1/vpn/connect", headers=user.headers, json={"device_id": dev["id"]}
    )
    assert r.status_code == 200 and r.json()["server_public_key"] == key
    srv = (await client.get(f"{AV}/servers/{sid}", headers=h)).json()
    assert srv["peers"] == 1 and srv["load"] == 0.5 and srv["in_sync"] is False

    # hiding the location hides it from users
    r = await client.patch(f"{AV}/locations/{loc['id']}", headers=h, json={"enabled": False})
    assert r.json()["enabled"] is False and r.json()["visible_to_users"] is False
    assert (await client.get("/api/v1/vpn/locations", headers=user.headers)).json() == []
    await client.patch(
        f"{AV}/locations/{loc['id']}",
        headers=h,
        json={"enabled": True, "names": {"en": "Frankfurt", "ru": "Франкфурт"}},
    )
    names = (await client.get("/api/v1/vpn/locations", headers=user.headers)).json()
    assert len(names) == 1

    actions = set((await db.scalars(select(AuditLog.action))).all())
    assert {"admin.location_created", "admin.location_updated", "admin.server_created"} <= actions
    # the token never lands in the audit log
    details = " ".join(str(d) for d in (await db.scalars(select(AuditLog.details))).all())
    assert token not in details


async def test_drain_disable_and_rotate(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    h = await _ops(client, outbox, db, "ops2@example.com")
    loc = await _location(client, h, country_code="NL", city="Amsterdam")
    sid, token = await _server(
        client, h, hostname="nl-ams-1", location_id=loc["id"], ipv4="198.51.100.7"
    )
    await beat(client, sid, token, wg_public_key=wg_key())
    user, dev = await entitled_user_with_device(client, outbox, db, "drain@example.com")
    connect = {"device_id": dev["id"]}
    assert (
        await client.post("/api/v1/vpn/connect", headers=user.headers, json=connect)
    ).status_code == 200

    # a reason is required for every change
    r = await client.patch(f"{AV}/servers/{sid}", headers=h, json={"status": "draining"})
    assert r.status_code == 422
    r = await client.patch(
        f"{AV}/servers/{sid}", headers=h, json={"status": "draining", "reason": "kernel update"}
    )
    assert r.json()["status"] == "draining" and r.json()["accepting"] is False
    # draining: existing peer stays on the node, but nobody new gets in
    assert len((await node_get(client, sid, token)).json()["peers"]) == 1
    u2, d2 = await entitled_user_with_device(client, outbox, db, "drain2@example.com")
    r = await client.post("/api/v1/vpn/connect", headers=u2.headers, json={"device_id": d2["id"]})
    assert r.status_code == 503

    # rotating the token cuts the old one off at once
    r = await client.post(f"{AV}/servers/{sid}/rotate-token", headers=h, json={"reason": "leak"})
    new_token = r.json()["token"]
    assert new_token != token
    assert (await node_get(client, sid, token)).status_code == 401
    assert (await node_get(client, sid, new_token)).status_code == 200

    # disabling refuses the node and releases its peers
    r = await client.patch(
        f"{AV}/servers/{sid}", headers=h, json={"status": "disabled", "reason": "decommission"}
    )
    assert r.json()["status"] == "disabled" and r.json()["peers"] == 0
    assert (await node_get(client, sid, new_token)).status_code == 401
    states = (await db.scalars(select(PeerAssignment.state))).all()
    assert states == ["removing"]
    row = await db.scalar(
        select(AuditLog)
        .where(AuditLog.action == "admin.server_updated")
        .order_by(AuditLog.id.desc())
    )
    assert row.details["status"] == ["draining", "disabled"] and row.details["released_peers"] == 1


async def test_idle_peers_are_released_only_when_switched_on(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    h = await _ops(client, outbox, db, "ops3@example.com")
    loc = await _location(client, h, country_code="FI", city="Helsinki")
    sid, token = await _server(
        client, h, hostname="fi-hel-1", location_id=loc["id"], ipv4="198.51.100.9"
    )
    await beat(client, sid, token, wg_public_key=wg_key())
    idle_user, idle_dev = await entitled_user_with_device(client, outbox, db, "idle@example.com")
    busy_user, busy_dev = await entitled_user_with_device(client, outbox, db, "busy@example.com")
    new_user_, new_dev = await entitled_user_with_device(client, outbox, db, "new@example.com")
    for u, d in ((idle_user, idle_dev), (busy_user, busy_dev), (new_user_, new_dev)):
        r = await client.post("/api/v1/vpn/connect", headers=u.headers, json={"device_id": d["id"]})
        assert r.status_code == 200
    long_ago = utcnow() - dt.timedelta(hours=50)
    await db.execute(
        update(PeerAssignment)
        .where(PeerAssignment.device_id.in_([idle_dev["id"], busy_dev["id"]]))
        .values(assigned_at=long_ago)
    )
    await db.execute(
        update(Device).where(Device.id == idle_dev["id"]).values(last_handshake_at=long_ago)
    )
    await db.execute(
        update(Device).where(Device.id == busy_dev["id"]).values(last_handshake_at=utcnow())
    )
    await db.commit()
    rev = (await node_get(client, sid, token)).json()["revision"]

    # off by default (fixed configs in the WireGuard app don't call us before connecting)
    assert await release_idle_peers(ctx, db) == 0
    boss = await staff(client, outbox, db, "boss@example.com", ["superadmin"])
    r = await client.put(
        "/api/v1/admin/settings/peers.idle_ttl_hours", headers=boss.headers, json={"value": 24}
    )
    assert r.status_code == 200, r.text
    assert await release_idle_peers(ctx, db) == 1  # only the idle one; the new one has time
    state = (await node_get(client, sid, token)).json()
    assert state["revision"] > rev
    assert {p["public_key"] for p in state["peers"]} == {
        busy_dev["public_key"],
        new_dev["public_key"],
    }
    assert await release_idle_peers(ctx, db) == 0  # nothing left to release
    # tapping Connect again puts the device back
    r = await client.post(
        "/api/v1/vpn/connect", headers=idle_user.headers, json={"device_id": idle_dev["id"]}
    )
    assert r.status_code == 200
    assert len((await node_get(client, sid, token)).json()["peers"]) == 3
