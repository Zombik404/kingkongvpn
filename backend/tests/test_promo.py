from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.models import PlanPrice, PromoCode, PromoRedemption
from app.models.base import utcnow
from tests.helpers import new_user
from tests.test_subscriptions import seed_plans

API = "/api/v1/promo"


async def test_free_days_redeem_starts_then_extends(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    _, std = await seed_plans(db)
    db.add(PromoCode(code="WELCOME30", kind="free_days", free_days=30, plan_id=std.id))
    db.add(PromoCode(code="MORE7", kind="free_days", free_days=7, plan_id=std.id))
    await db.commit()
    user = await new_user(client, outbox, "promo1@example.com")
    r = await client.post(f"{API}/redeem", headers=user.headers, json={"code": "welcome30"})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["status"] == "active" and first["plan_code"] == "standard"
    assert first["provider"] == "promo"
    r = await client.post(f"{API}/redeem", headers=user.headers, json={"code": "WELCOME30"})
    assert r.status_code == 422  # once per user
    r = await client.post(f"{API}/redeem", headers=user.headers, json={"code": "MORE7"})
    end_a = dt.datetime.fromisoformat(first["current_period_end"])
    end_b = dt.datetime.fromisoformat(r.json()["current_period_end"])
    assert end_b - end_a == dt.timedelta(days=7)


async def test_trial_converted_by_promo(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    _, std = await seed_plans(db)
    db.add(PromoCode(code="UPGRADE", kind="free_days", free_days=10, plan_id=std.id))
    await db.commit()
    user = await new_user(client, outbox, "promo2@example.com")
    await client.post("/api/v1/subscription/trial", headers=user.headers)
    r = await client.post(f"{API}/redeem", headers=user.headers, json={"code": "UPGRADE"})
    assert r.json()["status"] == "active"
    assert r.json()["plan_code"] == "standard"
    assert r.json()["device_limit"] == 5


async def test_invalid_codes(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    _, std = await seed_plans(db)
    now = utcnow()
    db.add_all(
        [
            PromoCode(code="OFF", kind="free_days", free_days=5, plan_id=std.id, active=False),
            PromoCode(
                code="LATE",
                kind="free_days",
                free_days=5,
                plan_id=std.id,
                valid_until=now - dt.timedelta(minutes=1),
            ),
            PromoCode(
                code="EARLY",
                kind="free_days",
                free_days=5,
                plan_id=std.id,
                valid_from=now + dt.timedelta(days=1),
            ),
            PromoCode(code="PCT", kind="percent_off", percent_off=20),
        ]
    )
    await db.commit()
    user = await new_user(client, outbox, "promo3@example.com")
    for code in ("OFF", "LATE", "EARLY", "NOPE", "PCT"):
        r = await client.post(f"{API}/redeem", headers=user.headers, json={"code": code})
        assert r.status_code == 422, code
        assert r.json()["error"]["code"] == "invalid_promo_code"


async def test_max_redemptions_under_concurrency(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    _, std = await seed_plans(db)
    db.add(
        PromoCode(code="LIMITED", kind="free_days", free_days=3, plan_id=std.id, max_redemptions=2)
    )
    await db.commit()
    users = [await new_user(client, outbox, f"promo-c{i}@example.com") for i in range(5)]
    results = await asyncio.gather(
        *[client.post(f"{API}/redeem", headers=u.headers, json={"code": "LIMITED"}) for u in users]
    )
    assert sorted(r.status_code for r in results) == [200, 200, 422, 422, 422]
    promo = await db.scalar(select(PromoCode))
    await db.refresh(promo)
    assert promo.redemption_count == 2
    assert len((await db.scalars(select(PromoRedemption))).all()) == 2


async def test_validate_discount_codes(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    trial, std = await seed_plans(db)
    db.add_all(
        [
            PromoCode(code="TWENTY", kind="percent_off", percent_off=20),
            PromoCode(code="ONEEURO", kind="amount_off", amount_off_minor=100, currency="EUR"),
            PromoCode(code="BIGUSD", kind="amount_off", amount_off_minor=100000, currency="USD"),
            PromoCode(code="TRIALONLY", kind="percent_off", percent_off=50, plan_id=trial.id),
            PromoCode(code="FREE", kind="free_days", free_days=5, plan_id=std.id),
        ]
    )
    await db.commit()
    price = await db.scalar(select(PlanPrice).where(PlanPrice.amount_minor == 499))
    user = await new_user(client, outbox, "promo4@example.com")

    async def quote(code: str) -> Any:
        return await client.post(
            f"{API}/validate", headers=user.headers, json={"code": code, "price_id": str(price.id)}
        )

    r = await quote("twenty")
    assert r.json() == {
        "code": "TWENTY",
        "kind": "percent_off",
        "currency": "EUR",
        "original_amount_minor": 499,
        "discounted_amount_minor": 400,
    }
    assert (await quote("ONEEURO")).json()["discounted_amount_minor"] == 399
    for bad in ("BIGUSD", "TRIALONLY", "FREE"):
        assert (await quote(bad)).status_code == 422, bad
