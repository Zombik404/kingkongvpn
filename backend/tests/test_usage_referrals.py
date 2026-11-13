from __future__ import annotations

import base64
import datetime as dt
import os
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.config import Settings
from app.core.context import AppContext
from app.models import DeviceUsageDaily, Plan, ReferralReward, User
from app.models.base import utcnow
from app.models.enums import ActorType, Provider
from app.payments import service as payments
from app.payments.cryptobot import CryptoBotClient
from app.subscriptions import service as subs
from app.vpn import service as vpn
from tests.conftest import make_settings
from tests.helpers import new_user
from tests.test_payments import TOKEN, FakeCryptoPay, checkout, seed
from tests.test_telegram_vpn import beat, entitled_user_with_device, register_node

GB = 1024**3


@pytest.fixture
def settings() -> Settings:
    return make_settings(
        cryptobot_api_token=TOKEN,
        telegram_bot_username="vpnhub_bot",
        cryptobot_accepted_assets="GRAM,USDC",
        node_longpoll_seconds=1,
    )


@pytest.fixture
def fake(ctx: AppContext) -> FakeCryptoPay:
    f = FakeCryptoPay()
    ctx.cryptobot = CryptoBotClient(ctx.settings, transport=httpx.MockTransport(f.handler))
    return f


# --- traffic ------------------------------------------------------------------------------
async def test_usage_accounting_from_heartbeats(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    sid, token = await register_node()
    await beat(client, sid, token)
    user, dev = await entitled_user_with_device(client, outbox, db, "use1@example.com")
    await client.post("/api/v1/vpn/connect", headers=user.headers, json={"device_id": dev["id"]})
    other, odev = await entitled_user_with_device(client, outbox, db, "use2@example.com")
    await client.post("/api/v1/vpn/connect", headers=other.headers, json={"device_id": odev["id"]})
    k, ok = dev["public_key"], odev["public_key"]
    # server rx = client upload, server tx = client download
    await beat(
        client,
        sid,
        token,
        transfer={k: [100, 1000], ok: [5, 5], base64.b64encode(os.urandom(32)).decode(): [9, 9]},
    )
    await beat(client, sid, token, transfer={k: [300, 1500]})  # +200 up, +500 down
    await beat(client, sid, token, transfer={k: [50, 70]})  # peer re-added: counters restarted
    r = (await client.get("/api/v1/vpn/usage?days=7", headers=user.headers)).json()
    assert len(r["series"]) == 7 and r["series"][-1]["date"] == utcnow().date().isoformat()
    assert r["series"][-1] == {"date": utcnow().date().isoformat(), "download": 1570, "upload": 350}
    assert r["total_download"] == 1570 and r["total_upload"] == 350
    assert [d["name"] for d in r["top_devices"]] == ["phone"]
    r2 = (await client.get("/api/v1/vpn/usage", headers=other.headers)).json()
    assert r2["total_download"] == 5  # strictly per user
    assert (await client.get("/api/v1/vpn/usage?days=91", headers=user.headers)).status_code == 422
    # garbage counters are ignored, never crash the heartbeat
    r = await beat(client, sid, token, transfer={k: [-1, 5], "short": [1, 1], ok: [1]})
    assert r.status_code == 200


async def test_usage_series_top5_and_retention(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    user, dev = await entitled_user_with_device(client, outbox, db, "use3@example.com")
    from app.models import Plan
    from app.services import settings as settings_service

    await settings_service.set_value(db, "devices.limit_without_subscription", 10, actor_id=None)
    plan = await db.scalar(select(Plan).where(Plan.code == "standard"))
    plan.device_limit = 10
    await db.commit()
    ids = [dev["id"]]
    for i in range(6):
        d = (
            await client.post(
                "/api/v1/devices",
                headers=user.headers,
                json={
                    "name": f"dev{i}",
                    "platform": "android",
                    "public_key": base64.b64encode(os.urandom(32)).decode(),
                },
            )
        ).json()
        ids.append(d["id"])
    today = utcnow().date()
    for n, did in enumerate(ids):
        db.add(
            DeviceUsageDaily(
                device_id=did,
                day=today - dt.timedelta(days=n),
                download_bytes=(n + 1) * GB,
                upload_bytes=n,
            )
        )
    db.add(
        DeviceUsageDaily(
            device_id=ids[0], day=today - dt.timedelta(days=200), download_bytes=GB, upload_bytes=0
        )
    )
    await db.commit()
    r = (await client.get("/api/v1/vpn/usage?days=30", headers=user.headers)).json()
    assert len(r["top_devices"]) == 5
    totals = [d["download"] for d in r["top_devices"]]
    assert totals == sorted(totals, reverse=True) and totals[0] == 7 * GB
    assert sum(p["download"] for p in r["series"]) == sum((n + 1) * GB for n in range(7))
    async with ctx.sessionmaker() as s:
        assert await vpn.purge_old_usage(s, keep_days=90) == 1


# --- referrals -------------------------------------------------------------------------------
async def test_referral_link_and_claim_rules(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    alice = await new_user(client, outbox, "ref-a@example.com")
    bob = await new_user(client, outbox, "ref-b@example.com")
    carol = await new_user(client, outbox, "ref-c@example.com")
    info = (await client.get("/api/v1/referrals", headers=alice.headers)).json()
    assert len(info["code"]) == 8 and info["percent_off"] == 30
    assert info["link"] == f"https://t.me/vpnhub_bot?start=ref_{info['code']}"
    assert (await client.get("/api/v1/referrals", headers=alice.headers)).json()["code"] == info[
        "code"
    ]  # stable
    code = info["code"]
    claim = "/api/v1/referrals/claim"
    assert (await client.post(claim, headers=alice.headers, json={"code": code})).status_code == 422
    assert (
        await client.post(claim, headers=bob.headers, json={"code": "ZZZZZZZZ"})
    ).status_code == 422
    assert (
        await client.post(claim, headers=bob.headers, json={"code": code.lower()})
    ).status_code == 204
    assert (await client.post(claim, headers=bob.headers, json={"code": code})).status_code == 204
    c_code = (await client.get("/api/v1/referrals", headers=carol.headers)).json()["code"]
    r = await client.post(claim, headers=bob.headers, json={"code": c_code})
    assert r.status_code == 422  # already referred by someone else
    stats = (await client.get("/api/v1/referrals", headers=alice.headers)).json()
    assert stats["invited"] == 1 and stats["paid"] == 0
    bob_row = await db.scalar(select(User).where(User.email == "ref-b@example.com"))
    assert str(bob_row.referred_by_id) == alice.user_id


async def test_referral_reward_full_cycle(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay, ctx: AppContext
) -> None:
    prices = await seed(db)
    alice = await new_user(client, outbox, "cyc-a@example.com")
    bob = await new_user(client, outbox, "cyc-b@example.com")
    code = (await client.get("/api/v1/referrals", headers=alice.headers)).json()["code"]
    await client.post("/api/v1/referrals/claim", headers=bob.headers, json={"code": code})

    # Bob pays → Alice earns one reward + 14 free days (she had no subscription → a new one
    # on the plan Bob bought) and is notified
    await checkout(client, bob, prices[1])
    fake.pay(fake._next)
    outbox.clear()
    async with ctx.sessionmaker() as s:
        assert await payments.poll_pending(ctx, s) == {"credited": 1}
    assert {m.template for m in outbox} == {"payment_received", "referral_reward_bonus"}
    notice = next(m for m in outbox if m.template == "referral_reward_bonus")
    assert notice.to == "cyc-a@example.com"
    assert "14 free days" in notice.subject and "30% off" in notice.subject
    async with ctx.sessionmaker() as s:
        live = await subs.get_live(s, alice.user_id)
        assert live is not None and live.provider == "promo"
        left = live.current_period_end - utcnow()
        assert dt.timedelta(days=13, hours=23) < left <= dt.timedelta(days=14)
        assert (await s.get(Plan, live.plan_id)).code == "standard"
    stats = (await client.get("/api/v1/referrals", headers=alice.headers)).json()
    assert stats["paid"] == 1 and stats["rewards_available"] == 1
    assert stats["bonus_days"] == 14 and stats["days_earned"] == 14
    # a second payment by Bob doesn't earn another reward
    await checkout(client, bob, prices[3])
    fake.pay(fake._next)
    async with ctx.sessionmaker() as s:
        await payments.poll_pending(ctx, s)
    assert len((await db.scalars(select(ReferralReward))).all()) == 1
    async with ctx.sessionmaker() as s:  # ...and no more free days either
        again = await subs.get_live(s, alice.user_id)
        assert again is not None and again.current_period_end == live.current_period_end

    # Alice's checkout gets 30 % off automatically; the reward is reserved for that invoice
    r = (await checkout(client, alice, prices[12])).json()
    assert r["amount_minor"] == 4200 - 1260 and r["discount"] == "referral"
    r2 = (await checkout(client, alice, prices[1])).json()
    assert r2["amount_minor"] == 500 and r2["discount"] is None  # only one reward, already held
    # the first invoice expires → reward released → next checkout discounted again
    from app.models import Payment

    first = await db.get(Payment, r["id"])
    fake.invoices[int(first.provider_payment_id)]["status"] = "expired"
    async with ctx.sessionmaker() as s:
        await payments.poll_pending(ctx, s)
    reward = await db.scalar(select(ReferralReward))
    await db.refresh(reward)
    assert reward.status == "available"
    r3 = (await checkout(client, alice, prices[6])).json()
    assert r3["amount_minor"] == 2400 - 720 and r3["discount"] == "referral"
    fake.pay(fake._next)
    async with ctx.sessionmaker() as s:
        await payments.poll_pending(ctx, s)
    await db.refresh(reward)
    assert reward.status == "used"
    stats = (await client.get("/api/v1/referrals", headers=alice.headers)).json()
    assert stats["rewards_available"] == 0 and stats["rewards_used"] == 1
    # after paying, nobody can attach a referrer to Bob any more
    dave = await new_user(client, outbox, "cyc-d@example.com")
    d_code = (await client.get("/api/v1/referrals", headers=dave.headers)).json()["code"]
    await db.execute(
        update(User).where(User.email == "cyc-b@example.com").values(referred_by_id=None)
    )
    await db.commit()
    r = await client.post("/api/v1/referrals/claim", headers=bob.headers, json={"code": d_code})
    assert r.status_code == 422


async def test_promo_code_beats_referral_reward(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay
) -> None:
    from app.models import PromoCode

    prices = await seed(db)
    alice = await new_user(client, outbox, "pr-a@example.com")
    db.add(ReferralReward(referrer_id=alice.user_id, percent_off=30, status="available"))
    db.add(PromoCode(code="HALF", kind="percent_off", percent_off=50))
    await db.commit()
    r = (await checkout(client, alice, prices[1], promo="HALF")).json()
    assert r["amount_minor"] == 250 and r["discount"] == "promo"
    reward = await db.scalar(select(ReferralReward))
    assert reward.status == "available"  # untouched, still usable next time


async def test_referrals_can_be_disabled(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay, ctx: AppContext
) -> None:
    from app.services import settings as settings_service

    prices = await seed(db)
    await settings_service.set_value(db, "referrals.enabled", False, actor_id=None)
    await db.commit()
    alice = await new_user(client, outbox, "dis-a@example.com")
    bob = await new_user(client, outbox, "dis-b@example.com")
    code = (await client.get("/api/v1/referrals", headers=alice.headers)).json()["code"]
    await client.post("/api/v1/referrals/claim", headers=bob.headers, json={"code": code})
    await checkout(client, bob, prices[1])
    fake.pay(fake._next)
    async with ctx.sessionmaker() as s:
        await payments.poll_pending(ctx, s)
    assert await db.scalar(select(ReferralReward)) is None


async def _refer(client: AsyncClient, referrer: Any, invitee: Any) -> None:
    code = (await client.get("/api/v1/referrals", headers=referrer.headers)).json()["code"]
    r = await client.post("/api/v1/referrals/claim", headers=invitee.headers, json={"code": code})
    assert r.status_code == 204


async def _pay(
    client: AsyncClient, fake: FakeCryptoPay, ctx: AppContext, who: Any, price: Any
) -> None:
    await checkout(client, who, price)
    fake.pay(fake._next)
    async with ctx.sessionmaker() as s:
        assert await payments.poll_pending(ctx, s) == {"credited": 1}


async def test_referral_bonus_days_extend_existing_subscription(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay, ctx: AppContext
) -> None:
    prices = await seed(db)
    alice = await new_user(client, outbox, "bd-a@example.com")
    bob = await new_user(client, outbox, "bd-b@example.com")
    carol = await new_user(client, outbox, "bd-c@example.com")
    trial_user = await new_user(client, outbox, "bd-t@example.com")
    dave = await new_user(client, outbox, "bd-d@example.com")
    standard = await db.scalar(select(Plan).where(Plan.code == "standard"))
    trial = await db.scalar(select(Plan).where(Plan.code == "trial"))
    # Alice already pays for 30 days; the trial user is on a 3-day trial
    for uid, plan, days in ((alice.user_id, standard, 30), (trial_user.user_id, trial, 3)):
        await subs.grant_days(
            db,
            user_id=uid,
            plan=plan,
            days=days,
            provider=Provider.CRYPTOBOT,
            actor_id=None,
            actor_type=ActorType.SYSTEM,
            ip=None,
        )
    await db.commit()
    async with ctx.sessionmaker() as s:
        before = (await subs.get_live(s, alice.user_id)).current_period_end

    # two invitees pay → +14 days each, on top of the existing end date
    await _refer(client, alice, bob)
    await _refer(client, alice, carol)
    await _pay(client, fake, ctx, bob, prices[1])
    await _pay(client, fake, ctx, carol, prices[3])
    async with ctx.sessionmaker() as s:
        after = await subs.get_live(s, alice.user_id)
        assert after.current_period_end - before == dt.timedelta(days=28)
        assert after.plan_id == standard.id
    stats = (await client.get("/api/v1/referrals", headers=alice.headers)).json()
    assert stats["paid"] == 2 and stats["days_earned"] == 28 and stats["rewards_available"] == 2

    # a referrer on a trial is moved to the paid plan the invitee bought
    await _refer(client, trial_user, dave)
    await _pay(client, fake, ctx, dave, prices[1])
    async with ctx.sessionmaker() as s:
        t = await subs.get_live(s, trial_user.user_id)
        assert t.plan_id == standard.id
        assert t.current_period_end - utcnow() > dt.timedelta(days=16, hours=23)


async def test_referral_bonus_days_off_and_suspended_referrer(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay, ctx: AppContext
) -> None:
    from app.services import settings as settings_service

    prices = await seed(db)
    alice = await new_user(client, outbox, "bo-a@example.com")
    bob = await new_user(client, outbox, "bo-b@example.com")
    sus = await new_user(client, outbox, "bo-s@example.com")
    carol = await new_user(client, outbox, "bo-c@example.com")
    await _refer(client, alice, bob)
    await _refer(client, sus, carol)

    await settings_service.set_value(db, "referrals.bonus_days", 0, actor_id=None)
    await db.commit()
    outbox.clear()
    await _pay(client, fake, ctx, bob, prices[1])
    assert {m.template for m in outbox} == {"payment_received", "referral_reward"}
    async with ctx.sessionmaker() as s:
        assert await subs.get_live(s, alice.user_id) is None  # discount only
    stats = (await client.get("/api/v1/referrals", headers=alice.headers)).json()
    assert (
        stats["bonus_days"] == 0 and stats["days_earned"] == 0 and stats["rewards_available"] == 1
    )

    await settings_service.set_value(db, "referrals.bonus_days", 14, actor_id=None)
    await db.execute(update(User).where(User.id == sus.user_id).values(status="suspended"))
    await db.commit()
    await _pay(client, fake, ctx, carol, prices[1])
    async with ctx.sessionmaker() as s:
        assert await subs.get_live(s, sus.user_id) is None
        reward = await s.scalar(
            select(ReferralReward).where(ReferralReward.referrer_id == sus.user_id)
        )
        assert reward is not None and reward.bonus_days == 0
