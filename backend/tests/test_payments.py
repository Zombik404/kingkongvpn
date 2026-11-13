from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.context import AppContext
from app.models import AuditLog, Payment, PaymentEvent, Plan, PlanPrice, PromoCode, Subscription
from app.models.base import utcnow
from app.payments import cryptobot
from app.payments import service as payments
from app.payments.cryptobot import CryptoBotClient, Invoice
from tests.conftest import make_settings
from tests.helpers import new_user

TOKEN = "123:test-token-for-crypto-pay"
DAY = dt.timedelta(days=1)


class FakeCryptoPay:
    """In-memory stand-in for the Crypto Pay API."""

    def __init__(self) -> None:
        self.invoices: dict[int, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = False
        self.offered = ["TON", "USDC", "USDT", "BTC"]  # API still on the old TON code
        self._next = 1000

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Crypto-Pay-API-Token"] == TOKEN
        method = request.url.path.rsplit("/", 1)[-1]
        params = json.loads(request.content or b"{}")
        self.calls.append((method, params))
        if self.fail:
            return httpx.Response(500, json={"ok": False, "error": {"code": 500}})
        if method == "createInvoice":
            self._next += 1
            inv = {
                "invoice_id": self._next,
                "hash": f"IV{self._next}",
                "currency_type": "fiat",
                "fiat": params["fiat"],
                "amount": params["amount"],
                "status": "active",
                "payload": params["payload"],
                "accepted_assets": params["accepted_assets"],
                "bot_invoice_url": f"https://t.me/CryptoTestnetBot?start=IV{self._next}",
                "created_at": utcnow().isoformat(),
                "expiration_date": (utcnow() + dt.timedelta(seconds=params["expires_in"]))
                .isoformat()
                .replace("+00:00", "Z"),
            }
            self.invoices[self._next] = inv
            return httpx.Response(200, json={"ok": True, "result": inv})
        if method == "getInvoices":
            ids = [int(i) for i in str(params.get("invoice_ids", "")).split(",") if i]
            items = [self.invoices[i] for i in ids if i in self.invoices]
            return httpx.Response(200, json={"ok": True, "result": {"items": items}})
        if method == "getCurrencies":
            items = [
                {"code": c, "is_blockchain": c != "USDC", "is_stablecoin": c == "USDC"}
                for c in self.offered
            ] + [{"code": "USD", "is_fiat": True}]
            return httpx.Response(200, json={"ok": True, "result": items})
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"app_id": 1, "name": "t"}})
        return httpx.Response(200, json={"ok": False, "error": "METHOD_NOT_FOUND"})

    def pay(self, invoice_id: int, *, asset: str = "GRAM", amount: str = "2.5") -> dict[str, Any]:
        inv = self.invoices[invoice_id]
        inv.update(
            status="paid",
            paid_asset=asset,
            paid_amount=amount,
            paid_at=utcnow().isoformat().replace("+00:00", "Z"),
        )
        return inv


@pytest.fixture
def settings() -> Settings:
    return make_settings(
        cryptobot_api_token=TOKEN,
        telegram_bot_username="myvpn_test_bot",
        cryptobot_accepted_assets="GRAM,USDC",
    )


@pytest.fixture
def fake(ctx: AppContext) -> FakeCryptoPay:
    f = FakeCryptoPay()
    ctx.cryptobot = CryptoBotClient(ctx.settings, transport=httpx.MockTransport(f.handler))
    return f


async def seed(db: Any) -> dict[int, PlanPrice]:
    plan = Plan(code="standard", names={"en": "Standard", "ru": "Стандарт"}, device_limit=5)
    trial = Plan(code="trial", names={"en": "Trial"}, device_limit=2, is_trial=True)
    db.add_all([plan, trial])
    await db.flush()
    prices = {}
    for months, cents in ((1, 500), (3, 1300), (6, 2400), (12, 4200)):
        prices[months] = PlanPrice(
            plan_id=plan.id,
            period_unit="month",
            period_count=months,
            currency="USD",
            amount_minor=cents,
        )
        db.add(prices[months])
    prices[0] = PlanPrice(
        plan_id=trial.id, period_unit="day", period_count=3, currency="USD", amount_minor=100
    )
    db.add(prices[0])
    await db.commit()
    return prices


