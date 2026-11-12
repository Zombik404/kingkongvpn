from __future__ import annotations

import base64
import os
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.core.context import AppContext
from app.models import Device, User
from tests.helpers import PASSWORD, new_user


async def test_update_locale(client: AsyncClient, outbox: list[Any]) -> None:
    user = await new_user(client, outbox, "u1@example.com")
    r = await client.patch("/api/v1/users/me", headers=user.headers, json={"locale": "uk"})
    assert r.json()["locale"] == "uk"
    r = await client.patch("/api/v1/users/me", headers=user.headers, json={"locale": "fr"})
    assert r.status_code == 422
    r = await client.patch("/api/v1/users/me", headers=user.headers, json={"email": "x@y.z"})
    assert r.status_code == 422  # unknown fields are rejected


async def test_export(client: AsyncClient, outbox: list[Any]) -> None:
    user = await new_user(client, outbox, "u2@example.com")
    key = base64.b64encode(os.urandom(32)).decode()
    await client.post(
        "/api/v1/devices",
        headers=user.headers,
        json={"name": "pc", "platform": "windows", "public_key": key},
    )
    data = (await client.get("/api/v1/users/me/export", headers=user.headers)).json()
    assert data["account"]["email"] == "u2@example.com"
    assert data["devices"][0]["public_key"] == key
    assert len(data["sessions"]) == 1
    flat = str(data)
    assert "argon2" not in flat and "password" not in flat


async def test_delete_account(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    user = await new_user(client, outbox, "u3@example.com")
    await client.post(
        "/api/v1/devices",
        headers=user.headers,
        json={
            "name": "pc",
            "platform": "linux",
            "public_key": base64.b64encode(os.urandom(32)).decode(),
        },
    )
    r = await client.request(
        "DELETE",
        "/api/v1/users/me",
        headers=user.headers,
        json={"password": "wrong-password", "confirm": "DELETE"},
    )
    assert r.status_code == 401
    r = await client.request(
        "DELETE",
        "/api/v1/users/me",
        headers=user.headers,
        json={"password": PASSWORD, "confirm": "yes"},
    )
    assert r.status_code == 422
    r = await client.request(
        "DELETE",
        "/api/v1/users/me",
        headers=user.headers,
        json={"password": PASSWORD, "confirm": "DELETE"},
    )
    assert r.status_code == 204
    assert (await client.get("/api/v1/users/me", headers=user.headers)).status_code == 401
    row = await db.get(User, user.user_id)
    assert row.status == "deleted" and row.email is None and row.password_hash is None
    device = await db.scalar(select(Device))
    assert device.status == "revoked"
    # the address can sign up again as a brand-new account
    outbox.clear()
    await new_user(client, outbox, "u3@example.com")

    # purge job removes it after the retention window only
    from app.workers.tasks import purge_deleted_users

    async with ctx.sessionmaker() as s:
        assert await purge_deleted_users(ctx, s) == 0
    import datetime as dt

    from sqlalchemy import update

    await db.execute(
        update(User)
        .where(User.id == user.user_id)
        .values(deleted_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=31))
    )
    await db.commit()
    async with ctx.sessionmaker() as s:
        assert await purge_deleted_users(ctx, s) == 1
    db.expire_all()
    assert await db.get(User, user.user_id) is None
    assert await db.scalar(select(Device)) is None  # cascaded
