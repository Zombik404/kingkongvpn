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
from app.models import DeviceUsageDaily, Plan, ReferralMilestone, ReferralReward, User
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
        rate_limit_enabled=False,  # rank tests sign up many friends from one test client
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
    assert stats["invited"] == 1 and stats["paid"] == 0 and stats["my_discount"] == 0
    bob_info = (await client.get("/api/v1/referrals", headers=bob.headers)).json()
    assert bob_info["my_discount"] == 30
    bob_row = await db.scalar(select(User).where(User.email == "ref-b@example.com"))
    assert str(bob_row.referred_by_id) == alice.user_id


async def _refer(client: AsyncClient, referrer: Any, invitee: Any) -> None:
    code = (await client.get("/api/v1/referrals", headers=referrer.headers)).json()["code"]
    r = await client.post("/api/v1/referrals/claim", headers=invitee.headers, json={"code": code})
    assert r.status_code == 204


async def _pay(
    client: AsyncClient, fake: FakeCryptoPay, ctx: AppContext, who: Any, price: Any
) -> dict[str, Any]:
    r = (await checkout(client, who, price)).json()
    fake.pay(fake._next)
    async with ctx.sessionmaker() as s:
        assert await payments.poll_pending(ctx, s) == {"credited": 1}
    return r


async def test_referral_full_cycle(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay, ctx: AppContext
) -> None:
    prices = await seed(db)
    alice = await new_user(client, outbox, "cyc-a@example.com")
    bob = await new_user(client, outbox, "cyc-b@example.com")
    await _refer(client, alice, bob)

    # Bob (invited) gets 30 % off his first checkout; Alice (referrer) gets nothing off
    r = (await checkout(client, bob, prices[12])).json()
    assert r["amount_minor"] == 4200 - 1260 and r["discount"] == "referral"
    a = (await checkout(client, alice, prices[1])).json()
    assert a["amount_minor"] == 500 and a["discount"] is None
    # Bob's first invoice expires → his discount is still there (he hasn't paid yet)
    from app.models import Payment

    first = await db.get(Payment, r["id"])
    fake.invoices[int(first.provider_payment_id)]["status"] = "expired"
    async with ctx.sessionmaker() as s:
        await payments.poll_pending(ctx, s)

    # Bob pays a discounted 1-month plan → Alice gets +14 days (no subscription before → a new
    # one on the plan Bob bought) and a notice
    outbox.clear()
    paid = await _pay(client, fake, ctx, bob, prices[1])
    assert paid["amount_minor"] == 350 and paid["discount"] == "referral"
    assert {m.template for m in outbox} == {"payment_received", "referral_reward"}
    notice = next(m for m in outbox if m.template == "referral_reward")
    assert notice.to == "cyc-a@example.com" and "14 free days" in notice.subject
    async with ctx.sessionmaker() as s:
        live = await subs.get_live(s, alice.user_id)
        assert live is not None and live.provider == "promo"
        left = live.current_period_end - utcnow()
        assert dt.timedelta(days=13, hours=23) < left <= dt.timedelta(days=14)
        assert (await s.get(Plan, live.plan_id)).code == "standard"
    stats = (await client.get("/api/v1/referrals", headers=alice.headers)).json()
    assert stats["invited"] == 1 and stats["paid"] == 1 and stats["bonus_days"] == 14

    # Bob's next payment: full price, and no more days for Alice
    nxt = await _pay(client, fake, ctx, bob, prices[3])
    assert nxt["amount_minor"] == 1300 and nxt["discount"] is None
    assert (await client.get("/api/v1/referrals", headers=bob.headers)).json()["my_discount"] == 0
    assert len((await db.scalars(select(ReferralReward))).all()) == 1
    async with ctx.sessionmaker() as s:
        again = await subs.get_live(s, alice.user_id)
        assert again.current_period_end == live.current_period_end

    # after paying, nobody can attach a referrer to Bob any more
    dave = await new_user(client, outbox, "cyc-d@example.com")
    d_code = (await client.get("/api/v1/referrals", headers=dave.headers)).json()["code"]
    await db.execute(
        update(User).where(User.email == "cyc-b@example.com").values(referred_by_id=None)
    )
    await db.commit()
    r = await client.post("/api/v1/referrals/claim", headers=bob.headers, json={"code": d_code})
    assert r.status_code == 422