def webhook(
    invoice: dict[str, Any], *, token: str = TOKEN, when: dt.datetime | None = None
) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(
        {
            "update_id": 1,
            "update_type": "invoice_paid",
            "request_date": (when or utcnow()).isoformat().replace("+00:00", "Z"),
            "payload": invoice,
        }
    ).encode()
    sig = hmac.new(hashlib.sha256(token.encode()).digest(), body, hashlib.sha256).hexdigest()
    return body, {"crypto-pay-api-signature": sig, "content-type": "application/json"}


async def checkout(
    client: AsyncClient, user: Any, price: PlanPrice, promo: str | None = None
) -> httpx.Response:
    body: dict[str, Any] = {"price_id": str(price.id)}
    if promo:
        body["promo_code"] = promo
    return await client.post("/api/v1/payments/checkout", headers=user.headers, json=body)


# --- pure helpers ---------------------------------------------------------------------------
def test_amounts_and_periods() -> None:
    assert cryptobot.minor_to_amount(499) == "4.99"
    assert cryptobot.minor_to_amount(1300) == "13.00"
    jan31 = dt.datetime(2027, 1, 31, 12, tzinfo=dt.UTC)
    assert payments.add_period(jan31, "month", 1) == dt.datetime(2027, 2, 28, 12, tzinfo=dt.UTC)
    assert payments.add_period(jan31, "month", 13).date() == dt.date(2028, 2, 29)
    assert payments.add_period(jan31, "year", 1).date() == dt.date(2028, 1, 31)
    assert payments.add_period(jan31, "day", 3).date() == dt.date(2027, 2, 3)


def test_signature_and_staleness() -> None:
    body, headers = webhook({"invoice_id": 1, "status": "paid", "amount": "1"})
    sig = headers["crypto-pay-api-signature"]
    assert cryptobot.verify_signature(TOKEN, body, sig)
    assert cryptobot.verify_signature(TOKEN, body, sig.upper())
    assert not cryptobot.verify_signature(TOKEN, body + b" ", sig)
    assert not cryptobot.verify_signature("other", body, sig)
    assert not cryptobot.verify_signature(TOKEN, body, None)
    assert not cryptobot.verify_signature("", body, sig)
    old, _ = webhook(
        {"invoice_id": 1, "status": "paid", "amount": "1"}, when=utcnow() - dt.timedelta(hours=1)
    )
    with pytest.raises(ValueError):
        cryptobot.parse_webhook(old, now=utcnow())
    with pytest.raises(ValueError):
        cryptobot.parse_webhook(b'{"payload": 1}', now=utcnow())


def test_settings_assets_and_urls() -> None:
    s = make_settings(cryptobot_accepted_assets="gram, usdt")
    assert s.cryptobot_accepted_assets == ["GRAM", "USDT"]
    assert s.cryptobot_base_url == "https://testnet-pay.crypt.bot/api"
    assert make_settings(cryptobot_network="mainnet").cryptobot_base_url == (
        "https://pay.crypt.bot/api"
    )


# --- checkout ---------------------------------------------------------------------------------
async def test_checkout_creates_invoice(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay
) -> None:
    prices = await seed(db)
    user = await new_user(client, outbox, "pay1@example.com")
    r = await checkout(client, user, prices[3])
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "pending" and out["provider"] == "cryptobot"
    assert out["amount_minor"] == 1300 and out["currency"] == "USD"
    assert out["plan_code"] == "standard" and out["period_count"] == 3
    assert out["checkout_url"].startswith("https://t.me/CryptoTestnetBot")
    method, params = fake.calls[-1]
    assert method == "createInvoice"
    assert params["currency_type"] == "fiat" and params["fiat"] == "USD"
    assert params["amount"] == "13.00"
    assert params["accepted_assets"] == "TON,USDC"  # GRAM resolved to the API's TON code
    assert params["payload"] == out["id"]
    assert params["paid_btn_url"] == "https://t.me/myvpn_test_bot"
    assert "Standard — 3 months" in params["description"]
    listing = (await client.get("/api/v1/payments", headers=user.headers)).json()
    assert [p["id"] for p in listing] == [out["id"]]


async def test_checkout_rejections(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay, ctx: AppContext
) -> None:
    prices = await seed(db)
    user = await new_user(client, outbox, "pay2@example.com")
    assert (await checkout(client, user, prices[0])).status_code == 404  # trial plan
    prices[1].active = False
    await db.commit()
    assert (await checkout(client, user, prices[1])).status_code == 404
    for _ in range(ctx.settings.payment_pending_limit_per_user):
        assert (await checkout(client, user, prices[6])).status_code == 201
    r = await checkout(client, user, prices[6])
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_pending_payments"
    fake.fail = True
    other = await new_user(client, outbox, "pay3@example.com")
    r = await checkout(client, other, prices[12])
    assert r.status_code == 502
    assert await db.scalar(select(Payment).where(Payment.user_id == other.user_id)) is None
    ctx.cryptobot = None
    assert (await checkout(client, other, prices[12])).status_code == 503


