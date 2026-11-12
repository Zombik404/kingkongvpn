from __future__ import annotations

import datetime as dt
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.context import AppContext
from app.models import AuditLog, Plan, PlanPrice, Subscription
from app.models.base import utcnow
from app.services import settings as settings_service
from app.subscriptions import service as subs
from tests.helpers import new_user

API = "/api/v1/subscription"
DAY = dt.timedelta(days=1)


async def seed_plans(db: Any, *, trial_enabled: bool = True) -> tuple[Plan, Plan]:
    trial = Plan(
        code="trial", names={"en": "Trial", "ru": "Пробный"}, device_limit=2, is_trial=True
    )
    std = Plan(code="standard", names={"en": "Standard", "ru": "Стандарт"}, device_limit=5)
    db.add_all([trial, std])
    await db.flush()
    db.add_all(
        [
            PlanPrice(
                plan_id=std.id,
                period_unit="month",
                period_count=1,
                currency="EUR",
                amount_minor=499,
            ),
            PlanPrice(
                plan_id=std.id,
                period_unit="year",
                period_count=1,
                currency="EUR",
                amount_minor=3999,
            ),
            PlanPrice(
                plan_id=std.id,
                period_unit="month",
                period_count=1,
                currency="USD",
                amount_minor=599,
                active=False,
            ),
            PlanPrice(
                plan_id=std.id,
                period_unit="month",
                period_count=3,
                currency="EUR",
                amount_minor=1299,
                valid_until=utcnow() - DAY,
            ),
        ]
    )
    await settings_service.set_value(db, "trial.enabled", trial_enabled, actor_id=None)
    await db.commit()
    return trial, std


async def test_public_plans_show_only_live_prices(client: AsyncClient, db: Any) -> None:
    await seed_plans(db)
    r = await client.get("/api/v1/plans", headers={"Accept-Language": "ru"})
    assert r.status_code == 200
    [plan] = r.json()  # trial plan isn't purchasable
    assert plan["code"] == "standard"
    assert plan["name"] == "Стандарт"
    assert sorted(p["amount_minor"] for p in plan["prices"]) == [499, 3999]
    r = await client.get("/api/v1/plans?locale=hu")
    assert r.json()[0]["name"] == "Standard"  # falls back to English


