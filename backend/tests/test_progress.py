"""Blackjack progression (ADR-021): XP and levels, achievements, daily challenges and streak,
leaderboards, seasons and prizes — all from server-side round results."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.core.config import Settings
from app.core.context import AppContext
from app.games import boards, progress, wallet
from app.games import service as games
from app.models import (
    AuditLog,
    BonusLedger,
    ChallengeTemplate,
    GameProfile,
    GameReward,
    PlayDay,
    Season,
    SeasonResult,
    SeasonStat,
    User,
    UserAchievement,
    UserTitle,
    XpEvent,
)
from app.models.base import utcnow
from app.services import settings as settings_service
from tests.conftest import make_settings
from tests.helpers import new_user
from tests.test_games import FILL, bet, do, setting, solo

G = "/api/v1/games"
WIN_20 = ("TH", "9C", "TD", "8S")  # 20 vs dealer 17 → stand and win
BLACKJACK = ("AH", "9C", "KD", "8S")  # natural vs dealer 17
LOSE = ("TH", "9C", "7D", "TS")  # 17 vs dealer 19
PUSH = ("TH", "9C", "8D", "9S")  # 18 vs 18
PERFECT = ("TH", "9C", "5D", "8S", "6C")  # 15, hit 6 → 21 vs dealer 17


@pytest.fixture
def settings() -> Settings:
    return make_settings(rate_limit_enabled=False)


def rig(monkeypatch: pytest.MonkeyPatch, cards: tuple[str, ...]) -> None:
    monkeypatch.setattr(games.fair, "shuffled_shoe", lambda *a, **k: [*cards, *FILL])


async def play(
    client: AsyncClient, user: Any, monkeypatch: pytest.MonkeyPatch, cards: tuple[str, ...]
) -> dict[str, Any]:
    """One solo round with a fixed shoe; returns the settled table view."""
    rig(monkeypatch, cards)
    rid = (await solo(client, user))["id"]
    v = (await bet(client, user, rid)).json()
    if v["phase"] != "settled":
        v = (await do(client, user, rid, "hit" if cards == PERFECT else "stand")).json()
    assert v["phase"] == "settled", v
    return v


async def only_challenges(db: Any, *codes: str) -> None:
    """Make the daily pick deterministic: one template per difficulty."""
    await db.execute(update(ChallengeTemplate).values(enabled=ChallengeTemplate.code.in_(codes)))
    await db.commit()


async def profile_of(db: Any, user: Any) -> GameProfile:
    p = await db.get(GameProfile, uuid.UUID(user.user_id))
    await db.refresh(p)
    return p


# ------------------------------------------------------------------------------- levels
def test_level_curve_and_titles() -> None:
    assert [progress.xp_to_reach(n, 100, 50) for n in (1, 2, 3, 4)] == [0, 100, 250, 450]
    assert [progress.level_for(x, 100, 50) for x in (0, 99, 100, 249, 250, 10_000)] == [
        1, 1, 2, 2, 3, 19,
    ]  # fmt: skip
    assert progress.level_for(10**9, 100, 50) > 100  # scales to any level
    titles = {"1": "Rookie", "5": "Fighter", "10": "Master"}
    assert [progress.level_title(n, titles) for n in (1, 4, 5, 9, 10, 99)] == [
        "Rookie", "Rookie", "Fighter", "Fighter", "Master", "Master",
    ]  # fmt: skip


# --------------------------------------------------------------------- one round → progress
async def test_rounds_give_xp_challenges_achievements_and_level(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await only_challenges(db, "rounds_3", "wins_2", "blackjack_1")
    u = await new_user(client, outbox, "kong@example.com")

    v = await play(client, u, monkeypatch, WIN_20)
    events = v["me"]["progress"]
    kinds = [e["type"] for e in events]
    assert {"xp", "achievement", "streak"} <= set(kinds)
    assert {e["code"] for e in events if e["type"] == "achievement"} == {
        "first_steps", "first_victory",
    }  # fmt: skip
    assert (await profile_of(db, u)).xp == 15 + 10 + 20

    v = await play(client, u, monkeypatch, BLACKJACK)
    events = v["me"]["progress"]
    assert any(e["type"] == "level" and e["level"] == 2 for e in events)  # 70 + 40 crosses 100
    done = [e for e in events if e["type"] == "challenge"]
    assert sorted(e["xp"] for e in done) == [40, 60]  # two wins, a blackjack
    v = await play(client, u, monkeypatch, LOSE)
    assert [e["xp"] for e in v["me"]["progress"] if e["type"] == "challenge"] == [20]

    p = await profile_of(db, u)
    assert p.xp == 195 and p.level == 2 and p.rounds == 3 and p.blackjacks == 1
    total = await db.scalar(select(func.sum(XpEvent.amount)).where(XpEvent.user_id == p.user_id))
    assert total == p.xp  # the ledger explains every point

    ch = (await client.get(f"{G}/challenges", headers=u.headers)).json()
    assert [c["code"] for c in ch["today"]] == ["rounds_3", "wins_2", "blackjack_1"]
    assert all(c["completed_at"] and c["progress"] == c["target"] for c in ch["today"])
    assert ch["streak"]["current"] == 1 and ch["streak"]["played_today"]
    assert ch["streak"]["next_reward"]["days"] == 3 and len(ch["history"]) == 3
    assert ch["calendar"][-1]["rounds"] == 3

    me = (await client.get(f"{G}/me", headers=u.headers)).json()
    assert me["level"] == 2 and me["xp"] == 195 and me["level_xp"] == 100
    assert me["next_level_xp"] == 250 and me["progress"] == round(95 / 150, 4)
    assert me["title"] == "Jungle Explorer" and me["win_rate"] == 66.7
    assert me["achievements"]["unlocked"] == 2 and me["ranks"]["xp"] == 1
    assert len(me["recent"]) == 3

    # the next deal clears the events: they are shown once
    rig(monkeypatch, LOSE)
    rid = (await solo(client, u))["id"]
    assert (await bet(client, u, rid)).json()["me"]["progress"] == []

    # replaying the same XP key adds nothing
    assert await progress.add_xp(db, {"games.levels.base_xp": 100, "games.levels.step_xp": 50,
        "games.levels.titles": {"1": "x"}}, p, 15, "round", "round:replay", []) == 15  # fmt: skip
    assert await progress.add_xp(db, {"games.levels.base_xp": 100, "games.levels.step_xp": 50,
        "games.levels.titles": {"1": "x"}}, p, 15, "round", "round:replay", []) == 0  # fmt: skip


async def test_perfect_21_push_and_unfinished_rounds(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await new_user(client, outbox, "perfect@example.com")
    v = await play(client, u, monkeypatch, PERFECT)
    assert v["round"]["results"]["seats"][0]["result"] == "win"
    assert "perfect_player" in {e.get("code") for e in v["me"]["progress"]}
    v = await play(client, u, monkeypatch, PUSH)
    p = await profile_of(db, u)
    assert p.pushes == 1 and p.perfect_wins == 1

    # a round the administration closes before it ends doesn't count anywhere
    rig(monkeypatch, LOSE)
    rid = (await solo(client, u))["id"]
    assert (await bet(client, u, rid)).json()["phase"] == "playing"
    xp_before = p.xp
    await games.close_room(db, uuid.UUID(rid), reason="test")
    await db.commit()
    p = await profile_of(db, u)
    assert p.xp == xp_before and p.rounds == 3  # in the history, but no progress from it


async def test_daily_xp_cap_is_logged_once(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await setting(db, "games.xp.daily_round_cap", 8)
    await setting(db, "games.achievements.enabled", False)
    await setting(db, "games.challenges.enabled", False)
    u = await new_user(client, outbox, "bot@example.com")
    for _ in range(4):
        await play(client, u, monkeypatch, LOSE)
    p = await profile_of(db, u)
    assert p.xp == 8 and p.rounds == 4  # 5 + 3 + 0 + 0; rounds still count
    caps = (await db.scalars(select(AuditLog).where(AuditLog.action == "game.xp_daily_cap"))).all()
    assert len(caps) == 1


async def test_daily_streak_rewards_once_and_resets(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await new_user(client, outbox, "daily@example.com")
    await play(client, u, monkeypatch, LOSE)  # day 1
    p = await profile_of(db, u)
    today = p.last_play_day
    # pretend the two previous days were played too
    p.last_play_day, p.day_streak, p.best_day_streak = today - dt.timedelta(days=1), 2, 2
    await db.execute(update(PlayDay).values(day=today - dt.timedelta(days=1)))
    await db.commit()
    v = await play(client, u, monkeypatch, LOSE)
    rewards = [e for e in v["me"]["progress"] if e["type"] == "reward"]
    assert rewards == [{"type": "reward", "source": "streak", "xp": 30, "title": None,
                        "frame": None, "bonus_days": 0}]  # fmt: skip
    assert "daily_player" in {e.get("code") for e in v["me"]["progress"]}
    await play(client, u, monkeypatch, LOSE)  # same day again: nothing more
    assert len((await db.scalars(select(GameReward))).all()) == 1
    p = await profile_of(db, u)
    assert p.day_streak == 3 and p.best_day_streak == 3

    p.last_play_day = today - dt.timedelta(days=3)  # missed days
    await db.commit()
    await play(client, u, monkeypatch, LOSE)
    p = await profile_of(db, u)
    assert p.day_streak == 1 and p.best_day_streak == 3


# --------------------------------------------------------------------------- leaderboards
async def _players(db: Any, n: int, **fields: Any) -> list[GameProfile]:
    out = []
    for i in range(n):
        user = User(email=f"p{i}-{uuid.uuid4().hex[:6]}@example.com", roles=[])
        db.add(user)
        await db.flush()
        prof = GameProfile(user_id=user.id, nickname=f"Player{i:02d}", **fields)
        db.add(prof)
        out.append(prof)
    await db.flush()
    return out


async def test_boards_order_ties_min_rounds_my_rank_and_search(db: Any) -> None:
    cfg = await games.config(db)
    t0 = utcnow()
    ps = await _players(db, 30)
    for i, p in enumerate(ps):
        p.wins, p.losses, p.xp, p.score_at = 10 + i, 20 - (i % 20), 100 * i, t0
    # a tie on wins: whoever got there first ranks higher
    ps[0].wins, ps[1].wins = 50, 50
    ps[0].score_at, ps[1].score_at = t0, t0 - dt.timedelta(minutes=5)
    ps[2].wins, ps[2].losses = 3, 16  # 19 decided: below the win-rate minimum (20)
    ps[3].excluded_at = t0  # removed by staff after a cheating review
    suspended = await db.get(User, ps[4].user_id)
    suspended.status = "suspended"
    await db.commit()

    b = await boards.board(db, cfg, "wins", season=None, user_id=ps[5].user_id, limit=3)
    assert [r["nickname"] for r in b["rows"]] == ["Player01", "Player00", "Player29"]
    assert b["total"] == 28 and b["me"]["nickname"] == "Player05"
    assert b["me"]["rank"] > 3  # visible even off the first page
    names = {
        r["nickname"]
        for r in (await boards.board(db, cfg, "wins", season=None, user_id=None, limit=50))["rows"]
    }
    assert "Player03" not in names and "Player04" not in names

    wr = await boards.board(db, cfg, "winrate", season=None, user_id=ps[2].user_id, limit=50)
    assert wr["me"] is None and wr["min_rounds"] == 20
    rates = [r["value"] for r in wr["rows"]]
    assert rates == sorted(rates, reverse=True)
    top = wr["rows"][0]
    assert top["value"] == top["wins"] * 10000 // (top["wins"] + top["losses"])

    xp = await boards.board(db, cfg, "xp", season=None, user_id=None, limit=5, q="player2")
    assert [r["nickname"] for r in xp["rows"]] == [f"Player{i}" for i in (29, 28, 27, 26, 25)]
    assert xp["rows"][0]["rank"] == 1  # search keeps the real rank
    page2 = await boards.board(db, cfg, "xp", season=None, user_id=None, offset=5, limit=5)
    assert [r["rank"] for r in page2["rows"]] == [6, 7, 8, 9, 10]


# --------------------------------------------------------------------------------- seasons
async def _season(db: Any, *, ended: bool = True, kind: str = "event") -> Season:
    now = utcnow()
    s = Season(
        kind=kind,
        name=f"Test {uuid.uuid4().hex[:4]}",
        starts_at=now - dt.timedelta(days=7),
        ends_at=now - dt.timedelta(minutes=1) if ended else now + dt.timedelta(days=1),
        board="xp",
        rewards=settings_service.SEASON_REWARDS_WEEKLY,
    )
    db.add(s)
    await db.flush()
    return s


async def test_season_finalisation_prizes_once_bonus_off_then_on(db: Any) -> None:
    cfg = await games.config(db)
    ps = await _players(db, 5)
    s = await _season(db)
    now = utcnow()
    for i, p in enumerate(ps):  # the 5th played only 3 rounds: below games.seasons.min_rounds
        db.add(SeasonStat(season_id=s.id, user_id=p.user_id, rounds=3 if i == 4 else 10 + i,
                          wins=i, losses=1, xp=1000 - 100 * i, score_at=now))  # fmt: skip
    await db.commit()

    prizes = await boards.finalize(db, cfg, s.id)
    await db.commit()
    assert [(p["rank"], p.get("title")) for _, p in prizes] == [
        (1, "King of Jungle"),
        (2, "Jungle Champion"),
        (3, "Jungle Warrior"),
        (4, None),
    ]  # fmt: skip  (the 5th played only 3 rounds: no prize)
    await db.refresh(s)
    assert s.status == "closed" and s.finalized_at is not None
    final = await boards.results(db, s.id, "xp")
    assert [r["rank"] for r in final] == [1, 2, 3, 4, 5] and final[0]["xp"] == 1000
    winner = await db.get(GameProfile, ps[0].user_id)
    await db.refresh(winner)
    assert winner.frame == "gold" and winner.xp == 500 + 600 + 50 + 150 + 250 + 400 + 20
    titles = (
        await db.scalars(select(UserTitle.title).where(UserTitle.user_id == ps[0].user_id))
    ).all()
    assert titles == ["King of Jungle"]
    got = set(
        (
            await db.scalars(
                select(UserAchievement.achievement_id).where(
                    UserAchievement.user_id == ps[0].user_id
                )
            )
        ).all()
    )
    assert len(got) == 5  # top 100, top 10, third, second, first
    reward = await db.scalar(select(GameReward).where(GameReward.user_id == ps[0].user_id))
    assert reward.bonus_days == 3 and reward.bonus_paid is False  # bonus days are off by default
    assert (await wallet.get_wallet(db, ps[0].user_id)).balance_hours == 0

    # finalising again (a retried task) changes nothing
    assert await boards.finalize(db, cfg, s.id) == []
    assert len((await db.scalars(select(GameReward))).all()) == 4

    # with bonus days switched on, prizes pay into the game wallet — never the subscription
    await settings_service.set_value(db, "games.rewards.bonus_days_enabled", True, actor_id=None)
    await db.commit()
    cfg = await games.config(db)
    s2 = await _season(db)
    db.add(
        SeasonStat(
            season_id=s2.id, user_id=ps[1].user_id, rounds=20, wins=5, losses=1, xp=50, score_at=now
        )
    )
    await db.commit()
    await boards.finalize(db, cfg, s2.id)
    await db.commit()
    assert (await wallet.get_wallet(db, ps[1].user_id)).balance_hours == 3 * 24
    led = (await db.scalars(select(BonusLedger).where(BonusLedger.user_id == ps[1].user_id))).all()
    assert [(e.kind, e.delta_hours) for e in led] == [("reward", 72)]


async def test_season_rotation_and_round_stats(
    client: AsyncClient,
    outbox: list[Any],
    db: Any,
    ctx: AppContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers.tasks import run_seasons

    cfg = {**await games.config(db), "games.timezone": "Europe/Moscow"}
    start, end, name = boards.bounds(
        "weekly", dt.datetime(2026, 11, 13, 22, 30, tzinfo=dt.UTC), cfg
    )
    # Fri 22:30 UTC = Sat 01:30 in Moscow; the week began Mon 00:00 MSK = Sun 21:00 UTC
    assert start == dt.datetime(2026, 11, 8, 21, 0, tzinfo=dt.UTC) and end - start == dt.timedelta(
        days=7
    )
    assert name == "2026-W46"
    m_start, _m_end, m_name = boards.bounds(
        "monthly", dt.datetime(2026, 12, 31, 22, 0, tzinfo=dt.UTC), cfg
    )
    assert m_name == "2027-01" and m_start == dt.datetime(2026, 12, 31, 21, 0, tzinfo=dt.UTC)

    assert await run_seasons(ctx, db) == 0
    assert await run_seasons(ctx, db) == 0  # safe to repeat
    live = (await db.scalars(select(Season).where(Season.status == "active"))).all()
    assert sorted(s.kind for s in live) == ["monthly", "weekly"]

    await only_challenges(db, "rounds_5", "wins_2", "win_run_3")  # none completes in one round
    u = await new_user(client, outbox, "season@example.com")
    await play(client, u, monkeypatch, WIN_20)
    stats = (
        await db.scalars(select(SeasonStat).where(SeasonStat.user_id == uuid.UUID(u.user_id)))
    ).all()
    assert len(stats) == 2 and all(st.wins == 1 and st.rounds == 1 and st.xp == 45 for st in stats)

    week = (
        await client.get(
            f"{G}/boards", headers=u.headers, params={"board": "wins", "period": "weekly"}
        )
    ).json()
    assert week["season"]["kind"] == "weekly" and week["me"]["rank"] == 1 and week["total"] == 1

    # the week ends: the task closes it, freezes the table, opens the next one
    await db.execute(
        update(Season)
        .where(Season.kind == "weekly")
        .values(ends_at=utcnow() - dt.timedelta(seconds=1))
    )
    await db.commit()
    assert await run_seasons(ctx, db) == 1
    closed = await db.scalar(select(Season).where(Season.status == "closed"))
    assert closed.kind == "weekly"
    assert (
        await db.scalar(
            select(func.count())
            .select_from(SeasonResult)
            .where(SeasonResult.season_id == closed.id)
        )
        == 2
    )
    seasons = (await client.get(f"{G}/seasons", headers=u.headers)).json()
    assert seasons["archive"][0]["id"] == str(closed.id)
    res = (
        await client.get(
            f"{G}/seasons/{closed.id}/results", headers=u.headers, params={"board": "wins"}
        )
    ).json()
    assert res["rows"][0]["me"] and res["rows"][0]["wins"] == 1


# -------------------------------------------------------------------------------- the API
async def test_profile_looks_titles_achievements_and_history(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await only_challenges(db, "rounds_5", "wins_2", "win_run_3")  # none completes in one round
    u = await new_user(client, outbox, "looks@example.com")
    await play(client, u, monkeypatch, BLACKJACK)
    r = await client.put(f"{G}/profile", headers=u.headers, json={"avatar": "🐯"})
    assert r.status_code == 200 and r.json()["progress"]["avatar"] == "🐯"
    assert (
        await client.put(f"{G}/profile", headers=u.headers, json={"avatar": "<b>"})
    ).status_code == 422
    r = await client.put(f"{G}/profile", headers=u.headers, json={"title": "King of Jungle"})
    assert r.status_code == 422  # not earned
    db.add(UserTitle(user_id=uuid.UUID(u.user_id), title="King of Jungle", source="season"))
    await db.commit()
    r = await client.put(f"{G}/profile", headers=u.headers, json={"title": "King of Jungle"})
    assert r.json()["progress"]["title"] == "King of Jungle"
    me = (await client.get(f"{G}/me", headers=u.headers)).json()
    assert (
        me["titles"] == ["Jungle Rookie", "King of Jungle"]
        and me["chosen_title"] == "King of Jungle"
    )
    assert (await client.put(f"{G}/profile", headers=u.headers, json={"title": ""})).json()[
        "progress"
    ]["title"] == "Jungle Rookie"

    ach = (await client.get(f"{G}/achievements", headers=u.headers)).json()
    cats = {a["category"] for a in ach}
    assert cats == {"game", "activity", "progress", "season"} and len(ach) == 23
    bjm = next(a for a in ach if a["code"] == "blackjack_master")
    assert bjm["progress"] == 1 and bjm["target"] == 10 and bjm["unlocked_at"] is None
    assert next(a for a in ach if a["code"] == "first_victory")["unlocked_at"]

    xp = (await client.get(f"{G}/xp", headers=u.headers)).json()
    assert sum(e["amount"] for e in xp) == me["xp"]
    assert (await client.get(f"{G}/rewards", headers=u.headers)).json() == []
    hub = (await client.get(G, headers=u.headers)).json()
    assert hub["progress"]["level"] == me["level"] and hub["progress"]["avatar"] == "🐯"
    for board in ("wins", "winrate", "xp"):
        for period in ("all", "weekly", "monthly"):
            r = await client.get(
                f"{G}/boards", headers=u.headers, params={"board": board, "period": period}
            )
            assert r.status_code == 200, (board, period, r.text)
    assert (
        await client.get(f"{G}/boards", headers=u.headers, params={"board": "money"})
    ).status_code == 422


# ---------------------------------------------------------------------------- staff side
async def test_admin_progress_exclusion_catalogue_and_seasons(
    client: AsyncClient, outbox: list[Any], db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.helpers import staff

    A = "/api/v1/admin/games"
    support = await staff(client, outbox, db, "sup@example.com", ["support"])
    ops = await staff(client, outbox, db, "ops@example.com", ["ops"])
    await only_challenges(db, "rounds_5", "wins_2", "win_run_3")
    cheat = await new_user(client, outbox, "cheat@example.com")
    honest = await new_user(client, outbox, "honest@example.com")
    await play(client, cheat, monkeypatch, WIN_20)
    await play(client, cheat, monkeypatch, WIN_20)
    await play(client, honest, monkeypatch, WIN_20)

    found = (await client.get(f"{A}/progress/players", headers=support.headers)).json()
    assert [p["wins"] for p in found] == [2, 1]
    detail = (
        await client.get(f"{A}/progress/players/{cheat.user_id}", headers=support.headers)
    ).json()
    assert detail["level"] == 2 and len(detail["achievements"]) == 2 and detail["xp_history"]
    r = await client.post(
        f"{A}/progress/players/{cheat.user_id}/exclude",
        headers=support.headers,
        json={"reason": "bot"},
    )
    assert r.status_code == 403  # support may look, not change
    r = await client.post(
        f"{A}/progress/players/{cheat.user_id}/exclude", headers=ops.headers, json={}
    )
    assert r.status_code == 422  # a reason is required
    r = await client.post(
        f"{A}/progress/players/{cheat.user_id}/exclude",
        headers=ops.headers,
        json={"reason": "scripted play, 900 rounds/h"},
    )
    assert r.status_code == 200
    board = (
        await client.get(f"{G}/boards", headers=honest.headers, params={"board": "wins"})
    ).json()
    assert [row["wins"] for row in board["rows"]] == [1] and board["total"] == 1
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "game.player_excluded"))
    assert row.details == {"reason": "scripted play, 900 rounds/h"}
    await client.post(
        f"{A}/progress/players/{cheat.user_id}/include",
        headers=ops.headers,
        json={"reason": "appeal"},
    )
    board = (
        await client.get(f"{G}/boards", headers=honest.headers, params={"board": "wins"})
    ).json()
    assert board["total"] == 2

    # achievements: create, validation, disable
    new = {
        "code": "hat_trick", "category": "game", "metric": "best_win_streak", "threshold": 3,
        "xp_reward": 25, "icon": "🎩", "names": {"ru": "Хет-трик", "en": "Hat Trick"},
        "descriptions": {"ru": "Три победы подряд.", "en": "Three wins in a row."},
    }  # fmt: skip
    assert (
        await client.post(f"{A}/achievements", headers=ops.headers, json=new)
    ).status_code == 201
    assert (
        await client.post(f"{A}/achievements", headers=ops.headers, json=new)
    ).status_code == 409
    bad = {**new, "code": "bad_one", "metric": "season_rank"}
    assert (
        await client.post(f"{A}/achievements", headers=ops.headers, json=bad)
    ).status_code == 422
    listed = (await client.get(f"{A}/achievements", headers=support.headers)).json()
    fv = next(a for a in listed if a["code"] == "first_victory")
    assert fv["unlocked_by"] == 2 and len(listed) == 24
    hat = next(a for a in listed if a["code"] == "hat_trick")
    await client.patch(
        f"{A}/achievements/{hat['id']}", headers=ops.headers, json={"enabled": False}
    )
    mine = (await client.get(f"{G}/achievements", headers=honest.headers)).json()
    assert "hat_trick" not in {a["code"] for a in mine}  # disabled and not unlocked: hidden

    # challenges
    ch = {"code": "wins_5", "difficulty": "hard", "names": {"ru": "5 побед", "en": "5 wins"},
          "metric": "wins", "target": 5, "xp_reward": 100}  # fmt: skip
    assert (await client.post(f"{A}/challenges", headers=ops.headers, json=ch)).status_code == 201
    tpl = next(
        t
        for t in (await client.get(f"{A}/challenges", headers=support.headers)).json()
        if t["code"] == "wins_5"
    )
    r = await client.patch(f"{A}/challenges/{tpl['id']}", headers=ops.headers, json={"target": 4})
    assert r.json()["target"] == 4

    # seasons: an event, edits, finishing early
    now = utcnow()
    ev = {"name": "Banana Cup", "starts_at": (now - dt.timedelta(hours=1)).isoformat(),
          "ends_at": (now + dt.timedelta(days=2)).isoformat(), "board": "wins"}  # fmt: skip
    r = await client.post(
        f"{A}/seasons", headers=ops.headers, json={**ev, "ends_at": ev["starts_at"]}
    )
    assert r.status_code == 422
    r = await client.post(f"{A}/seasons", headers=ops.headers, json=ev)
    assert r.status_code == 201
    sid = r.json()["id"]
    await play(client, honest, monkeypatch, WIN_20)  # counts in the event season too
    r = await client.patch(
        f"{A}/seasons/{sid}", headers=ops.headers,
        json={"reason": "earlier start", "starts_at": (now - dt.timedelta(days=1)).isoformat()},
    )  # fmt: skip
    assert r.status_code == 409  # already started
    live = (
        await client.get(
            f"{A}/seasons/{sid}/results", headers=support.headers, params={"board": "wins"}
        )
    ).json()
    assert live["live"] and live["rows"][0]["wins"] == 1
    r = await client.post(
        f"{A}/seasons/{sid}/finish", headers=ops.headers, json={"reason": "event over"}
    )
    assert r.json()["status"] == "closed"
    final = (
        await client.get(
            f"{A}/seasons/{sid}/results", headers=support.headers, params={"board": "wins"}
        )
    ).json()
    assert final["rows"][0]["wins"] == 1 and "live" not in final
    r = await client.patch(
        f"{A}/seasons/{sid}", headers=ops.headers, json={"reason": "late fix", "name": "New"}
    )
    assert r.status_code == 409  # history doesn't change
    seasons = (await client.get(f"{A}/seasons", headers=support.headers)).json()
    assert any(s["id"] == sid and s["winners"] for s in seasons)
    actions = set(
        (await db.scalars(select(AuditLog.action).where(AuditLog.action.like("game.%")))).all()
    )
    expected = {"game.achievement_created", "game.achievement_updated", "game.challenge_created",
                "game.season_created", "game.season_finished", "game.player_included"}  # fmt: skip
    assert expected <= actions