# --- webhook ------------------------------------------------------------------------------------
async def test_webhook_credits_once(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay
) -> None:
    prices = await seed(db)
    user = await new_user(client, outbox, "pay4@example.com")
    pay = (await checkout(client, user, prices[3])).json()
    inv = fake.pay(fake._next, asset="GRAM", amount="4.2")
    body, headers = webhook(inv)
    before = utcnow()
    r = await client.post("/api/v1/webhooks/cryptobot", content=body, headers=headers)
    assert r.status_code == 200 and r.json()["outcome"] == "credited"
    sub = (await client.get("/api/v1/subscription", headers=user.headers)).json()["subscription"]
    assert sub["status"] == "active" and sub["plan_code"] == "standard"
    assert sub["provider"] == "cryptobot"
    end = dt.datetime.fromisoformat(sub["current_period_end"])
    expected = payments.add_period(before, "month", 3)
    assert abs(end - expected) < dt.timedelta(days=1)
    p = (await client.get(f"/api/v1/payments/{pay['id']}", headers=user.headers)).json()
    assert p["status"] == "succeeded" and p["checkout_url"] is None and p["paid_at"]
    row = await db.get(Payment, pay["id"])
    assert (row.paid_asset, row.paid_amount) == ("GRAM", "4.2")
    assert outbox[-1].template == "payment_received"
    # the same notification again (providers retry) changes nothing
    body2, headers2 = webhook(inv)
    r = await client.post("/api/v1/webhooks/cryptobot", content=body2, headers=headers2)
    assert r.json()["outcome"] == "duplicate"
    sub2 = (await client.get("/api/v1/subscription", headers=user.headers)).json()["subscription"]
    assert sub2["current_period_end"] == sub["current_period_end"]
    events = (await db.scalars(select(PaymentEvent))).all()
    assert len(events) == 1  # keyed by invoice+status, not by the non-unique update_id
    assert await db.scalar(select(AuditLog.id).where(AuditLog.action == "payment.succeeded"))


async def test_webhook_rejects_forgeries(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay
) -> None:
    prices = await seed(db)
    user = await new_user(client, outbox, "pay5@example.com")
    await checkout(client, user, prices[1])
    inv = fake.pay(fake._next)
    body, _ = webhook(inv, token="attacker-guess")
    _, good_headers = webhook(inv)
    r = await client.post(
        "/api/v1/webhooks/cryptobot", content=body, headers={"crypto-pay-api-signature": "0" * 64}
    )
    assert r.status_code == 401
    r = await client.post("/api/v1/webhooks/cryptobot", content=body, headers=good_headers)
    assert r.status_code == 401  # signature from another body
    stale, stale_headers = webhook(inv, when=utcnow() - dt.timedelta(hours=2))
    r = await client.post("/api/v1/webhooks/cryptobot", content=stale, headers=stale_headers)
    assert r.status_code == 400
    me = (await client.get("/api/v1/subscription", headers=user.headers)).json()
    assert me["entitled"] is False


async def test_amount_and_payload_mismatch_do_not_grant(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay
) -> None:
    prices = await seed(db)
    user = await new_user(client, outbox, "pay6@example.com")
    await checkout(client, user, prices[12])
    inv = dict(fake.pay(fake._next), amount="1.00")  # underpaid / tampered invoice
    body, headers = webhook(inv)
    r = await client.post("/api/v1/webhooks/cryptobot", content=body, headers=headers)
    assert r.json()["outcome"] == "mismatch"
    p = await db.scalar(select(Payment))
    assert (p.status, p.failure_reason) == ("failed", "amount_mismatch")
    await checkout(client, user, prices[1])
    inv2 = dict(fake.pay(fake._next), payload="00000000-0000-0000-0000-000000000000")
    body, headers = webhook(inv2)
    assert (await client.post("/api/v1/webhooks/cryptobot", content=body, headers=headers)).json()[
        "outcome"
    ] == "mismatch"
    body, headers = webhook({**inv2, "invoice_id": 999999})
    assert (await client.post("/api/v1/webhooks/cryptobot", content=body, headers=headers)).json()[
        "outcome"
    ] == "unknown"
    me = (await client.get("/api/v1/subscription", headers=user.headers)).json()
    assert me["entitled"] is False