async def test_trial_flow(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    await seed_plans(db)
    user = await new_user(client, outbox, "sub1@example.com")
    status = (await client.get(API, headers=user.headers)).json()
    assert status == {"entitled": False, "subscription": None, "trial_available": True}
    r = await client.post(f"{API}/trial", headers=user.headers)
    assert r.status_code == 201, r.text
    sub = r.json()
    assert sub["status"] == "trialing"
    assert sub["plan_code"] == "trial"
    assert sub["device_limit"] == 2
    length = dt.datetime.fromisoformat(sub["current_period_end"]) - dt.datetime.fromisoformat(
        sub["current_period_start"]
    )
    assert length == 3 * DAY
    # only once, ever
    r = await client.post(f"{API}/trial", headers=user.headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "trial_unavailable"
    status = (await client.get(API, headers=user.headers)).json()
    assert status["entitled"] is True and status["trial_available"] is False
    devices = (await client.get("/api/v1/devices", headers=user.headers)).json()
    assert devices["limit"] == 2


async def test_trial_disabled(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    await seed_plans(db, trial_enabled=False)
    user = await new_user(client, outbox, "sub2@example.com")
    assert (await client.get(API, headers=user.headers)).json()["trial_available"] is False
    assert (await client.post(f"{API}/trial", headers=user.headers)).status_code == 409


async def test_cancel_and_resume(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    await seed_plans(db)
    user = await new_user(client, outbox, "sub3@example.com")
    assert (await client.post(f"{API}/cancel", headers=user.headers)).status_code == 404
    await client.post(f"{API}/trial", headers=user.headers)
    r = await client.post(f"{API}/cancel", headers=user.headers)
    assert r.json()["cancel_at_period_end"] is True
    r = await client.post(f"{API}/cancel", headers=user.headers)
    assert r.status_code == 409
    r = await client.post(f"{API}/resume", headers=user.headers)
    assert r.json()["cancel_at_period_end"] is False


async def test_expiry_job_grace_then_expired(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    _, std = await seed_plans(db)
    user = await new_user(client, outbox, "sub4@example.com")
    async with ctx.sessionmaker() as s:
        from app.models.enums import ActorType, Provider

        await subs.grant_days(
            s,
            user_id=user.user_id,
            plan=std,
            days=30,
            provider=Provider.ADMIN,
            actor_id=None,
            actor_type=ActorType.SYSTEM,
            ip=None,
        )
        await s.commit()
    now = utcnow()
    async with ctx.sessionmaker() as s:
        assert await subs.process_due(ctx, s, now=now) == 0
    async with ctx.sessionmaker() as s:
        assert await subs.process_due(ctx, s, now=now + 31 * DAY) == 1
    status = (await client.get(API, headers=user.headers)).json()
    assert status["subscription"]["status"] == "grace"
    assert status["entitled"] is True
    outbox.clear()
    async with ctx.sessionmaker() as s:
        assert await subs.process_due(ctx, s, now=now + 32 * DAY) == 0  # grace not over
        assert await subs.process_due(ctx, s, now=now + 34 * DAY) == 1
    status = (await client.get(API, headers=user.headers)).json()
    assert status == {"entitled": False, "subscription": None, "trial_available": True}
    [mail] = outbox
    assert mail.template == "subscription_expired"
    assert "Standard" in mail.text
    async with ctx.sessionmaker() as s:  # idempotent
        assert await subs.process_due(ctx, s, now=now + 40 * DAY) == 0
    changes = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "subscription.status_changed"))
    ).all()
    assert [(c.details["from"], c.details["to"]) for c in changes] == [
        ("active", "grace"),
        ("grace", "expired"),
    ]


async def test_canceled_subscription_skips_grace(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    await seed_plans(db)
    user = await new_user(client, outbox, "sub5@example.com")
    await client.post(f"{API}/trial", headers=user.headers)
    await client.post(f"{API}/cancel", headers=user.headers)
    async with ctx.sessionmaker() as s:
        await subs.process_due(ctx, s, now=utcnow() + 4 * DAY)
    sub = await db.scalar(select(Subscription))
    assert sub.status == "expired"  # trials expire directly


async def test_reminders_once_per_threshold(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    await seed_plans(db)
    await settings_service.set_value(db, "reminders.days_before", [7, 1], actor_id=None)
    await db.commit()
    user = await new_user(client, outbox, "sub6@example.com")
    await client.post(f"{API}/trial", headers=user.headers)  # ends in 3 days
    await db.execute(update(Subscription).values(current_period_end=utcnow() + 3 * DAY))
    await db.commit()
    outbox.clear()
    now = utcnow()
    async with ctx.sessionmaker() as s:
        assert await subs.send_reminders(ctx, s, now=now) == 1
        assert await subs.send_reminders(ctx, s, now=now + dt.timedelta(hours=1)) == 0
        assert await subs.send_reminders(ctx, s, now=now + 2 * DAY + dt.timedelta(hours=1)) == 1
        assert await subs.send_reminders(ctx, s, now=now + 2 * DAY + dt.timedelta(hours=2)) == 0
    assert [m.template for m in outbox] == ["subscription_ending"] * 2
    assert "Trial" in outbox[0].subject or "Trial" in outbox[0].text


async def test_auto_renewing_subscriptions_get_no_reminder(
    ctx: AppContext, db: Any, client: AsyncClient, outbox: list[Any]
) -> None:
    _, std = await seed_plans(db)
    user = await new_user(client, outbox, "sub7@example.com")
    now = utcnow()
    db.add(
        Subscription(
            user_id=user.user_id,
            plan_id=std.id,
            status="active",
            provider="stripe",
            provider_subscription_id="sub_123",
            auto_renew=True,
            current_period_start=now - 28 * DAY,
            current_period_end=now + 2 * DAY,
        )
    )
    await db.commit()
    async with ctx.sessionmaker() as s:
        assert await subs.send_reminders(ctx, s, now=now) == 0


async def test_one_live_subscription_per_user_enforced_by_db(
    db: Any, client: AsyncClient, outbox: list[Any]
) -> None:
    import pytest
    from sqlalchemy.exc import IntegrityError

    _, std = await seed_plans(db)
    user = await new_user(client, outbox, "sub8@example.com")
    now = utcnow()
    for i in range(2):
        db.add(
            Subscription(
                user_id=user.user_id,
                plan_id=std.id,
                status="active",
                provider="admin",
                current_period_start=now,
                current_period_end=now + (i + 1) * DAY,
            )
        )
    with pytest.raises(IntegrityError):
        await db.commit()
