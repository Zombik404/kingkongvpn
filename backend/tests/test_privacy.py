"""User data protection: deletion and export for Telegram accounts, abuse limits, headers."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.config import Settings
from app.core.context import AppContext
from app.models import Device, GameProfile, User
from app.models.base import utcnow
from app.vpn.service import release_revoked_addresses
from tests.conftest import make_settings
from tests.test_telegram_vpn import BOT_TOKEN, init_data, tg_login, wg_key


@pytest.fixture
def settings() -> Settings:
    return make_settings(telegram_bot_token=BOT_TOKEN, public_web_url="https://vpn.test")


async def _uid(client: AsyncClient, h: dict[str, str]) -> Any:
    return (await client.get("/api/v1/users/me", headers=h)).json()["id"]


async def test_telegram_account_can_be_deleted_with_fresh_init_data(
    client: AsyncClient, db: Any
) -> None:
    h = await tg_login(client, 5001)
    uid = await _uid(client, h)
    other = await tg_login(client, 5002)
    db.add(
        GameProfile(
            user_id=uid,
            nickname="Anna Ivanova",
            best_win=500,
            best_win_stake=500,
            best_win_at=utcnow(),
        )
    )
    await db.commit()
    board = (await client.get("/api/v1/games/leaderboard", headers=other)).json()
    assert [r["nickname"] for r in board["top"]] == ["Anna Ivanova"]

    url = "/api/v1/users/me"
    # no password on a Telegram account: proof must come from Telegram, for the same person
    for body in (
        {"confirm": "DELETE"},
        {"confirm": "DELETE", "password": "guess"},
        {"confirm": "DELETE", "telegram_init_data": init_data(5002)},
        {"confirm": "DELETE", "telegram_init_data": init_data(5001, age=dt.timedelta(days=3))},
        {"confirm": "DELETE", "telegram_init_data": init_data(5001, token="1:other-bot")},
    ):
        r = await client.request("DELETE", url, headers=h, json=body)
        assert r.status_code == 401, (body, r.text)
    r = await client.request(
        "DELETE", url, headers=h, json={"confirm": "DELETE", "telegram_init_data": init_data(5001)}
    )
    assert r.status_code == 204, r.text

    user = await db.get(User, uid)
    await db.refresh(user)
    assert user.status == "deleted" and user.telegram_id is None and user.referral_code is None
    profile = await db.get(GameProfile, uid)
    await db.refresh(profile)
    assert profile.nickname == "Deleted player"
    board = (await client.get("/api/v1/games/leaderboard", headers=other)).json()
    assert board["top"] == []  # gone from the board at once
    assert (await client.get(url, headers=h)).status_code == 401  # signed out everywhere
    # opening the Mini App again starts a brand-new, empty account
    h2 = await tg_login(client, 5001)
    assert await _uid(client, h2) != uid


async def test_export_covers_everything(client: AsyncClient, db: Any) -> None:
    h = await tg_login(client, 5101)
    uid = await _uid(client, h)
    await client.get("/api/v1/referrals", headers=h)  # creates the referral code
    db.add(GameProfile(user_id=uid, nickname="Kong", rounds=3, wins=2))
    await db.commit()
    r = await client.post(
        "/api/v1/devices",
        headers=h,
        json={"name": "phone", "platform": "android", "public_key": wg_key()},
    )
    assert r.status_code == 201, r.text
    data = (await client.get("/api/v1/users/me/export", headers=h)).json()
    assert data["account"]["telegram_linked"] is True
    assert len(data["devices"]) == 1
    assert data["games"]["profile"]["nickname"] == "Kong" and data["games"]["profile"]["wins"] == 2
    assert data["games"]["bonus_hours"] == 0 and data["games"]["bonus_ledger"] == []
    assert data["referrals"]["invited_users"] == 0
    assert "traffic_daily" in data and "notification_preferences" in data
    # nothing secret in it
    blob = str(data)
    assert "password" not in blob and "totp" not in blob.lower()
    for _ in range(4):
        await client.get("/api/v1/users/me/export", headers=h)
    assert (await client.get("/api/v1/users/me/export", headers=h)).status_code == 429


async def test_device_churn_is_limited_and_old_addresses_come_back(
    client: AsyncClient, db: Any, ctx: AppContext
) -> None:
    h = await tg_login(client, 5201)
    ids = []
    for _ in range(10):  # register + revoke, as an attacker draining the address pool would
        r = await client.post(
            "/api/v1/devices",
            headers=h,
            json={"name": "x", "platform": "android", "public_key": wg_key()},
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
        assert (await client.delete(f"/api/v1/devices/{ids[-1]}", headers=h)).status_code == 204
    r = await client.post(
        "/api/v1/devices",
        headers=h,
        json={"name": "x", "platform": "android", "public_key": wg_key()},
    )
    assert r.status_code == 429

    await db.execute(
        update(Device)
        .where(Device.id.in_(ids[:4]))
        .values(revoked_at=utcnow() - dt.timedelta(days=31))
    )
    await db.commit()
    assert await release_revoked_addresses(db, dt.timedelta(days=30)) == 4
    rows = (await db.execute(select(Device.id, Device.ipv4).order_by(Device.created_at))).all()
    freed = {str(i) for i, ip in rows if ip is None}
    assert freed == set(ids[:4])
    assert await release_revoked_addresses(db, dt.timedelta(days=30)) == 0


async def test_api_security_headers(client: AsyncClient) -> None:
    h = await tg_login(client, 5301)
    r = await client.get("/api/v1/users/me", headers=h)
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY"
    assert "camera=()" in r.headers["permissions-policy"]