async def test_webhook_disabled_without_token(client: AsyncClient, ctx: AppContext) -> None:
    ctx.cryptobot = None
    r = await client.post("/api/v1/webhooks/cryptobot", content=b"{}")
    assert r.status_code == 404


# --- polling, refresh, renewal, promo, concurrency ------------------------------------------------
async def test_poll_credits_and_expires(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay, ctx: AppContext
) -> None:
    prices = await seed(db)
    user = await new_user(client, outbox, "pay7@example.com")
    paid = (await checkout(client, user, prices[1])).json()
    fake.pay(fake._next)
    expired = (await checkout(client, user, prices[6])).json()
    fake.invoices[fake._next]["status"] = "expired"
    still = (await checkout(client, user, prices[12])).json()
    async with ctx.sessionmaker() as s:
        counts = await payments.poll_pending(ctx, s)
    assert counts == {"credited": 1, "expired": 1}
    statuses = {
        p["id"]: p["status"]
        for p in (await client.get("/api/v1/payments", headers=user.headers)).json()
    }
    assert statuses == {paid["id"]: "succeeded", expired["id"]: "failed", still["id"]: "pending"}
    async with ctx.sessionmaker() as s:
        assert await payments.poll_pending(ctx, s) == {}


async def test_user_refresh_button(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay
) -> None:
    prices = await seed(db)
    user = await new_user(client, outbox, "pay8@example.com")
    other = await new_user(client, outbox, "pay9@example.com")
    pay = (await checkout(client, user, prices[1])).json()
    url = f"/api/v1/payments/{pay['id']}?refresh=true"
    assert (await client.get(url, headers=user.headers)).json()["status"] == "pending"
    fake.pay(fake._next)
    assert (await client.get(url, headers=other.headers)).status_code == 404
    assert (await client.get(url, headers=user.headers)).json()["status"] == "succeeded"


async def test_renewal_extends_from_current_end(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay, ctx: AppContext
) -> None:
    prices = await seed(db)
    user = await new_user(client, outbox, "pay10@example.com")
    await checkout(client, user, prices[1])
    fake.pay(fake._next)
    async with ctx.sessionmaker() as s:
        await payments.poll_pending(ctx, s)
    first_end = (await db.scalar(select(Subscription))).current_period_end
    r = await checkout(client, user, prices[12])
    p = await db.get(Payment, r.json()["id"])
    assert p.kind == "renewal"
    fake.pay(fake._next)
    async with ctx.sessionmaker() as s:
        await payments.poll_pending(ctx, s)
    db.expire_all()
    sub = await db.scalar(select(Subscription))
    assert abs(sub.current_period_end - payments.add_period(first_end, "year", 1)) < DAY


async def test_discount_code_at_checkout(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay, ctx: AppContext
) -> None:
    prices = await seed(db)
    db.add(PromoCode(code="LAUNCH20", kind="percent_off", percent_off=20))
    db.add(PromoCode(code="ALLFREE", kind="percent_off", percent_off=100))
    await db.commit()
    user = await new_user(client, outbox, "pay11@example.com")
    r = await checkout(client, user, prices[12], promo="launch20")
    assert r.json()["amount_minor"] == 3360
    assert fake.calls[-1][1]["amount"] == "33.60"
    r2 = await checkout(client, user, prices[12], promo="ALLFREE")
    assert r2.status_code == 422
    fake.pay(fake._next)
    async with ctx.sessionmaker() as s:
        assert await payments.poll_pending(ctx, s) == {"credited": 1}
    promo = await db.scalar(select(PromoCode).where(PromoCode.code == "LAUNCH20"))
    await db.refresh(promo)
    assert promo.redemption_count == 1
    r3 = await checkout(client, user, prices[1], promo="LAUNCH20")
    assert r3.status_code == 422  # once per account


