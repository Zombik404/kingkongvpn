from __future__ import annotations

import asyncio
import base64
import ipaddress
import os
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.context import AppContext
from app.models import Device, Location, PeerAssignment, Plan, Server
from tests.helpers import new_user

API = "/api/v1/devices"


def wg_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


async def give_plan(client: AsyncClient, db: Any, user_id: str, device_limit: int) -> None:
    from app.models.enums import ActorType, Provider
    from app.subscriptions import service as subs

    plan = Plan(code=f"p{device_limit}", names={"en": "Test"}, device_limit=device_limit)
    db.add(plan)
    await db.flush()
    await subs.grant_days(
        db,
        user_id=user_id,
        plan=plan,
        days=30,
        provider=Provider.ADMIN,
        actor_id=None,
        actor_type=ActorType.SYSTEM,
        ip=None,
    )
    await db.commit()


async def test_register_device_allocates_addresses(
    client: AsyncClient, outbox: list[Any], ctx: AppContext
) -> None:
    user = await new_user(client, outbox, "dev1@example.com")
    key = wg_key()
    r = await client.post(
        API,
        headers=user.headers,
        json={"name": "  My   Phone ", "platform": "android", "public_key": key},
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["name"] == "My Phone"
    assert d["public_key"] == key
    pool = ctx.address_pool
    assert ipaddress.ip_address(d["ipv4"]) == pool.ipv4.network_address + pool.reserved
    assert ipaddress.ip_address(d["ipv6"]) == pool.ipv6.network_address + pool.reserved
    assert ipaddress.ip_address(d["ipv4"]) in pool.ipv4
    assert "private" not in r.text.lower()


@pytest.mark.parametrize(
    "key",
    [
        "short",
        base64.b64encode(os.urandom(31)).decode() + "A",  # wrong length after decode
        base64.b64encode(bytes(32)).decode(),  # all-zero key
        "!" * 43 + "=",  # not base64
        base64.b64encode(os.urandom(33)).decode()[:44],
    ],
)
async def test_invalid_public_keys_rejected(
    client: AsyncClient, outbox: list[Any], key: str
) -> None:
    user = await new_user(client, outbox, "dev2@example.com")
    r = await client.post(
        API, headers=user.headers, json={"name": "x", "platform": "ios", "public_key": key}
    )
    assert r.status_code == 422


async def test_duplicate_key_rejected_even_across_users(
    client: AsyncClient, outbox: list[Any]
) -> None:
    a = await new_user(client, outbox, "dev3@example.com")
    b = await new_user(client, outbox, "dev4@example.com")
    key = wg_key()
    assert (
        await client.post(
            API, headers=a.headers, json={"name": "a", "platform": "linux", "public_key": key}
        )
    ).status_code == 201
    r = await client.post(
        API, headers=b.headers, json={"name": "b", "platform": "linux", "public_key": key}
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "public_key_in_use"


async def test_device_limit_without_and_with_plan(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    user = await new_user(client, outbox, "dev5@example.com")
    body = {"name": "d", "platform": "windows"}
    assert (
        await client.post(API, headers=user.headers, json={**body, "public_key": wg_key()})
    ).status_code == 201
    r = await client.post(API, headers=user.headers, json={**body, "public_key": wg_key()})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "device_limit_reached"
    assert r.json()["error"]["details"] == {"limit": 1}
    await give_plan(client, db, user.user_id, device_limit=3)
    for _ in range(2):
        assert (
            await client.post(API, headers=user.headers, json={**body, "public_key": wg_key()})
        ).status_code == 201
    r = await client.post(API, headers=user.headers, json={**body, "public_key": wg_key()})
    assert r.status_code == 409
    listing = (await client.get(API, headers=user.headers)).json()
    assert listing["limit"] == 3
    assert listing["active_count"] == 3


async def test_concurrent_registrations_respect_limit(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    user = await new_user(client, outbox, "dev6@example.com")
    await give_plan(client, db, user.user_id, device_limit=3)
    results = await asyncio.gather(
        *[
            client.post(
                API,
                headers=user.headers,
                json={"name": f"d{i}", "platform": "macos", "public_key": wg_key()},
            )
            for i in range(8)
        ]
    )
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 3
    assert codes.count(409) == 5
    ips = {r.json()["ipv4"] for r in results if r.status_code == 201}
    assert len(ips) == 3


async def test_rename_revoke_and_isolation(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    a = await new_user(client, outbox, "dev7@example.com")
    b = await new_user(client, outbox, "dev8@example.com")
    dev = (
        await client.post(
            API,
            headers=a.headers,
            json={"name": "laptop", "platform": "linux", "public_key": wg_key()},
        )
    ).json()
    # b can neither see, rename nor revoke a's device
    assert (
        await client.patch(f"{API}/{dev['id']}", headers=b.headers, json={"name": "pwned"})
    ).status_code == 404
    assert (await client.delete(f"{API}/{dev['id']}", headers=b.headers)).status_code == 404
    assert (await client.get(API, headers=b.headers)).json()["devices"] == []

    r = await client.patch(f"{API}/{dev['id']}", headers=a.headers, json={"name": "work laptop"})
    assert r.json()["name"] == "work laptop"
    r = await client.patch(f"{API}/{dev['id']}", headers=a.headers, json={"name": "bad\x00name"})
    assert r.status_code == 422

    # an assignment on a node is marked for removal and the node revision bumps
    loc = Location(country_code="DE", city="Frankfurt")
    db.add(loc)
    await db.flush()
    server = Server(location_id=loc.id, hostname="de-fra-1.test", status="active")
    db.add(server)
    await db.flush()
    db.add(PeerAssignment(device_id=dev["id"], server_id=server.id, state="active"))
    server_id = server.id
    await db.commit()

    assert (await client.delete(f"{API}/{dev['id']}", headers=a.headers)).status_code == 204
    assert (await client.delete(f"{API}/{dev['id']}", headers=a.headers)).status_code == 204
    db.expire_all()
    assignment = await db.scalar(select(PeerAssignment))
    assert assignment.state == "removing"
    assert (await db.get(Server, server_id)).revision == 1
    listing = (await client.get(API, headers=a.headers)).json()
    assert listing["devices"] == []
    full = (await client.get(f"{API}?include_revoked=true", headers=a.headers)).json()
    assert full["devices"][0]["status"] == "revoked"
    r = await client.patch(f"{API}/{dev['id']}", headers=a.headers, json={"name": "x"})
    assert r.json()["error"]["code"] == "device_revoked"
    # revoked device frees a slot (limit 1 without plan)
    assert (
        await client.post(
            API,
            headers=a.headers,
            json={"name": "new", "platform": "linux", "public_key": wg_key()},
        )
    ).status_code == 201
    # but its key is burned forever
    r = await client.post(
        API,
        headers=a.headers,
        json={"name": "again", "platform": "linux", "public_key": dev["public_key"]},
    )
    assert r.status_code == 409
    rows = (await db.scalars(select(Device))).all()
    assert len({str(d.ipv4) for d in rows}) == len(rows)
