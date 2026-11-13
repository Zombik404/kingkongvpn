from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import os
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.config import Settings
from app.core.context import AppContext
from app.core.errors import NotAuthenticated
from app.models import PeerAssignment, PromoCode, Server, Subscription, User
from app.models.base import utcnow
from app.notifications.telegram import MemoryTelegramDispatcher, TelegramJob, TelegramSendError
from app.security.telegram import sign_init_data, validate_init_data
from tests.conftest import make_settings
from tests.helpers import new_user

BOT_TOKEN = "123456:TEST-bot-token-not-real"
DAY = dt.timedelta(days=1)


@pytest.fixture
def settings() -> Settings:
    return make_settings(
        telegram_bot_token=BOT_TOKEN, node_longpoll_seconds=3, public_web_url="https://vpn.test"
    )


def init_data(
    tg_id: int = 777,
    *,
    lang: str = "ru",
    age: dt.timedelta = dt.timedelta(0),
    token: str = BOT_TOKEN,
    **extra: Any,
) -> str:
    user = {"id": tg_id, "first_name": "Ann", "language_code": lang, **extra}
    fields = {
        "auth_date": str(int((utcnow() - age).timestamp())),
        "query_id": "AAE",
        "user": json.dumps(user, separators=(",", ":")),
    }
    return sign_init_data(fields, token)


async def tg_login(client: AsyncClient, tg_id: int = 777, **kw: Any) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/telegram/webapp", json={"init_data": init_data(tg_id, **kw)}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def wg_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


# --- initData ----------------------------------------------------------------------------------
def test_init_data_validation() -> None:
    now = utcnow()
    age = dt.timedelta(days=1)
    tg = validate_init_data(init_data(42), BOT_TOKEN, max_age=age, now=now)
    assert tg.id == 42 and tg.language_code == "ru"
    bad = [
        init_data(42, token="other:token"),  # signed by another bot
        init_data(42, age=dt.timedelta(days=2)),  # too old
        init_data(42, is_bot=True),
        init_data(42) + "&user=%7B%7D",  # duplicate key
        init_data(42).replace("hash=", "hash=0"),
        "",
    ]
    for data in bad:
        with pytest.raises(NotAuthenticated):
            validate_init_data(data, BOT_TOKEN, max_age=age, now=now)
    with pytest.raises(NotAuthenticated):
        validate_init_data(init_data(42), "", max_age=age, now=now)


async def test_webapp_login_creates_and_reuses_account(client: AsyncClient, db: Any) -> None:
    h1 = await tg_login(client, 1001, lang="uk")
    h2 = await tg_login(client, 1001)
    me1 = (await client.get("/api/v1/users/me", headers=h1)).json()
    me2 = (await client.get("/api/v1/users/me", headers=h2)).json()
    assert me1["id"] == me2["id"] and me1["has_telegram"] and me1["email"] is None
    assert me1["locale"] == "uk"
    r = await client.post(
        "/api/v1/auth/telegram/webapp", json={"init_data": init_data(1001, token="evil:token")}
    )
    assert r.status_code == 401
    await db.execute(update(User).where(User.telegram_id == 1001).values(roles=["support"]))
    await db.commit()
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data(1001)})
    assert r.status_code == 401  # staff must use password + TOTP
    await db.execute(
        update(User).where(User.telegram_id == 1001).values(roles=[], status="suspended")
    )
    await db.commit()
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data(1001)})
    assert r.json()["error"]["code"] == "account_suspended"