async def test_concurrent_webhook_and_poll_credit_once(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay, ctx: AppContext
) -> None:
    prices = await seed(db)
    user = await new_user(client, outbox, "pay12@example.com")
    await checkout(client, user, prices[1])
    inv = fake.pay(fake._next)

    async def via_webhook() -> None:
        body, headers = webhook(inv)
        await client.post("/api/v1/webhooks/cryptobot", content=body, headers=headers)

    async def via_poll() -> None:
        async with ctx.sessionmaker() as s:
            await payments.poll_pending(ctx, s)

    async def via_apply() -> None:
        async with ctx.sessionmaker() as s:
            await payments.apply_invoice(ctx, s, Invoice.parse(inv), source="test")

    await asyncio.gather(via_webhook(), via_poll(), via_apply(), via_webhook())
    oks = (await db.scalars(select(AuditLog).where(AuditLog.action == "payment.succeeded"))).all()
    assert len(oks) == 1
    sub = await db.scalar(select(Subscription))
    assert (sub.current_period_end - sub.current_period_start) < dt.timedelta(days=32)


async def test_cli_set_price_replaces_active(db: Any, ctx: AppContext) -> None:
    from app.cli import set_price

    await seed(db)
    assert await set_price("standard", "month", 3, "USD", "12.99", quiet=True) == 0
    assert await set_price("standard", "month", 3, "USD", "1.999") == 1
    assert await set_price("nope", "month", 3, "USD", "1") == 1
    rows = (
        await db.scalars(
            select(PlanPrice).where(PlanPrice.period_count == 3, PlanPrice.period_unit == "month")
        )
    ).all()
    active = [r for r in rows if r.active]
    assert len(rows) == 2 and len(active) == 1 and active[0].amount_minor == 1299
    assert Decimal(active[0].amount_minor) / 100 == Decimal("12.99")


async def test_asset_resolution(ctx: AppContext) -> None:
    async def resolved(offered: list[str] | None, configured: str) -> list[str] | str:
        fake = FakeCryptoPay()
        if offered is None:
            fake.fail = True
        else:
            fake.offered = offered
        s = make_settings(cryptobot_api_token=TOKEN, cryptobot_accepted_assets=configured)
        c = CryptoBotClient(s, transport=httpx.MockTransport(fake.handler))
        try:
            first = await c.accepted_assets()
            if offered is not None:
                assert await c.accepted_assets() == first
                assert [m for m, _ in fake.calls].count("getCurrencies") == 1  # cached
            return first
        except cryptobot.PaymentProviderError:
            return "error"
        finally:
            await c.aclose()

    assert await resolved(["GRAM", "TON", "USDC"], "GRAM,USDC") == ["GRAM", "USDC"]
    assert await resolved(["TON", "USDC"], "GRAM,USDC") == ["TON", "USDC"]
    assert await resolved(["GRAM", "USDT"], "GRAM,USDC") == ["GRAM"]  # USDC dropped, logged
    assert await resolved(None, "GRAM,USDC") == ["GRAM", "USDC"]  # API down: use config
    assert await resolved(["BTC"], "GRAM,USDC") == "error"


async def test_cli_bootstrap_catalog_idempotent(db: Any, ctx: AppContext) -> None:
    from app.cli import LAUNCH_PRICES_USD, bootstrap_catalog

    assert await bootstrap_catalog() == 0
    assert await bootstrap_catalog() == 0
    plans = {p.code: p for p in (await db.scalars(select(Plan))).all()}
    assert set(plans) == {"trial", "standard"} and plans["trial"].is_trial
    prices = (await db.scalars(select(PlanPrice))).all()
    assert len(prices) == 4  # the second run changed nothing
    assert sorted((p.period_count, p.amount_minor) for p in prices) == [
        (m, int(Decimal(a) * 100)) for m, a in LAUNCH_PRICES_USD
    ]


async def test_closed_test_requires_invite_before_paying(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay
) -> None:
    from app.services import settings as settings_service

    prices = await seed(db)
    plan = await db.scalar(select(Plan).where(Plan.code == "standard"))
    db.add(
        PromoCode(
            code="INV-TEST-0001", kind="free_days", free_days=7, plan_id=plan.id, max_redemptions=1
        )
    )
    await settings_service.set_value(db, "access.invite_only", True, actor_id=None)
    await db.commit()
    user = await new_user(client, outbox, "pay13@example.com")
    r = await checkout(client, user, prices[1])
    assert r.status_code == 403 and r.json()["error"]["code"] == "invite_required"
    assert not [c for c in fake.calls if c[0] == "createInvoice"]
    await client.post("/api/v1/promo/redeem", headers=user.headers, json={"code": "INV-TEST-0001"})
    assert (await checkout(client, user, prices[1])).status_code == 201