async def test_promo_code_beats_referral_discount(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay
) -> None:
    from app.models import PromoCode

    prices = await seed(db)
    alice = await new_user(client, outbox, "pr-a@example.com")
    bob = await new_user(client, outbox, "pr-b@example.com")
    await _refer(client, alice, bob)
    db.add(PromoCode(code="HALF", kind="percent_off", percent_off=50))
    await db.commit()
    r = (await checkout(client, bob, prices[1], promo="HALF")).json()
    assert r["amount_minor"] == 250 and r["discount"] == "promo"


async def test_referrals_can_be_disabled(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay, ctx: AppContext
) -> None:
    from app.services import settings as settings_service

    prices = await seed(db)
    alice = await new_user(client, outbox, "dis-a@example.com")
    bob = await new_user(client, outbox, "dis-b@example.com")
    await _refer(client, alice, bob)
    await settings_service.set_value(db, "referrals.enabled", False, actor_id=None)
    await db.commit()
    paid = await _pay(client, fake, ctx, bob, prices[1])
    assert paid["amount_minor"] == 500 and paid["discount"] is None
    assert await db.scalar(select(ReferralReward)) is None
    async with ctx.sessionmaker() as s:
        assert await subs.get_live(s, alice.user_id) is None


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

    # two invited friends pay → +14 days each, on top of the existing end date
    await _refer(client, alice, bob)
    await _refer(client, alice, carol)
    await _pay(client, fake, ctx, bob, prices[1])
    await _pay(client, fake, ctx, carol, prices[3])
    async with ctx.sessionmaker() as s:
        after = await subs.get_live(s, alice.user_id)
        assert after.current_period_end - before == dt.timedelta(days=28)
        assert after.plan_id == standard.id
    stats = (await client.get("/api/v1/referrals", headers=alice.headers)).json()
    assert stats["invited"] == 2 and stats["paid"] == 2

    # a referrer on a trial is moved to the paid plan the friend bought
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

    # bonus days off: the friend still gets the discount, the referrer gets no days/no notice
    await settings_service.set_value(db, "referrals.bonus_days", 0, actor_id=None)
    await db.commit()
    outbox.clear()
    paid = await _pay(client, fake, ctx, bob, prices[1])
    assert paid["discount"] == "referral"
    assert {m.template for m in outbox} == {"payment_received"}
    async with ctx.sessionmaker() as s:
        assert await subs.get_live(s, alice.user_id) is None
    assert (await client.get("/api/v1/referrals", headers=alice.headers)).json()["paid"] == 1

    # a suspended referrer gets nothing; the invited friend still gets the discount
    await settings_service.set_value(db, "referrals.bonus_days", 14, actor_id=None)
    await db.execute(update(User).where(User.id == sus.user_id).values(status="suspended"))
    await db.commit()
    paid = await _pay(client, fake, ctx, carol, prices[1])
    assert paid["discount"] == "referral"
    async with ctx.sessionmaker() as s:
        assert await subs.get_live(s, sus.user_id) is None
        reward = await s.scalar(
            select(ReferralReward).where(ReferralReward.referrer_id == sus.user_id)
        )
        assert reward is not None and reward.bonus_days == 0