# --- invite-only closed test ------------------------------------------------------------------
async def test_invite_gate_and_trial_for_telegram_users(
    client: AsyncClient, db: Any, ctx: AppContext
) -> None:
    from app.cli import bootstrap_catalog, create_invites, set_setting

    await bootstrap_catalog()
    assert await set_setting("trial.enabled", "true") == 0
    h = await tg_login(client, 2001)
    r = await client.post("/api/v1/subscription/trial", headers=h)
    assert r.status_code == 201, r.text  # no email needed for Telegram accounts

    assert await set_setting("access.invite_only", "true") == 0
    assert await set_setting("access.invite_only", "maybe") == 1
    h2 = await tg_login(client, 2002)
    r = await client.post("/api/v1/subscription/trial", headers=h2)
    assert r.status_code == 409 and "invite" in r.json()["error"]["message"]

    assert await create_invites(3, 30, "standard", 60) == 0
    assert await create_invites(1, 30, "nope", 60) == 1
    codes = (await db.scalars(select(PromoCode.code))).all()
    assert len(codes) == 3 and all(c.startswith("INV-") and len(c) == 13 for c in codes)
    r = await client.post("/api/v1/promo/redeem", headers=h2, json={"code": codes[0]})
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert r.json()["plan_code"] == "standard"
    h3 = await tg_login(client, 2003)
    r = await client.post("/api/v1/promo/redeem", headers=h3, json={"code": codes[0]})
    assert r.status_code == 422  # single use
    price_id = (await client.get("/api/v1/plans")).json()[0]["prices"][0]["id"]
    r = await client.post("/api/v1/payments/checkout", headers=h3, json={"price_id": price_id})
    # without an invite: closed (or payments simply disabled in this test setup)
    assert r.status_code in (403, 503)


# --- VPN: nodes, connect, desired state -------------------------------------------------------
async def register_node(
    hostname: str = "de-fra-1",
    country: str = "DE",
    city: str = "Frankfurt",
    ipv4: str = "203.0.113.5",
) -> tuple[str, str]:
    import contextlib
    import io

    from app.cli import node_register

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = await node_register(hostname, country, city, ipv4, None, 51820, wg_key(), 1500)
    assert rc == 0
    data = json.loads(out.getvalue())
    return data["server_id"], data["token"]


async def node_get(client: AsyncClient, sid: str, token: str, since: int | None = None) -> Any:
    url = f"/internal/v1/nodes/{sid}/desired-state" + (
        f"?since={since}" if since is not None else ""
    )
    return await client.get(url, headers={"Authorization": f"Bearer {token}"})


async def beat(client: AsyncClient, sid: str, token: str, **body: Any) -> Any:
    return await client.post(
        f"/internal/v1/nodes/{sid}/heartbeat",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )


async def entitled_user_with_device(
    client: AsyncClient, outbox: list[Any], db: Any, email: str
) -> tuple[Any, dict[str, Any]]:
    from app.cli import bootstrap_catalog
    from app.models.enums import ActorType, Provider
    from app.subscriptions import service as subs

    await bootstrap_catalog()
    user = await new_user(client, outbox, email)
    from app.models import Plan

    plan = await db.scalar(select(Plan).where(Plan.code == "standard"))
    await subs.grant_days(
        db,
        user_id=user.user_id,
        plan=plan,
        days=30,
        provider=Provider.ADMIN,
        actor_id=None,
        actor_type=ActorType.SYSTEM,
        ip=None,
    )
    await db.commit()
    dev = (
        await client.post(
            "/api/v1/devices",
            headers=user.headers,
            json={"name": "phone", "platform": "android", "public_key": wg_key()},
        )
    ).json()
    return user, dev


async def test_node_auth_and_heartbeat(client: AsyncClient, db: Any) -> None:
    sid, token = await register_node()
    assert (await node_get(client, sid, "wrong-token")).status_code == 401
    assert (
        await node_get(client, "00000000-0000-7000-8000-000000000000", token)
    ).status_code == 401
    r = await node_get(client, sid, token)
    assert r.status_code == 200 and r.json()["peers"] == []
    r = await beat(client, sid, token, peers_total=0, peers_active=0, agent_version="0.2.0")
    assert r.json() == {"ok": True}
    server = await db.get(Server, sid)
    assert server.last_heartbeat_at is not None
    assert server.last_metrics["agent_version"] == "0.2.0"
    sid2, token2 = await register_node()  # re-register rotates the token
    assert sid2 == sid
    assert (await node_get(client, sid, token)).status_code == 401
    assert (await node_get(client, sid, token2)).status_code == 200


