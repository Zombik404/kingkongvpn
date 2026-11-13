"""Staff API pieces behind the admin panel: create-staff, /admin/me, overview, payments,
user search by Telegram ID and referral code."""

from __future__ import annotations

import contextlib
import io
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.cli import create_staff
from app.core.config import Settings
from app.models import AuditLog, Payment, User
from app.models.base import utcnow
from tests.conftest import make_settings
from tests.helpers import enable_mfa, login, staff
from tests.test_telegram_vpn import BOT_TOKEN, tg_login

A = "/api/v1/admin"


@pytest.fixture
def settings() -> Settings:
    return make_settings(telegram_bot_token=BOT_TOKEN, public_web_url="https://vpn.test")


async def _create_staff(email: str, role: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        rc = await create_staff(email, role)
    return rc, out.getvalue()


async def test_create_staff_login_and_mfa_gate(client: AsyncClient, db: Any) -> None:
    assert (await _create_staff("boss@example.com", "nope"))[0] == 1
    rc, out = await _create_staff("Boss@Example.com", "superadmin")
    assert rc == 0
    password = out.split("one-time password: ")[1].split()[0]
    assert len(password) >= 20
    user = await login(client, "boss@example.com", password)
    # signed in, but staff routes need 2FA on this session first
    r = await client.get(f"{A}/me", headers=user.headers)
    assert r.status_code == 403 and r.json()["error"]["code"] == "mfa_required"
    await enable_mfa(client, user)  # enabling TOTP verifies the current session
    me = (await client.get(f"{A}/me", headers=user.headers)).json()
    assert me["email"] == "boss@example.com" and me["roles"] == ["superadmin"]
    assert "servers:write" in me["permissions"] and "payments:read" in me["permissions"]
    # re-running resets the password and signs the old sessions out
    rc, out2 = await _create_staff("boss@example.com", "ops")
    assert rc == 0 and password not in out2
    assert (await client.get(f"{A}/me", headers=user.headers)).status_code == 401
    row = await db.scalar(select(User).where(User.email == "boss@example.com"))
    assert row.roles == ["ops", "superadmin"]
    actions = (await db.scalars(select(AuditLog.action))).all()
    assert actions.count("cli.staff_created") == 2
    # the one-time password never lands in the audit log
    assert password not in " ".join(str(d) for d in (await db.scalars(select(AuditLog.details))))
    # a Telegram user account can't be turned into a staff account this way
    await tg_login(client, 9001)
    tg_user = await db.scalar(select(User).where(User.telegram_id == 9001))
    tg_user.email = "tg@example.com"
    await db.commit()
    assert (await _create_staff("tg@example.com", "support"))[0] == 1


async def test_overview_payments_and_search(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    support = await staff(client, outbox, db, "sup@example.com", ["support"])
    ops = await staff(client, outbox, db, "ops@example.com", ["ops"])
    finance = await staff(client, outbox, db, "fin@example.com", ["finance"])
    await tg_login(client, 777001)
    tg_user = await db.scalar(select(User).where(User.telegram_id == 777001))
    tg_user.referral_code = "KONG2026"
    db.add(
        Payment(
            user_id=tg_user.id,
            provider="cryptobot",
            provider_payment_id="inv-1",
            amount_minor=1300,
            currency="USD",
            status="succeeded",
            kind="initial",
            paid_at=utcnow(),
            paid_asset="USDT",
            paid_amount="13",
        )
    )
    await db.commit()

    o = (await client.get(f"{A}/overview", headers=support.headers)).json()
    assert o["users"]["total"] == 4 and o["users"]["telegram"] == 1
    assert len(o["signups_30d"]) == 30 and o["signups_30d"][-1]["count"] == 4
    assert o["revenue_30d"]["by_currency"] == {"USD": {"count": 1, "amount_minor": 1300}}
    assert o["revenue_30d"]["usd_daily"][-1]["amount_minor"] == 1300
    o = (await client.get(f"{A}/overview", headers=ops.headers)).json()
    assert o["revenue_30d"] is None  # ops don't see money

    assert (await client.get(f"{A}/payments", headers=ops.headers)).status_code == 403
    pays = (await client.get(f"{A}/payments", headers=finance.headers)).json()
    assert [(p["amount_minor"], p["status"], p["paid_asset"]) for p in pays] == [
        (1300, "succeeded", "USDT")
    ]
    pays = (
        await client.get(
            f"{A}/payments", headers=finance.headers, params={"user_id": str(support.user_id)}
        )
    ).json()
    assert pays == []

    async def search(**params: Any) -> list[Any]:
        r = await client.get(f"{A}/users", headers=support.headers, params=params)
        assert r.status_code == 200, r.text
        return list(r.json())

    found = await search(q="777001")
    assert [u["id"] for u in found] == [str(tg_user.id)] and found[0]["has_telegram"] is True
    assert "telegram_id" not in found[0]  # searchable, never shown
    assert [u["id"] for u in await search(q="KONG2026")] == [str(tg_user.id)]
    assert [u["email"] for u in await search(q="fin@")] == ["fin@example.com"]
    assert {u["email"] for u in await search(staff_only=True)} == {
        "sup@example.com",
        "ops@example.com",
        "fin@example.com",
    }
    assert await search(status="suspended") == []
    assert await search(q="99999999999999999999") == []  # too long for a Telegram ID: email path


async def test_staff_without_mfa_is_refused_everywhere(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    _, out = await _create_staff("nomfa@example.com", "support")
    password = out.split("one-time password: ")[1].split()[0]
    user = await login(client, "nomfa@example.com", password)
    for path in ("/me", "/overview", "/payments", "/users", "/vpn/servers", "/games/overview"):
        r = await client.get(f"{A}{path}", headers=user.headers)
        assert r.status_code == 403, path