async def test_referral_ranks_gifts_and_themes(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay, ctx: AppContext
) -> None:
    prices = await seed(db)
    boss = await new_user(client, outbox, "rank-boss@example.com")
    info = (await client.get("/api/v1/referrals", headers=boss.headers)).json()
    assert info["rank"] == "chick" and info["themes"] == []
    assert info["next_level"] == {
        "code": "fox",
        "need": 3,
        "days": 7,
        "theme": "lava",
        "reached": False,
    }
    assert [lv["need"] for lv in info["levels"]] == [3, 5, 10, 25]

    friends = [await new_user(client, outbox, f"rank-f{i}@example.com") for i in range(5)]
    for f in friends:
        await _refer(client, boss, f)
    await _pay(client, fake, ctx, friends[0], prices[1])
    await _pay(client, fake, ctx, friends[1], prices[1])
    async with ctx.sessionmaker() as s:
        before = (await subs.get_live(s, boss.user_id)).current_period_end

    # 3rd paying friend → rank "fox": +14 (per friend) +7 (rank gift), theme "lava", a notice
    outbox.clear()
    await _pay(client, fake, ctx, friends[2], prices[1])
    assert sorted(m.template for m in outbox) == [
        "payment_received",
        "referral_milestone",
        "referral_reward",
    ]
    notice = next(m for m in outbox if m.template == "referral_milestone")
    assert notice.to == "rank-boss@example.com"
    assert (
        "Parrot" in notice.subject
        and "+7 free VPN days" in notice.text
        and "Volcano" in notice.text
    )
    async with ctx.sessionmaker() as s:
        after = (await subs.get_live(s, boss.user_id)).current_period_end
    assert after - before == dt.timedelta(days=21)
    info = (await client.get("/api/v1/referrals", headers=boss.headers)).json()
    assert info["rank"] == "fox" and info["themes"] == ["lava"] and info["paid"] == 3
    assert info["next_level"]["code"] == "hacker"

    # 4th: no new rank; 5th: "hacker" (+30 days, theme "matrix")
    await _pay(client, fake, ctx, friends[3], prices[1])
    outbox.clear()
    await _pay(client, fake, ctx, friends[4], prices[1])
    assert "referral_milestone" in {m.template for m in outbox}
    async with ctx.sessionmaker() as s:
        end = (await subs.get_live(s, boss.user_id)).current_period_end
    assert end - after == dt.timedelta(days=14 + 14 + 30)
    info = (await client.get("/api/v1/referrals", headers=boss.headers)).json()
    assert info["rank"] == "hacker" and info["themes"] == ["lava", "matrix"]
    rows = (await db.scalars(select(ReferralMilestone.level))).all()
    assert sorted(rows) == ["fox", "hacker"]  # each gift exactly once


async def test_referral_ranks_can_be_disabled(
    client: AsyncClient, outbox: list[Any], db: Any, fake: FakeCryptoPay, ctx: AppContext
) -> None:
    from app.services import settings as settings_service

    prices = await seed(db)
    await settings_service.set_value(db, "referrals.milestones", False, actor_id=None)
    await db.commit()
    boss = await new_user(client, outbox, "nr-boss@example.com")
    for i in range(3):
        f = await new_user(client, outbox, f"nr-f{i}@example.com")
        await _refer(client, boss, f)
        await _pay(client, fake, ctx, f, prices[1])
    assert await db.scalar(select(ReferralMilestone)) is None
    info = (await client.get("/api/v1/referrals", headers=boss.headers)).json()
    assert info["rank"] == "chick" and info["next_level"] is None and info["paid"] == 3


async def test_vpn_status_by_request_origin(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    from httpx import ASGITransport

    from app.main import create_app

    await register_node(ipv4="198.51.100.77")
    user, dev = await entitled_user_with_device(client, outbox, db, "st@example.com")

    async def status_from(ip: str) -> dict[str, Any]:
        transport = ASGITransport(app=create_app(ctx.settings, ctx=ctx), client=(ip, 40000))
        async with AsyncClient(transport=transport, base_url="http://api.test") as c:
            r = await c.get("/api/v1/vpn/status", headers=user.headers)
            assert r.status_code == 200, r.text
            return r.json()

    off = await status_from("203.0.113.200")
    assert off == {"protected": False, "via": None, "device_id": None, "device_name": None}
    # through the tunnel, from this user's device address
    on = await status_from(dev["ipv4"])
    assert on["protected"] and on["via"] == "tunnel" and on["device_id"] == dev["id"]
    assert on["device_name"] == "phone"
    v6 = await status_from(dev["ipv6"])
    assert v6["via"] == "tunnel" and v6["device_id"] == dev["id"]
    # another tunnel address: protected, but not one of this user's devices
    other = await status_from("10.64.9.9")
    assert other["protected"] and other["device_id"] is None
    # API on another host: traffic leaves through a node's public address
    exit_ = await status_from("198.51.100.77")
    assert exit_["protected"] and exit_["via"] == "exit"
    assert (await client.get("/api/v1/vpn/status")).status_code == 401