async def test_connect_flow_and_desired_state(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    sid, token = await register_node()
    user, dev = await entitled_user_with_device(client, outbox, db, "vpn1@example.com")
    # no heartbeat yet → node not eligible
    r = await client.post(
        "/api/v1/vpn/connect", headers=user.headers, json={"device_id": dev["id"]}
    )
    assert r.status_code == 503
    assert (await client.get("/api/v1/vpn/locations", headers=user.headers)).json() == []
    await beat(client, sid, token)
    locs = (await client.get("/api/v1/vpn/locations", headers=user.headers)).json()
    assert [(loc["country_code"], loc["servers"]) for loc in locs] == [("DE", 1)]
    r = await client.post(
        "/api/v1/vpn/connect",
        headers=user.headers,
        json={"device_id": dev["id"], "location_id": locs[0]["id"]},
    )
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["endpoint"] == "203.0.113.5:51820"
    assert info["addresses"] == [f"{dev['ipv4']}/32", f"{dev['ipv6']}/128"]
    assert info["allowed_ips"] == ["0.0.0.0/0", "::/0"]
    assert info["dns"] == ["1.1.1.1", "2606:4700:4700::1111"]
    state = (await node_get(client, sid, token)).json()
    assert state["peers"] == [
        {
            "public_key": dev["public_key"],
            "allowed_ips": [f"{dev['ipv4']}/32", f"{dev['ipv6']}/128"],
        }
    ]
    rev = state["revision"]
    # connecting again is idempotent (no revision bump)
    await client.post("/api/v1/vpn/connect", headers=user.headers, json={"device_id": dev["id"]})
    assert (await node_get(client, sid, token)).json()["revision"] == rev
    # handshake reported → "last connected" at hour resolution
    await beat(client, sid, token, handshakes={dev["public_key"]: int(utcnow().timestamp())})
    listing = (await client.get("/api/v1/devices", headers=user.headers)).json()["devices"]
    assert (
        listing[0]["last_handshake_at"].endswith(":00:00Z")
        or ":00:00" in listing[0]["last_handshake_at"]
    )
    # revoking the device removes it from the node and bumps the revision
    await client.delete(f"/api/v1/devices/{dev['id']}", headers=user.headers)
    state2 = (await node_get(client, sid, token)).json()
    assert state2["peers"] == [] and state2["revision"] > rev


async def test_expired_user_is_dropped_even_without_bump(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    sid, token = await register_node()
    await beat(client, sid, token)
    user, dev = await entitled_user_with_device(client, outbox, db, "vpn2@example.com")
    await client.post("/api/v1/vpn/connect", headers=user.headers, json={"device_id": dev["id"]})
    assert len((await node_get(client, sid, token)).json()["peers"]) == 1
    await db.execute(update(Subscription).values(status="expired", ended_at=utcnow()))
    await db.commit()
    assert (await node_get(client, sid, token)).json()["peers"] == []
    r = await client.post(
        "/api/v1/vpn/connect", headers=user.headers, json={"device_id": dev["id"]}
    )
    assert r.status_code == 402


async def test_switching_location_moves_the_peer(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    de, de_tok = await register_node()
    nl, nl_tok = await register_node("nl-ams-1", "NL", "Amsterdam", "198.51.100.7")
    for sid, tok in ((de, de_tok), (nl, nl_tok)):
        await beat(client, sid, tok)
    user, dev = await entitled_user_with_device(client, outbox, db, "vpn3@example.com")
    locs = {
        loc["country_code"]: loc["id"]
        for loc in (await client.get("/api/v1/vpn/locations", headers=user.headers)).json()
    }
    await client.post(
        "/api/v1/vpn/connect",
        headers=user.headers,
        json={"device_id": dev["id"], "location_id": locs["DE"]},
    )
    r = await client.post(
        "/api/v1/vpn/connect",
        headers=user.headers,
        json={"device_id": dev["id"], "location_id": locs["NL"]},
    )
    assert r.json()["endpoint"].startswith("198.51.100.7")
    assert (await node_get(client, de, de_tok)).json()["peers"] == []
    assert len((await node_get(client, nl, nl_tok)).json()["peers"]) == 1
    states = sorted(a.state for a in (await db.scalars(select(PeerAssignment))).all())
    assert states == ["active", "removing"]
    other = await new_user(client, outbox, "vpn4@example.com")
    r = await client.post(
        "/api/v1/vpn/connect", headers=other.headers, json={"device_id": dev["id"]}
    )
    assert r.status_code == 404  # someone else's device


async def test_long_poll_wakes_on_change(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    sid, token = await register_node()
    await beat(client, sid, token)
    user, dev = await entitled_user_with_device(client, outbox, db, "vpn5@example.com")
    rev = (await node_get(client, sid, token)).json()["revision"]

    async def change_soon() -> None:
        await asyncio.sleep(0.5)
        await client.post(
            "/api/v1/vpn/connect", headers=user.headers, json={"device_id": dev["id"]}
        )

    loop = asyncio.get_running_loop()
    started = loop.time()
    r, _ = await asyncio.gather(node_get(client, sid, token, since=rev), change_soon())
    elapsed = loop.time() - started
    assert r.json()["revision"] > rev and len(r.json()["peers"]) == 1
    assert elapsed < 2.9  # returned on the change, not at the 3 s timeout
    started = loop.time()
    r = await node_get(client, sid, token, since=r.json()["revision"])
    assert loop.time() - started >= 2.5  # nothing changed → waits for the timeout


async def test_stale_node_is_not_used(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    sid, token = await register_node()
    await beat(client, sid, token)
    await db.execute(update(Server).values(last_heartbeat_at=utcnow() - dt.timedelta(minutes=5)))
    await db.commit()
    user, dev = await entitled_user_with_device(client, outbox, db, "vpn6@example.com")
    r = await client.post(
        "/api/v1/vpn/connect", headers=user.headers, json={"device_id": dev["id"]}
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "no_server_available"


# --- Telegram notifications -------------------------------------------------------------------
async def test_telegram_users_get_notifications(
    client: AsyncClient, db: Any, ctx: AppContext
) -> None:
    from app.cli import bootstrap_catalog
    from app.subscriptions import service as subs

    await bootstrap_catalog()
    await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data(3001)})
    from app.services import settings as settings_service

    await settings_service.set_value(db, "trial.enabled", True, actor_id=None)
    await db.commit()
    h = await tg_login(client, 3001)
    await client.post("/api/v1/subscription/trial", headers=h)
    async with ctx.sessionmaker() as s:
        await subs.process_due(ctx, s, now=utcnow() + 4 * DAY)
    assert isinstance(ctx.telegram, MemoryTelegramDispatcher)
    [msg] = ctx.telegram.sent
    assert msg.chat_id == 3001
    assert "закончился" in msg.text  # Russian (from language_code)
    assert msg.webapp_url == "https://vpn.test/app/"


def test_telegram_send_sync_statuses() -> None:
    from app.notifications.telegram import send_sync

    s = make_settings(telegram_bot_token=BOT_TOKEN)
    seen: list[dict[str, Any]] = []

    def run(status: int) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            seen.append(json.loads(req.content))
            assert req.url.path == f"/bot{BOT_TOKEN}/sendMessage"
            return httpx.Response(status, json={"ok": status == 200})

        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            send_sync(TelegramJob(5, "hi", "Open", "https://vpn.test/app/"), s, c)

    run(200)
    assert seen[0]["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"].endswith("/app/")
    run(403)  # user blocked the bot: not an error
    run(400)  # logged only
    for status in (429, 502):
        with pytest.raises(TelegramSendError):
            run(status)
    send_sync(TelegramJob(5, "hi"), make_settings(telegram_bot_token=""))  # no token: no-op


async def test_cleanup_purges_old_removed_assignments(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    from app.workers.tasks import cleanup_tokens

    sid, token = await register_node()
    await beat(client, sid, token)
    user, dev = await entitled_user_with_device(client, outbox, db, "vpn7@example.com")
    await client.post("/api/v1/vpn/connect", headers=user.headers, json={"device_id": dev["id"]})
    await client.delete(f"/api/v1/devices/{dev['id']}", headers=user.headers)
    await db.execute(update(PeerAssignment).values(updated_at=utcnow() - 2 * DAY))
    await db.commit()
    async with ctx.sessionmaker() as s:
        await cleanup_tokens(ctx, s)
    assert await db.scalar(select(PeerAssignment)) is None
