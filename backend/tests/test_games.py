"""Jungle Kong Blackjack on the real stack: API, bonus wallet, tables, timers, admin."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.api.v1.games import room_updates
from app.core.config import Settings
from app.core.context import AppContext
from app.games import fair, wallet
from app.games import service as games
from app.models import (
    AuditLog,
    BonusLedger,
    GameRoom,
    GameRoomPlayer,
    GameRound,
    Plan,
    Subscription,
)
from app.models.base import utcnow
from app.models.enums import ActorType, Provider
from app.services import settings as settings_service
from app.subscriptions import service as subs
from tests.conftest import make_settings
from tests.helpers import new_user, staff

G = "/api/v1/games"
AG = "/api/v1/admin/games"
FILL = ["5D", "6C", "7H", "4S", "9D", "3C"] * 8


@pytest.fixture
def settings() -> Settings:
    return make_settings(rate_limit_enabled=False)


def rig(monkeypatch: pytest.MonkeyPatch, *cards: str) -> None:
    """Fix the shoe. Order: each player's first card, dealer up, each second card, dealer hole,
    then draws."""
    monkeypatch.setattr(games.fair, "shuffled_shoe", lambda *a, **k: [*cards, *FILL])


def plain_seed() -> str:
    """A server seed whose first round (client seed "0=my-seed") has no blackjack and no dealer
    ace or ten showing, so the round needs a player decision."""
    from app.games import blackjack as bj

    for i in range(1000):
        seed = f"{i:064x}"
        p1, up, p2, _hole = fair.shuffled_shoe(seed, "0=my-seed", 1, 6)[:4]
        if bj.hand_total([p1, p2])[0] < 21 and bj.card_value(up) < 10:
            return seed
    raise AssertionError("no seed found")


async def setting(db: Any, key: str, value: Any) -> None:
    await settings_service.set_value(db, key, value, actor_id=None)
    await db.commit()


async def stakes_on(db: Any) -> None:
    await setting(db, "games.blackjack.stakes_enabled", True)


async def give(db: Any, user: Any, days: int) -> None:
    await wallet.move(db, uuid.UUID(user.user_id), days * 24, "admin", f"test:{uuid.uuid4()}")
    await db.commit()


async def balance(client: AsyncClient, user: Any) -> int:
    return int((await client.get(f"{G}/wallet", headers=user.headers)).json()["balance_hours"])


async def post(
    client: AsyncClient, user: Any, path: str, body: dict[str, Any] | None = None
) -> Any:
    return await client.post(f"{G}{path}", headers=user.headers, json=body or {})


async def solo(client: AsyncClient, user: Any) -> dict[str, Any]:
    r = await post(client, user, "/rooms/solo")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def bet(client: AsyncClient, user: Any, room: str, days: int = 0, **extra: Any) -> Any:
    return await post(client, user, f"/rooms/{room}/bet", {"stake_days": days, **extra})


async def do(client: AsyncClient, user: Any, room: str, action: str, **extra: Any) -> Any:
    return await post(client, user, f"/rooms/{room}/actions", {"action": action, **extra})


# ----------------------------------------------------------------------------- fun mode
async def test_fun_mode_solo_round_history_and_fairness(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a real (unrigged) shuffle, but from a known server seed that deals an ordinary hand
    seeds = iter([plain_seed(), "ab" * 32, "cd" * 32])
    monkeypatch.setattr(games.fair, "new_server_seed", lambda: next(seeds))
    u = await new_user(client, outbox, "fun@example.com")
    hub = (await client.get(G, headers=u.headers)).json()
    assert (
        hub["enabled"]
        and not hub["stakes"]
        and hub["balance_hours"] == 0
        and hub["room_id"] is None
    )
    assert hub["profile"]["rounds"] == 0 and hub["rules"]["decks"] == 6
    table = await solo(client, u)
    rid, seed_hash = table["id"], table["next_seed_hash"]
    assert (
        table["phase"] == "waiting"
        and table["max_players"] == 1
        and table["stake_options_days"] == []
    )
    assert (await solo(client, u))["id"] == rid  # the same table again
    assert (await client.get(G, headers=u.headers)).json()["room_id"] == rid

    v = (
        await bet(client, u, rid, 5, client_seed="my-seed")
    ).json()  # the stake is ignored in fun mode
    assert v["phase"] == "playing" and v["round"]["dealer"]["cards"][1] == "??"
    assert v["me"]["actions"][:2] == ["hit", "stand"] and v["players"][0]["me"]
    raw = str(v)
    assert "deck" not in raw and "next_seed'" not in raw and "server_seed'" not in raw
    room = await db.get(GameRoom, uuid.UUID(rid))
    secret, hole = room.state["next_seed"], room.state["round"]["dealer"]["cards"][1]
    assert hole not in str(v["round"]["dealer"]) and secret not in raw

    v = (await do(client, u, rid, "stand")).json()
    assert v["phase"] == "settled" and v["round"]["dealer"]["cards"][1] == hole
    result = v["round"]["results"]["seats"][0]
    assert result["net"] == 0 and result["result"] in ("win", "lose", "push")
    assert await balance(client, u) == 0 and not (await db.scalars(select(BonusLedger))).all()

    # provably fair: the hash was shown before the bet; the revealed seed reproduces the cards
    f = v["last_fair"]
    assert fair.seed_hash(f["server_seed"]) == seed_hash == f["server_seed_hash"]
    assert f["client_seed"] == "0=my-seed"
    shoe = fair.shuffled_shoe(f["server_seed"], f["client_seed"], f["number"], f["decks"])
    hand = v["round"]["seats"][0]["hands"][0]["cards"]
    assert [shoe[0], shoe[2]] == hand[:2] and [shoe[1], shoe[3]] == v["round"]["dealer"]["cards"][
        :2
    ]
    api = (await client.get(f"{G}/rounds/{f['round_id']}/fairness", headers=u.headers)).json()
    assert api["server_seed"] == f["server_seed"] and api["summary"]["dealer"]["cards"][1] == hole
    assert v["next_seed_hash"] != seed_hash  # a new commitment for the next round

    hist = (await client.get(f"{G}/history", headers=u.headers)).json()
    assert len(hist) == 1 and hist[0]["result"] == result["result"] and hist[0]["staked_hours"] == 0
    prof = (await client.get(G, headers=u.headers)).json()["profile"]
    assert prof["rounds"] == 1 and prof["wins"] + prof["losses"] + prof["pushes"] == 1
    other = await new_user(client, outbox, "nosy@example.com")
    assert (
        await client.get(f"{G}/rounds/{f['round_id']}/fairness", headers=other.headers)
    ).status_code == 404
    assert (await client.get(G)).status_code == 401


async def test_profile_nickname_is_sanitised(client: AsyncClient, outbox: list[Any]) -> None:
    u = await new_user(client, outbox, "nick@example.com")
    r = await client.put(
        f"{G}/profile", headers=u.headers, json={"nickname": "  Kong‮ \n the   Great" + "x" * 40}
    )
    assert r.json()["nickname"] == "Kong the Greatxxxxxxxxxx"
    assert (
        await client.put(f"{G}/profile", headers=u.headers, json={"nickname": ""})
    ).status_code == 422


# ----------------------------------------------------------------------------- stakes & wallet
async def test_stakes_win_lose_push_blackjack(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await stakes_on(db)
    u = await new_user(client, outbox, "stake@example.com")
    await give(db, u, 5)
    rid = (await solo(client, u))["id"]
    assert (await solo(client, u))["stake_options_days"] == [1, 2, 3, 5]

    rig(monkeypatch, "TS", "9D", "8H", "8C")  # 18 vs 17: win
    v = (await bet(client, u, rid, 1)).json()
    assert v["me"]["balance_hours"] == 96 and v["round"]["seats"][0]["bet"] == 24
    v = (await do(client, u, rid, "stand")).json()
    assert v["round"]["results"]["seats"][0]["net"] == 24 and v["me"]["balance_hours"] == 144

    rig(monkeypatch, "TS", "9D", "6H", "8C")  # 16 vs 17: lose
    await bet(client, u, rid, 2)
    assert (await do(client, u, rid, "stand")).json()["me"]["balance_hours"] == 96

    rig(monkeypatch, "TS", "9D", "7H", "8C")  # push: the stake comes back
    await bet(client, u, rid, 1)
    assert (await do(client, u, rid, "stand")).json()["me"]["balance_hours"] == 96

    rig(monkeypatch, "AS", "9D", "KH", "8C")  # blackjack pays 3:2 → +1.5 days, no action needed
    v = (await bet(client, u, rid, 1)).json()
    assert v["phase"] == "settled" and v["round"]["results"]["seats"][0]["blackjack"]
    assert v["me"]["balance_hours"] == 132

    kinds = [
        r.kind
        for r in (await db.scalars(select(BonusLedger).order_by(BonusLedger.created_at))).all()
    ]
    assert kinds == ["admin", "stake", "payout", "stake", "stake", "payout", "stake", "payout"]
    w = (await client.get(f"{G}/wallet", headers=u.headers)).json()
    assert w["ledger"][0]["delta_hours"] == 60 and w["ledger"][0]["balance_after"] == 132
    prof = (await client.get(G, headers=u.headers)).json()["profile"]
    assert (
        prof["wins"],
        prof["losses"],
        prof["pushes"],
        prof["blackjacks"],
        prof["net_hours"],
    ) == (2, 1, 1, 1, 12)
    hist = (await client.get(f"{G}/history", headers=u.headers)).json()
    assert [h["net_hours"] for h in hist] == [36, 0, -48, 24]


async def test_stake_validation_and_no_negative_balance(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await stakes_on(db)
    u = await new_user(client, outbox, "poor@example.com")
    rid = (await solo(client, u))["id"]
    r = await bet(client, u, rid, 1)
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_bonus"
    assert (await bet(client, u, rid, 4)).json()["error"]["code"] == "bad_stake"
    assert (await bet(client, u, rid, 0)).json()["error"]["code"] == "bad_stake"
    assert (await solo(client, u))["phase"] == "waiting" and await balance(client, u) == 0

    await give(db, u, 1)
    rig(monkeypatch, "5S", "9D", "6H", "8C", "TD")  # 11: would love to double, but can't afford it
    v = (await bet(client, u, rid, 1)).json()
    assert "double" not in v["me"]["actions"] and v["me"]["balance_hours"] == 0
    r = await do(client, u, rid, "double")
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_bonus"
    assert (await solo(client, u))["phase"] == "playing"  # nothing changed
    assert (await do(client, u, rid, "hit")).json()["me"]["balance_hours"] == 48  # 21 wins

    await setting(db, "games.blackjack.daily_win_cap_days", 1)
    assert (await bet(client, u, rid, 1)).json()["error"]["code"] == "daily_cap"


async def test_double_split_surrender_insurance_move_the_wallet(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await stakes_on(db)
    u = await new_user(client, outbox, "moves@example.com")
    await give(db, u, 10)
    rid = (await solo(client, u))["id"]

    rig(monkeypatch, "5S", "9D", "6H", "8C", "TD")  # double 11 → 21 vs 17
    v = (await bet(client, u, rid, 1)).json()
    assert v["me"]["extra_hours"]["double"] == 24
    v = (await do(client, u, rid, "double")).json()
    assert v["me"]["balance_hours"] == 240 + 48  # staked 2 days, got 4 back

    rig(monkeypatch, "8S", "9D", "8H", "8C", "3D", "TS", "KD")  # split 8s: 21 and 18 vs 17
    v = (await bet(client, u, rid, 1)).json()
    assert "split" in v["me"]["actions"]
    v = (await do(client, u, rid, "split")).json()
    assert len(v["round"]["seats"][0]["hands"]) == 2 and v["me"]["balance_hours"] == 288 - 48
    await do(client, u, rid, "hit")
    v = (await do(client, u, rid, "stand")).json()
    assert v["phase"] == "settled" and v["me"]["balance_hours"] == 288 + 48

    rig(monkeypatch, "TS", "9D", "6H", "8C")  # surrender: half back
    await bet(client, u, rid, 2)
    assert (await do(client, u, rid, "surrender")).json()["me"]["balance_hours"] == 336 - 24

    rig(monkeypatch, "TS", "AD", "9H", "KC")  # insurance against a dealer blackjack: even
    v = (await bet(client, u, rid, 2)).json()
    assert v["phase"] == "insurance" and v["me"]["actions"] == ["insurance", "no_insurance"]
    v = (await do(client, u, rid, "insurance")).json()
    assert v["phase"] == "settled" and v["me"]["balance_hours"] == 312
    assert v["round"]["results"]["seats"][0]["insurance_won"]

    await setting(db, "games.blackjack.allow_double", False)
    await setting(db, "games.blackjack.allow_surrender", False)
    rig(monkeypatch, "5S", "9D", "6H", "8C", "TD")
    v = (await bet(client, u, rid, 1)).json()
    assert v["me"]["actions"] == ["hit", "stand"]
    assert (await do(client, u, rid, "double")).json()["error"]["code"] == "not_allowed"


async def test_paid_subscription_is_never_touched_and_redeem_is_one_way(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.cli import bootstrap_catalog

    await bootstrap_catalog()
    await stakes_on(db)
    u = await new_user(client, outbox, "paid@example.com")
    uid = uuid.UUID(u.user_id)
    plan = await db.scalar(select(Plan).where(Plan.code == "standard"))
    await subs.grant_days(
        db,
        user_id=uid,
        plan=plan,
        days=30,
        provider=Provider.CRYPTOBOT,
        actor_id=None,
        actor_type=ActorType.SYSTEM,
        ip=None,
    )
    await db.commit()

    async def paid_until() -> dt.datetime:
        async with ctx_session(db) as s:
            return (
                await s.scalar(select(Subscription).where(Subscription.user_id == uid))
            ).current_period_end

    end = await paid_until()
    rid = (await solo(client, u))["id"]
    # 30 paid days, zero bonus days: no stake is possible
    assert (await bet(client, u, rid, 1)).json()["error"]["code"] == "insufficient_bonus"
    await give(db, u, 3)
    for _ in range(3):  # lose all three bonus days
        rig(monkeypatch, "TS", "9D", "6H", "8C")
        await bet(client, u, rid, 1)
        await do(client, u, rid, "stand")
    assert await balance(client, u) == 0 and await paid_until() == end
    assert (await bet(client, u, rid, 1)).json()["error"]["code"] == "insufficient_bonus"
    assert await paid_until() == end

    # bonus days → VPN days: one way, whole days, idempotent
    await give(db, u, 3)
    body = {"days": 2, "action_id": "redeem-0001"}
    r = await post(client, u, "/wallet/redeem", body)
    assert r.status_code == 200 and r.json()["balance_hours"] == 24
    assert await paid_until() - end == dt.timedelta(days=2)
    assert (await post(client, u, "/wallet/redeem", body)).status_code == 200  # same request again
    assert await balance(client, u) == 24 and await paid_until() - end == dt.timedelta(days=2)
    r = await post(client, u, "/wallet/redeem", {"days": 2, "action_id": "redeem-0002"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_bonus"
    assert await paid_until() - end == dt.timedelta(days=2)
    await setting(db, "games.bonus_redeem_enabled", False)
    r = await post(client, u, "/wallet/redeem", {"days": 1, "action_id": "redeem-0003"})
    assert r.json()["error"]["code"] == "redeem_disabled"
    assert (
        await db.scalar(select(AuditLog).where(AuditLog.action == "game.bonus_redeemed"))
        is not None
    )


def ctx_session(db: Any) -> Any:
    """A second session on the same engine (fresh view of committed data)."""
    from sqlalchemy.ext.asyncio import AsyncSession

    return AsyncSession(db.bind, expire_on_commit=False)


async def test_repeated_requests_do_not_repeat_effects(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await stakes_on(db)
    u = await new_user(client, outbox, "retry@example.com")
    await give(db, u, 5)
    rid = (await solo(client, u))["id"]
    rig(monkeypatch, "2S", "9D", "3H", "8C", "4D", "2H", "9S")
    a = (await bet(client, u, rid, 1, action_id="bet-00000001")).json()
    b = (await bet(client, u, rid, 1, action_id="bet-00000001")).json()
    assert a["me"]["balance_hours"] == b["me"]["balance_hours"] == 96 and b["round_no"] == 1
    assert (await bet(client, u, rid, 1)).json()["error"]["code"] == "round_in_progress"
    a = (await do(client, u, rid, "hit", action_id="hit-00000001")).json()
    b = (await do(client, u, rid, "hit", action_id="hit-00000001")).json()
    assert (
        len(a["round"]["seats"][0]["hands"][0]["cards"])
        == len(b["round"]["seats"][0]["hands"][0]["cards"])
        == 3
    )
    a = (await do(client, u, rid, "double", action_id="dbl-00000001")).status_code
    assert a == 409  # three cards: not allowed, and nothing was charged
    assert await balance(client, u) == 96
    stakes = (await db.scalars(select(BonusLedger).where(BonusLedger.kind == "stake"))).all()
    assert len(stakes) == 1
    # the payout key is per round: settling twice can't pay twice
    await do(client, u, rid, "hit")  # 11
    await do(client, u, rid, "hit")  # 20
    assert (await do(client, u, rid, "stand")).json()["round"]["results"]["seats"][0][
        "result"
    ] == "win"
    room = await db.get(GameRoom, uuid.UUID(rid), populate_existing=True)
    before = await balance(client, u)
    await wallet.move(db, uuid.UUID(u.user_id), 999, "payout", f"payout:{room.round_id}")
    await db.commit()
    assert await balance(client, u) == before


# ----------------------------------------------------------------------------- multiplayer
async def table_for(
    client: AsyncClient, outbox: list[Any], n: int, visibility: str = "private"
) -> Any:
    users = [
        await new_user(client, outbox, f"mp{n}-{i}-{visibility}@example.com") for i in range(n)
    ]
    r = await post(client, users[0], "/rooms", {"max_players": n, "visibility": visibility})
    assert r.status_code == 201, r.text
    room = r.json()
    for u in users[1:]:
        j = await post(client, u, "/rooms/join", {"code": room["code"]})
        assert j.status_code == 200, j.text
    return users, room["id"], room["code"]


@pytest.mark.parametrize("n", [2, 3, 4])
async def test_shared_table_round_for_every_player(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch, n: int
) -> None:
    users, rid, _ = await table_for(client, outbox, n)
    firsts, seconds = ["TS", "TH", "TD", "TC"][:n], ["8S", "8H", "8D", "9C"][:n]
    rig(monkeypatch, *firsts, "9D", *seconds, "8C")  # everyone 18 (last 19 with 4) vs dealer 17
    for i, u in enumerate(users):
        v = (await bet(client, u, rid)).json()
        assert v["phase"] == ("playing" if i == n - 1 else "betting")
        assert sum(p["ready"] for p in v["players"]) == (0 if i == n - 1 else i + 1)
    assert [p["seat"] for p in v["players"]] == list(range(n)) and len(v["round"]["seats"]) == n
    for i, u in enumerate(users):
        mine = (await client.get(f"{G}/rooms/{rid}", headers=u.headers)).json()
        assert mine["round"]["turn"] == {"seat": i, "hand": 0}
        assert mine["me"]["actions"] and mine["me"]["seat"] == i
        for other in users[i + 1 :]:  # nobody can play someone else's turn
            assert (await do(client, other, rid, "stand")).json()["error"]["code"] == "not_allowed"
            theirs = (await client.get(f"{G}/rooms/{rid}", headers=other.headers)).json()
            assert theirs["me"]["actions"] == [] and theirs["round"]["dealer"]["cards"][1] == "??"
        v = (await do(client, u, rid, "stand")).json()
    assert v["phase"] == "settled" and len(v["round"]["results"]["seats"]) == n
    assert all(s["result"] == "win" for s in v["round"]["results"]["seats"])
    for u in users:
        assert (await client.get(G, headers=u.headers)).json()["profile"]["wins"] == 1
        assert len((await client.get(f"{G}/history", headers=u.headers)).json()) == 1
    assert v["last_fair"]["client_seed"].count("=") == n
    board = (await client.get(f"{G}/leaderboard", headers=users[0].headers)).json()
    assert (
        len(board["top"]) == n and board["my_rank"] == 1 and sum(t["me"] for t in board["top"]) == 1
    )


async def test_rooms_public_private_full_and_access(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    users, rid, code = await table_for(client, outbox, 2, "private")
    stranger = await new_user(client, outbox, "stranger@example.com")
    assert (
        await client.get(f"{G}/rooms", headers=stranger.headers)
    ).json() == []  # private: not listed
    assert (await client.get(f"{G}/rooms/{rid}", headers=stranger.headers)).status_code == 403
    assert (await do(client, stranger, rid, "stand")).status_code == 403
    assert (await bet(client, stranger, rid)).status_code == 403
    # a private table by id, without its code: refused without revealing anything about it
    assert (await post(client, stranger, "/rooms/join", {"room_id": rid})).status_code == 403
    full = await post(client, stranger, "/rooms/join", {"code": code})
    assert full.json()["error"]["code"] == "room_full"
    assert (await post(client, stranger, "/rooms/join", {"code": "ZZZZZZ"})).status_code == 404

    owner = await new_user(client, outbox, "pub-owner@example.com")
    pub = (await post(client, owner, "/rooms", {"max_players": 3, "visibility": "public"})).json()
    listed = (await client.get(f"{G}/rooms", headers=stranger.headers)).json()
    assert [r["id"] for r in listed] == [pub["id"]] and listed[0]["players"] == 1
    priv = (
        await post(client, users[0], "/rooms", {"max_players": 2})
    ).json()  # users[0] moves tables
    assert (await post(client, stranger, "/rooms/join", {"room_id": priv["id"]})).status_code == 403
    v = (await post(client, stranger, "/rooms/join", {"room_id": pub["id"]})).json()
    assert v["me"]["seat"] == 1 and [p["nickname"] for p in v["players"]][1].startswith("Player ")
    again = (
        await post(client, stranger, "/rooms/join", {"room_id": pub["id"]})
    ).json()  # reconnect
    assert again["me"]["seat"] == 1 and len(again["players"]) == 2
    # one table at a time: the old seat was given up
    left = (
        await db.scalars(select(GameRoomPlayer).where(GameRoomPlayer.left_at.is_not(None)))
    ).all()
    assert [str(p.user_id) for p in left] == [users[0].user_id]

    await setting(db, "games.multiplayer_enabled", False)
    r = await post(client, owner, "/rooms", {"max_players": 2})
    assert r.json()["error"]["code"] == "multiplayer_disabled"
    await setting(db, "games.enabled", False)
    assert (await post(client, owner, "/rooms/solo")).json()["error"]["code"] == "games_disabled"
    assert not (await client.get(G, headers=owner.headers)).json()["enabled"]


async def expire(db: Any, rid: str) -> None:
    await db.execute(
        update(GameRoom)
        .where(GameRoom.id == uuid.UUID(rid))
        .values(deadline=utcnow() - dt.timedelta(seconds=1))
    )
    await db.commit()


async def test_timers_deal_without_idlers_and_play_for_them(
    client: AsyncClient,
    outbox: list[Any],
    db: Any,
    ctx: AppContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    users, rid, _ = await table_for(client, outbox, 3)
    a, b, c = users
    rig(monkeypatch, "TS", "TH", "9D", "8S", "8H", "8C")
    v = (await bet(client, a, rid)).json()
    assert v["phase"] == "betting" and v["deadline"] is not None
    await bet(client, b, rid)
    await expire(db, rid)
    assert await games.run_timers(ctx, db) == 1  # the periodic job deals without the idle player
    v = (await client.get(f"{G}/rooms/{rid}", headers=c.headers)).json()
    assert v["phase"] == "playing" and len(v["round"]["seats"]) == 2 and not v["me"]["in_round"]
    assert (await bet(client, c, rid)).json()["error"]["code"] == "round_in_progress"

    await expire(db, rid)  # a's turn runs out → auto-stand, applied when anyone looks at the table
    v = (await client.get(f"{G}/rooms/{rid}", headers=b.headers)).json()
    assert v["round"]["turn"] == {"seat": 1, "hand": 0} and v["me"]["actions"]
    assert (await do(client, a, rid, "hit")).json()["error"]["code"] == "not_allowed"
    v = (await do(client, b, rid, "stand")).json()
    assert v["phase"] == "settled" and [s["result"] for s in v["round"]["results"]["seats"]] == [
        "win",
        "win",
    ]

    # sitting out three rounds in a row means leaving the table
    for _ in range(2):
        rig(monkeypatch, "TS", "TH", "9D", "8S", "8H", "8C")
        await bet(client, a, rid)
        await bet(client, b, rid)
        await expire(db, rid)
        await games.run_timers(ctx, db)
        await do(client, a, rid, "stand")
        await do(client, b, rid, "stand")
    v = (await client.get(f"{G}/rooms/{rid}", headers=a.headers)).json()
    assert [p["seat"] for p in v["players"]] == [0, 1]
    assert (await client.get(f"{G}/rooms/{rid}", headers=c.headers)).status_code == 403


async def test_leaving_refunds_or_finishes_and_cannot_be_abused(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await stakes_on(db)
    users, rid, code = await table_for(client, outbox, 2)
    a, b = users
    await give(db, a, 5)
    await give(db, b, 5)
    await bet(client, a, rid, 2)
    assert await balance(client, a) == 72
    assert (await post(client, a, f"/rooms/{rid}/leave")).status_code == 204
    assert await balance(client, a) == 120  # left before the deal: stake refunded
    # rejoin and bet again for the same round: charged again (no free bet from the old key)
    await post(client, a, "/rooms/join", {"code": code})
    rig(monkeypatch, "TS", "TH", "9D", "8S", "8H", "8C")
    await bet(client, a, rid, 2)
    assert await balance(client, a) == 72
    v = (await bet(client, b, rid, 1)).json()
    assert v["phase"] == "playing" and v["round"]["turn"]["seat"] == 0

    # a leaves mid-round: their hand stands, the stake stays in play and settles normally
    await post(client, a, f"/rooms/{rid}/leave")
    v = (await client.get(f"{G}/rooms/{rid}", headers=b.headers)).json()
    assert v["round"]["turn"]["seat"] == 1 and len(v["players"]) == 1 and v["players"][0]["owner"]
    v = (await do(client, b, rid, "stand")).json()
    assert v["phase"] == "settled"
    assert await balance(client, a) == 72 + 96 and await balance(client, b) == 120 + 24
    assert (await client.get(f"{G}/rooms/{rid}", headers=a.headers)).status_code == 403
    await post(client, b, f"/rooms/{rid}/leave")
    assert (await db.get(GameRoom, uuid.UUID(rid), populate_existing=True)).status == "closed"
    assert (await post(client, a, "/rooms/join", {"code": code})).json()["error"][
        "code"
    ] == "room_closed"


async def test_realtime_updates_stream(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    users, rid, _ = await table_for(client, outbox, 2)
    a, b = users
    stream = room_updates(ctx, uuid.UUID(rid), uuid.UUID(a.user_id), heartbeat=0.3)
    first = await asyncio.wait_for(anext(stream), 5)
    assert (
        first["type"] == "room"
        and first["room"]["phase"] == "waiting"
        and first["room"]["me"]["seat"] == 0
    )
    await bet(client, b, rid)  # another player's action reaches a's stream
    nxt = await asyncio.wait_for(anext(stream), 5)
    assert nxt["room"]["phase"] == "betting" and nxt["room"]["players"][1]["ready"]
    assert nxt["room"]["players"][0]["online"]
    await post(client, a, f"/rooms/{rid}/leave")
    assert (await asyncio.wait_for(anext(stream), 5))["type"] == "left"
    await stream.aclose()


# ----------------------------------------------------------------------------- admin
async def test_admin_games_permissions_and_actions(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await stakes_on(db)
    users, rid, _ = await table_for(client, outbox, 2)
    a, b = users
    await give(db, a, 5)
    await give(db, b, 5)
    plain = a
    support = await staff(client, outbox, db, "g-support@example.com", ["support"])
    finance = await staff(client, outbox, db, "g-finance@example.com", ["finance"])
    ops = await staff(client, outbox, db, "g-ops@example.com", ["ops"])
    reason = {"reason": "testing"}
    for path in ("/overview", "/rooms", "/rounds", "/ledger", "/players", "/suspicious", "/events"):
        assert (await client.get(f"{AG}{path}", headers=plain.headers)).status_code == 403
        assert (await client.get(f"{AG}{path}", headers=finance.headers)).status_code == 403
        assert (await client.get(f"{AG}{path}", headers=support.headers)).status_code == 200, path
        assert (await client.get(f"{AG}{path}")).status_code == 401
    for who in (plain, support, finance):  # read-only roles can't change anything
        assert (
            await client.post(f"{AG}/rooms/{rid}/pause", headers=who.headers, json=reason)
        ).status_code == 403
        r = await client.post(
            f"{AG}/players/{a.user_id}/bonus", headers=who.headers, json={"delta_days": 9, **reason}
        )
        assert r.status_code == 403

    over = (await client.get(f"{AG}/overview", headers=ops.headers)).json()
    assert over["stakes_enabled"] and over["open_rooms"] == 1 and over["seated_players"] == 2
    assert over["bonus_hours_outstanding"] == 240

    rig(monkeypatch, "TS", "TH", "9D", "8S", "8H", "8C")
    await bet(client, a, rid, 1)
    await bet(client, b, rid, 1)
    r = await client.post(f"{AG}/rooms/{rid}/pause", headers=ops.headers, json=reason)
    assert r.json()["status"] == "paused"
    assert (await do(client, a, rid, "stand")).json()["error"]["code"] == "room_paused"
    v = (await client.get(f"{G}/rooms/{rid}", headers=a.headers)).json()
    assert v["status"] == "paused" and v["me"]["actions"] == [] and v["deadline"] is None
    await client.post(f"{AG}/rooms/{rid}/resume", headers=ops.headers, json=reason)
    assert (await do(client, a, rid, "stand")).status_code == 200
    r = await client.post(
        f"{AG}/rooms/{rid}/close", headers=ops.headers, json=reason
    )  # b never moved
    assert r.json()["status"] == "closed" and r.json()["players"] == 0
    assert (
        await balance(client, a) == 144 and await balance(client, b) == 144
    )  # both 18 vs 17: paid

    rounds = (
        await client.get(f"{AG}/rounds", headers=ops.headers, params={"user_id": a.user_id})
    ).json()
    assert len(rounds) == 1 and len(rounds[0]["players"]) == 2 and rounds[0]["stakes"]
    led = (
        await client.get(f"{AG}/ledger", headers=ops.headers, params={"user_id": a.user_id})
    ).json()
    assert [x["kind"] for x in led] == ["payout", "stake", "admin"]
    r = await client.post(
        f"{AG}/players/{a.user_id}/bonus", headers=ops.headers, json={"delta_days": -2, **reason}
    )
    assert r.json()["balance_days"] == 4.0
    r = await client.post(
        f"{AG}/players/{a.user_id}/bonus", headers=ops.headers, json={"delta_days": -9, **reason}
    )
    assert r.status_code == 409  # never below zero
    players = (
        await client.get(f"{AG}/players", headers=ops.headers, params={"user_id": a.user_id})
    ).json()
    assert players[0]["wins"] == 1 and players[0]["balance_hours"] == 96
    actions = [e["action"] for e in (await client.get(f"{AG}/events", headers=ops.headers)).json()]
    assert actions == [
        "game.bonus_adjusted",
        "game.room_closed",
        "game.room_resumed",
        "game.room_paused",
    ]
    # switches and rules are ordinary settings
    r = await client.put(
        "/api/v1/admin/settings/games.blackjack.stakes_enabled",
        headers=ops.headers,
        json={"value": False},
    )
    assert r.status_code == 200 and not (await client.get(G, headers=a.headers)).json()["stakes"]
    r = await client.put(
        "/api/v1/admin/settings/games.blackjack.decks", headers=ops.headers, json={"value": 99}
    )
    assert r.status_code == 422


async def test_suspicious_players_report(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    from app.models import GameRoundPlayer

    boss = await staff(client, outbox, db, "g-boss@example.com", ["superadmin"])
    lucky, normal = (
        uuid.UUID(boss.user_id),
        uuid.UUID((await new_user(client, outbox, "norm@example.com")).user_id),
    )
    room = GameRoom(code="TESTAA", state={})
    db.add(room)
    await db.flush()
    for i in range(40):
        rnd = GameRound(
            room_id=room.id,
            number=i + 1,
            server_seed="s",
            server_seed_hash="h",
            client_seed="c",
            rules={},
            finished_at=utcnow(),
        )
        db.add(rnd)
        await db.flush()
        db.add(
            GameRoundPlayer(
                round_id=rnd.id, user_id=lucky, seat=0, result="win" if i < 36 else "lose"
            )
        )
        db.add(
            GameRoundPlayer(
                round_id=rnd.id, user_id=normal, seat=1, result="win" if i < 17 else "lose"
            )
        )
    await db.commit()
    rep = (await client.get(f"{AG}/suspicious", headers=boss.headers)).json()
    assert [r["user_id"] for r in rep] == [str(lucky)] and rep[0]["win_rate"] == 0.9


# ----------------------------------------------------------------------------- notices
async def test_notices_redeem_admin_away_round_and_kick(
    client: AsyncClient,
    outbox: list[Any],
    db: Any,
    ctx: AppContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.cli import bootstrap_catalog
    from app.models import GameRoomPlayer

    await bootstrap_catalog()
    await setting(db, "games.bonus_redeem_enabled", True)
    # exchange: the player gets a notice with the new access date and the bonus left
    u = await new_user(client, outbox, "note@example.com")
    await give(db, u, 3)
    outbox.clear()
    r = await post(client, u, "/wallet/redeem", {"days": 2, "action_id": "redeem-note-1"})
    assert r.status_code == 200, r.text
    mail = next(m for m in outbox if m.template == "game_redeem")
    assert (
        mail.to == "note@example.com"
        and "+2 VPN days" in mail.subject
        and "Bonus days left: 1" in mail.text
    )

    # a manual change by staff: the sign and the balance are in the notice
    outbox.clear()
    await games.send_notices(ctx, [("game_bonus_admin", uuid.UUID(u.user_id), {"_change": "36"})])
    mail = next(m for m in outbox if m.template == "game_bonus_admin")
    assert "+1.5" in mail.subject and "balance is now 1 days" in mail.text

    # a round that finished while a player was away → notice; the player watching gets none
    users, rid, _ = await table_for(client, outbox, 2)
    a, b = users
    rig(monkeypatch, "TS", "TH", "9D", "8S", "8H", "8C")
    await bet(client, a, rid)
    await bet(client, b, rid)
    await db.execute(
        update(GameRoomPlayer)
        .where(GameRoomPlayer.room_id == uuid.UUID(rid), GameRoomPlayer.seat == 0)
        .values(last_seen_at=utcnow() - dt.timedelta(minutes=5))
    )
    await db.commit()
    await expire(db, rid)
    outbox.clear()
    await games.run_timers(ctx, db)  # a's turn runs out: the server stands for a
    v = (await do(client, b, rid, "stand")).json()
    assert v["phase"] == "settled"
    away = [m for m in outbox if m.template == "game_round_away"]
    assert len(away) == 1 and away[0].to == a.email and "win" in away[0].subject

    # sitting out three rounds in a row: removed from the table, with a notice
    outbox.clear()
    for _ in range(3):
        rig(monkeypatch, "TS", "TH", "9D", "8S", "8H", "8C")
        await bet(client, b, rid)
        await expire(db, rid)
        await games.run_timers(ctx, db)
        await do(client, b, rid, "stand")
    kicked = [m for m in outbox if m.template == "game_kicked"]
    assert len(kicked) == 1 and kicked[0].to == a.email
    assert (await client.get(f"{G}/rooms/{rid}", headers=a.headers)).status_code == 403
