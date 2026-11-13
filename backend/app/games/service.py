"""Blackjack tables: rooms for 1-4 players, betting, turns, timers, settlement, statistics.

Every change to a table happens under a row lock on `game_rooms` (SELECT … FOR UPDATE), so
simultaneous requests from several players are applied one after another. The engine state —
including the shoe and the next server seed — lives in `room.state` and never leaves the server:
clients only get `room_view()`.

Phases of a table:  waiting → betting → [insurance] → playing → settled → betting → …
"""

from __future__ import annotations

import copy
import datetime as dt
import logging
import re
import secrets
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.context import AppContext
from app.core.errors import AppError, NotFound, PermissionDenied
from app.games import blackjack as bj
from app.games import fair, wallet
from app.models import (
    BonusLedger,
    GameProfile,
    GameRoom,
    GameRoomPlayer,
    GameRound,
    GameRoundPlayer,
    User,
)
from app.models.base import utcnow
from app.models.enums import ActorType
from app.notifications.notify import miniapp_url, notify
from app.services import audit
from app.services import settings as settings_service

log = logging.getLogger(__name__)
H = wallet.HOURS_PER_DAY
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no look-alikes
SOLO_TURN_SECONDS = 600  # an abandoned solo round still ends (auto-stand) and frees the stake
MAX_MISSED = 3  # rounds a player may sit out / time out before leaving the table
ONLINE_SECONDS = 20
IDLE_ROOM_MINUTES = 120
LIVE = ("insurance", "playing")


class GameError(AppError):
    status_code = 409
    code = "game_error"

    def __init__(self, code: str, message: str | None = None, **details: Any) -> None:
        super().__init__(
            message or code.replace("_", " ").capitalize() + ".", code=code, details=details or None
        )


def channel(room_id: uuid.UUID) -> str:
    return f"games:room:{room_id}"


async def publish(ctx: AppContext, room: GameRoom) -> None:
    """Tell every connected client of the table that there is a new version to fetch, then send
    the Telegram/email notices that the change produced (only after it was committed)."""
    try:
        await ctx.redis.publish(channel(room.id), str(room.version))
    except Exception:  # realtime is best effort; clients also poll
        log.warning("games: publish failed for room %s", room.id)
    notices = _NOTICES.pop(room.id, [])
    if notices:
        await send_notices(ctx, notices)


# --------------------------------------------------------------------------- notices
# Collected while a table changes (settlement, removal for inactivity) and sent by publish()
# after the commit, so nobody is told about a change that was rolled back.
AWAY_SECONDS = 20  # not looking at the table for this long = the round finished "without you"
_NOTICES: dict[uuid.UUID, list[tuple[str, uuid.UUID, dict[str, str]]]] = {}


def _notice(room_id: uuid.UUID, template: str, user_id: uuid.UUID, params: dict[str, str]) -> None:
    pending = _NOTICES.setdefault(room_id, [])
    if len(pending) < 32:
        pending.append((template, user_id, params))


def fmt_days(hours: int, locale: str, signed: bool = False) -> str:
    """Hours of bonus → days for people: 36 → "1.5", signed on request (+1.5 / minus 1.5)."""
    from babel.numbers import format_decimal

    text = format_decimal(abs(hours) / H, format="#,##0.#", locale=locale)
    if not signed:
        return text
    return f"+{text}" if hours > 0 else f"\u2212{text}" if hours < 0 else "0"


async def send_notices(
    ctx: AppContext, notices: list[tuple[str, uuid.UUID, dict[str, str]]]
) -> None:
    from app.i18n import t

    try:
        async with ctx.sessionmaker() as db:
            for template, user_id, raw in notices:
                user = await db.get(User, user_id)
                if user is None:
                    continue
                bal = (await wallet.get_wallet(db, user_id)).balance_hours
                params = {k: v for k, v in raw.items() if not k.startswith("_")}
                params["balance"] = fmt_days(bal, user.locale)
                if "_change" in raw:
                    params["change"] = fmt_days(int(raw["_change"]), user.locale, signed=True)
                if "_result" in raw:
                    params["result"] = t(user.locale, f"games.result.{raw['_result']}")
                await notify(ctx, user, template, params, miniapp_url(ctx))
    except Exception:  # a notice must never break the game
        log.exception("games: sending notices failed")


# --------------------------------------------------------------------------- settings
async def config(db: AsyncSession) -> dict[str, Any]:
    return await settings_service.get_all(db)


def rules_from(cfg: dict[str, Any]) -> bj.Rules:
    num, den = (int(x) for x in str(cfg["games.blackjack.blackjack_pays"]).split(":"))
    return bj.Rules(
        decks=cfg["games.blackjack.decks"],
        dealer_hits_soft_17=cfg["games.blackjack.dealer_hits_soft_17"],
        blackjack_pays=(num, den),
        allow_double=cfg["games.blackjack.allow_double"],
        allow_double_after_split=cfg["games.blackjack.allow_double_after_split"],
        allow_split=cfg["games.blackjack.allow_split"],
        max_hands=cfg["games.blackjack.max_hands"],
        allow_surrender=cfg["games.blackjack.allow_surrender"],
        allow_insurance=cfg["games.blackjack.allow_insurance"],
    )


def _require_enabled(cfg: dict[str, Any]) -> None:
    if not cfg["games.enabled"]:
        raise GameError("games_disabled", "Mini games are turned off right now.")


# --------------------------------------------------------------------------- profile
_CTRL = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]")


def clean_nickname(raw: str | None, user_id: uuid.UUID) -> str:
    name = re.sub(r"\s+", " ", _CTRL.sub("", raw or "")).strip()[:24]
    return name or f"Player {str(user_id)[-4:].upper()}"


async def ensure_profile(
    db: AsyncSession, user_id: uuid.UUID, cfg: dict[str, Any], nickname: str | None = None
) -> GameProfile:
    profile = await db.get(GameProfile, user_id)
    if profile is None:
        profile = GameProfile(user_id=user_id, nickname=clean_nickname(nickname, user_id))
        db.add(profile)
        await db.flush()
    elif nickname is not None:
        profile.nickname = clean_nickname(nickname, user_id)
    days = cfg["games.blackjack.welcome_bonus_days"]
    if cfg["games.blackjack.stakes_enabled"] and days:
        w = await wallet.get_wallet(db, user_id, lock=True)
        if not w.welcome_granted:
            w.welcome_granted = True
            await wallet.move(db, user_id, days * H, "welcome", "welcome", note="welcome bonus")
    return profile


# --------------------------------------------------------------------------- rooms
async def _lock(db: AsyncSession, room_id: uuid.UUID) -> GameRoom:
    room = (
        await db.execute(
            select(GameRoom)
            .where(GameRoom.id == room_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if room is None:
        raise NotFound("No such table.")
    return room


async def players_of(db: AsyncSession, room_id: uuid.UUID) -> list[GameRoomPlayer]:
    rows = await db.scalars(
        select(GameRoomPlayer)
        .where(GameRoomPlayer.room_id == room_id, GameRoomPlayer.left_at.is_(None))
        .order_by(GameRoomPlayer.seat)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def current_seat(db: AsyncSession, user_id: uuid.UUID) -> GameRoomPlayer | None:
    return (
        await db.execute(
            select(GameRoomPlayer).where(
                GameRoomPlayer.user_id == user_id, GameRoomPlayer.left_at.is_(None)
            )
        )
    ).scalar_one_or_none()


def _touch(room: GameRoom, state: dict[str, Any]) -> None:
    room.state = state
    flag_modified(room, "state")
    room.version += 1


def _in_live_round(state: dict[str, Any], phase: str, user_id: uuid.UUID) -> bool:
    eng = state.get("round")
    return bool(phase in LIVE and eng and any(s["user"] == str(user_id) for s in eng["seats"]))


async def _leave_other_table(
    db: AsyncSession, ctx: AppContext, user_id: uuid.UUID, keep: uuid.UUID | None
) -> None:
    """A player sits at one table at a time. Moving on leaves the old one (finishing their hand)."""
    seat = await current_seat(db, user_id)
    if seat is not None and seat.room_id != keep:
        old = await leave_room(db, user_id, seat.room_id)
        await db.flush()
        await publish(ctx, old)


async def _new_code(db: AsyncSession) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if await db.scalar(select(GameRoom.id).where(GameRoom.code == code)) is None:
            return code
    raise GameError("try_again")


async def create_room(
    db: AsyncSession, ctx: AppContext, user_id: uuid.UUID, *, max_players: int, visibility: str
) -> GameRoom:
    cfg = await config(db)
    _require_enabled(cfg)
    if max_players > 1 and not cfg["games.multiplayer_enabled"]:
        raise GameError("multiplayer_disabled", "Shared tables are turned off right now.")
    await ensure_profile(db, user_id, cfg)
    await _leave_other_table(db, ctx, user_id, None)
    room = GameRoom(
        code=await _new_code(db),
        visibility="private" if max_players == 1 else visibility,
        max_players=max_players,
        owner_id=user_id,
        state={"next_seed": fair.new_server_seed(), "bets": {}, "seen": []},
    )
    db.add(room)
    await db.flush()
    db.add(GameRoomPlayer(room_id=room.id, user_id=user_id, seat=0, last_seen_at=utcnow()))
    await db.flush()
    return room


async def solo_room(db: AsyncSession, ctx: AppContext, user_id: uuid.UUID) -> GameRoom:
    """The player's own single-seat table: reuse it while it is open."""
    seat = await current_seat(db, user_id)
    if seat is not None:
        room = await db.get(GameRoom, seat.room_id)
        if room is not None and room.max_players == 1 and room.status == "open":
            return room
    return await create_room(db, ctx, user_id, max_players=1, visibility="private")


async def join_room(
    db: AsyncSession,
    ctx: AppContext,
    user_id: uuid.UUID,
    *,
    room_id: uuid.UUID | None,
    code: str | None,
) -> GameRoom:
    cfg = await config(db)
    _require_enabled(cfg)
    if code:
        found = await db.scalar(select(GameRoom.id).where(GameRoom.code == code.strip().upper()))
        if found is None:
            raise NotFound("No table with this code.")
        room_id = found
    if room_id is None:
        raise NotFound("No such table.")
    await ensure_profile(db, user_id, cfg)
    await _leave_other_table(db, ctx, user_id, room_id)
    room = await _lock(db, room_id)
    players = await players_of(db, room.id)
    if any(p.user_id == user_id for p in players):
        return room  # already seated: a reconnect
    if room.status != "open":
        raise GameError("room_closed", "This table is closed.")
    if room.visibility == "private" and not code:
        raise PermissionDenied("This table is private: you need its code.")
    if room.max_players > 1 and not cfg["games.multiplayer_enabled"]:
        raise GameError("multiplayer_disabled", "Shared tables are turned off right now.")
    if len(players) >= room.max_players:
        raise GameError("room_full", "This table is full.")
    taken = {p.seat for p in players}
    seat = next(i for i in range(room.max_players) if i not in taken)
    db.add(GameRoomPlayer(room_id=room.id, user_id=user_id, seat=seat, last_seen_at=utcnow()))
    _touch(room, copy.deepcopy(room.state))
    await db.flush()
    return room


async def leave_room(db: AsyncSession, user_id: uuid.UUID, room_id: uuid.UUID) -> GameRoom:
    room = await _lock(db, room_id)
    cfg = await config(db)
    players = await players_of(db, room.id)
    me = next((p for p in players if p.user_id == user_id), None)
    if me is None:
        return room
    state = copy.deepcopy(room.state)
    if _in_live_round(state, room.phase, user_id):  # finish their hands: the stake stays in play
        bj.force_stand(state["round"], me.seat)
    bet = state["bets"].pop(str(me.seat), None)
    if bet and bet["hours"]:
        await wallet.move(
            db,
            user_id,
            bet["hours"],
            "refund",
            f"refund:{bet['key']}",
            note="left before the deal",
        )
    me.left_at = utcnow()
    rest = [p for p in players if p.user_id != user_id]
    if room.owner_id == user_id:
        room.owner_id = rest[0].user_id if rest else None
    _touch(room, state)
    await db.flush()
    await _sync(db, room, state, cfg, rest)
    if not rest and room.phase not in LIVE:
        room.status = "closed"
        room.deadline = None
    return room


# --------------------------------------------------------------------------- betting & dealing
async def _daily_net(db: AsyncSession, user_id: uuid.UUID) -> int:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    net = await db.scalar(
        select(func.coalesce(func.sum(BonusLedger.delta_hours), 0)).where(
            BonusLedger.user_id == user_id,
            BonusLedger.kind.in_(("stake", "payout", "refund")),
            BonusLedger.created_at >= start,
        )
    )
    return int(net or 0)


def _seen(state: dict[str, Any], action_id: str | None) -> bool:
    if not action_id:
        return False
    if action_id in state["seen"]:
        return True
    state["seen"] = [*state["seen"][-99:], action_id]
    return False


async def place_bet(
    db: AsyncSession,
    user_id: uuid.UUID,
    room_id: uuid.UUID,
    *,
    stake_days: int,
    client_seed: str | None,
    action_id: str | None,
) -> GameRoom:
    """Join the next round. With stakes on, the stake is taken from the bonus wallet right now."""
    room = await _lock(db, room_id)
    cfg = await config(db)
    _require_enabled(cfg)
    players = await players_of(db, room.id)
    me = next((p for p in players if p.user_id == user_id), None)
    if me is None:
        raise PermissionDenied("You are not at this table.")
    if room.status == "paused":
        raise GameError("room_paused", "This table is paused by the administration.")
    if room.status != "open":
        raise GameError("room_closed", "This table is closed.")
    state = copy.deepcopy(room.state)
    if _seen(state, action_id) or str(me.seat) in state["bets"]:
        return room
    if room.phase in LIVE:
        raise GameError("round_in_progress", "Wait for the current round to finish.")
    hours = 0
    if cfg["games.blackjack.stakes_enabled"]:
        if stake_days not in cfg["games.blackjack.stake_options_days"]:
            raise GameError("bad_stake", "Choose one of the offered stakes.")
        if await _daily_net(db, user_id) >= cfg["games.blackjack.daily_win_cap_days"] * H:
            raise GameError("daily_cap", "You've reached today's bonus limit. Come back tomorrow!")
        hours = stake_days * H
    # A fresh key per bet: leaving (refund) and betting again must be two separate movements.
    key = f"bet:{room.id}:{room.round_no + 1}:{secrets.token_hex(6)}"
    if hours:
        await wallet.move(db, user_id, -hours, "stake", key, note="stake")
    seed = re.sub(r"[^A-Za-z0-9_.-]", "", client_seed or "")[:64] or "kingkong"
    state["bets"][str(me.seat)] = {"user": str(user_id), "hours": hours, "seed": seed, "key": key}
    me.missed = 0
    if room.phase != "betting":
        room.phase = "betting"
        seconds = cfg["games.blackjack.bet_seconds"]
        room.deadline = utcnow() + dt.timedelta(seconds=seconds) if len(players) > 1 else None
    _touch(room, state)
    if all(str(p.seat) in state["bets"] for p in players):
        await _deal(db, room, state, cfg, players)
    return room


async def _deal(
    db: AsyncSession,
    room: GameRoom,
    state: dict[str, Any],
    cfg: dict[str, Any],
    players: list[GameRoomPlayer],
) -> None:
    bets = state["bets"]
    for p in players:  # sitting out counts towards leaving the table
        if str(p.seat) not in bets:
            p.missed += 1
            if p.missed >= MAX_MISSED and p.left_at is None:
                p.left_at = utcnow()
                _notice(room.id, "game_kicked", p.user_id, {"code": room.code})
    if not bets:
        room.phase, room.deadline = "waiting", None
        _touch(room, state)
        return
    rules = rules_from(cfg)
    number = room.round_no + 1
    server_seed = state["next_seed"]
    client_seed = fair.combine_client_seeds({int(seat): b["seed"] for seat, b in bets.items()})
    shoe = fair.shuffled_shoe(server_seed, client_seed, number, rules.decks)
    seats = [
        {"seat": int(seat), "user": b["user"], "bet": b["hours"]}
        for seat, b in sorted(bets.items())
    ]
    rnd = GameRound(
        room_id=room.id,
        number=number,
        server_seed=server_seed,
        server_seed_hash=fair.seed_hash(server_seed),
        client_seed=client_seed,
        stakes=any(b["hours"] for b in bets.values()),
        rules=rules.to_json(),
    )
    db.add(rnd)
    await db.flush()
    state["round"] = bj.start_round(rules, shoe, seats)
    state["bets"] = {}
    state["round_started"] = utcnow().isoformat()
    room.round_no, room.round_id = number, rnd.id
    _touch(room, state)
    await _sync(db, room, state, cfg, [p for p in players if p.left_at is None])


async def _sync(
    db: AsyncSession,
    room: GameRoom,
    state: dict[str, Any],
    cfg: dict[str, Any],
    players: list[GameRoomPlayer],
) -> None:
    """Bring the table's phase and timer in line with the engine after any change."""
    eng = state.get("round")
    if eng is None or state.get("settled_round") == room.round_no:
        return  # no round is running
    if eng["phase"] == "settled":
        await _settle(db, room, state, eng)
        return
    room.phase = eng["phase"]
    seconds = cfg["games.blackjack.turn_seconds"] if room.max_players > 1 else SOLO_TURN_SECONDS
    room.deadline = utcnow() + dt.timedelta(seconds=seconds)
    _touch(room, state)


async def _settle(
    db: AsyncSession, room: GameRoom, state: dict[str, Any], eng: dict[str, Any]
) -> None:
    """Pay out, write history and statistics — exactly once per round."""
    assert room.round_id is not None
    rnd = await db.get(GameRound, room.round_id)
    assert rnd is not None
    for r in eng["results"]["seats"]:
        uid = uuid.UUID(r["user"])
        if r["returned"]:
            await wallet.move(
                db,
                uid,
                r["returned"],
                "payout",
                f"payout:{rnd.id}",
                round_id=rnd.id,
                note=r["result"],
            )
        db.add(
            GameRoundPlayer(
                round_id=rnd.id,
                user_id=uid,
                seat=r["seat"],
                staked_hours=r["staked"],
                returned_hours=r["returned"],
                result=r["result"],
                blackjack=r["blackjack"],
            )
        )
        profile = await db.get(GameProfile, uid, with_for_update=True)
        if profile is not None:
            profile.rounds += 1
            profile.net_hours += r["net"]
            profile.blackjacks += int(r["blackjack"])
            if r["result"] == "win":
                profile.wins += 1
                profile.streak += 1
                profile.best_streak = max(profile.best_streak, profile.streak)
            elif r["result"] == "lose":
                profile.losses += 1
                profile.streak = 0
            else:
                profile.pushes += 1
    away_before = utcnow() - dt.timedelta(seconds=AWAY_SECONDS)
    for r in eng["results"]["seats"]:
        uid = uuid.UUID(r["user"])
        seat = await db.scalar(
            select(GameRoomPlayer)
            .where(GameRoomPlayer.room_id == room.id, GameRoomPlayer.user_id == uid)
            .order_by(GameRoomPlayer.created_at.desc())
            .limit(1)
        )
        seen = seat.last_seen_at if seat is not None and seat.left_at is None else None
        if seen is None or seen < away_before:
            kind = "blackjack" if r["blackjack"] and r["result"] == "win" else r["result"]
            _notice(
                room.id,
                "game_round_away",
                uid,
                {"code": room.code, "_result": kind, "_change": str(r["net"])},
            )
    rnd.summary = bj.public_view(eng)
    rnd.finished_at = utcnow()
    state["last_fair"] = {
        "round_id": str(rnd.id),
        "number": rnd.number,
        "server_seed": rnd.server_seed,
        "server_seed_hash": rnd.server_seed_hash,
        "client_seed": rnd.client_seed,
        "decks": rnd.rules["decks"],
    }
    state["next_seed"] = fair.new_server_seed()
    state["settled_round"] = room.round_no
    room.phase, room.deadline = "settled", None
    _touch(room, state)
    await db.flush()


async def act(
    db: AsyncSession, user_id: uuid.UUID, room_id: uuid.UUID, action: str, action_id: str | None
) -> GameRoom:
    room = await _lock(db, room_id)
    cfg = await config(db)
    players = await players_of(db, room.id)
    me = next((p for p in players if p.user_id == user_id), None)
    if me is None:
        raise PermissionDenied("You are not at this table.")
    if room.status == "paused":
        raise GameError("room_paused", "This table is paused by the administration.")
    state = copy.deepcopy(room.state)
    if _seen(state, action_id):
        return room  # the same request again (retry after a network hiccup)
    eng = state.get("round")
    if room.phase not in LIVE or eng is None:
        raise GameError("wrong_phase", "There is no round in progress.")
    if action not in bj.allowed_actions(eng, me.seat):
        raise GameError("not_allowed", "You can't do that right now.")
    extra = bj.extra_stake(eng, me.seat, action)
    if extra and room.round_id:
        key = f"act:{room.round_id}:{action_id or secrets.token_hex(8)}"
        await wallet.move(db, user_id, -extra, "stake", key, round_id=room.round_id, note=action)
    bj.act(eng, me.seat, action)
    me.missed = 0
    _touch(room, state)
    await _sync(db, room, state, cfg, players)
    return room


async def tick(db: AsyncSession, room_id: uuid.UUID) -> GameRoom | None:
    """Apply an expired timer: deal with whoever is ready, or play for an idle player."""
    room = await _lock(db, room_id)
    if room.status != "open" or room.deadline is None or room.deadline > utcnow():
        return None
    cfg = await config(db)
    players = await players_of(db, room.id)
    state = copy.deepcopy(room.state)
    if room.phase == "betting":
        room.deadline = None
        await _deal(db, room, state, cfg, players)
        if all(p.left_at is not None for p in players) and room.phase not in LIVE:
            room.status = "closed"  # everybody walked away
        return room
    eng = state.get("round")
    if room.phase in LIVE and eng is not None:
        idle = bj.insurance_pending(eng) if eng["phase"] == "insurance" else [eng["turn"]["seat"]]
        for seat in idle:
            bj.force_stand(eng, seat)
            p = next((x for x in players if x.seat == seat), None)
            if p is not None:
                p.missed += 1
        _touch(room, state)
        await _sync(db, room, state, cfg, players)
        if room.phase == "settled":
            for p in players:
                if p.missed >= MAX_MISSED and p.left_at is None:
                    p.left_at = utcnow()
                    _notice(room.id, "game_kicked", p.user_id, {"code": room.code})
        return room
    room.deadline = None
    return room


async def due_rooms(db: AsyncSession) -> list[uuid.UUID]:
    rows = await db.scalars(
        select(GameRoom.id).where(
            GameRoom.status == "open", GameRoom.deadline.is_not(None), GameRoom.deadline <= utcnow()
        )
    )
    return list(rows.all())


async def run_timers(ctx: AppContext, db: AsyncSession) -> int:
    """Periodic job: expired timers, and tables nobody has touched for a long time."""
    n = 0
    for rid in await due_rooms(db):
        room = await tick(db, rid)
        await db.commit()
        if room is not None:
            await publish(ctx, room)
            n += 1
    stale = utcnow() - dt.timedelta(minutes=IDLE_ROOM_MINUTES)
    idle = await db.scalars(
        select(GameRoom.id).where(
            GameRoom.status == "open",
            GameRoom.updated_at < stale,
            GameRoom.phase.in_(("waiting", "settled")),
        )
    )
    for rid in idle.all():
        await close_room(db, rid, reason="idle")
        await db.commit()
    return n


async def close_room(db: AsyncSession, room_id: uuid.UUID, *, reason: str) -> GameRoom:
    """Close a table: finish a running round by standing for everyone, refund unplayed bets."""
    room = await _lock(db, room_id)
    cfg = await config(db)
    players = await players_of(db, room.id)
    state = copy.deepcopy(room.state)
    eng = state.get("round")
    if room.phase in LIVE and eng is not None:
        for s in list(eng["seats"]):
            if eng["phase"] != "settled":
                bj.force_stand(eng, s["seat"])
        await _sync(db, room, state, cfg, players)
    for seat, bet in list(state["bets"].items()):
        if bet["hours"]:
            await wallet.move(
                db,
                uuid.UUID(bet["user"]),
                bet["hours"],
                "refund",
                f"refund:{bet['key']}",
                note=reason,
            )
        state["bets"].pop(seat)
    await db.execute(
        update(GameRoomPlayer)
        .where(GameRoomPlayer.room_id == room.id, GameRoomPlayer.left_at.is_(None))
        .values(left_at=utcnow())
    )
    room.status, room.deadline = "closed", None
    if room.phase == "betting":
        room.phase = "waiting"
    _touch(room, state)
    return room


async def set_paused(db: AsyncSession, room_id: uuid.UUID, paused: bool) -> GameRoom:
    """Pausing freezes the timer; resuming gives the current player a fresh one."""
    room = await _lock(db, room_id)
    if room.status == "closed":
        raise GameError("room_closed", "This table is closed.")
    cfg = await config(db)
    room.status = "paused" if paused else "open"
    if paused:
        room.deadline = None
    elif room.phase in LIVE or room.phase == "betting":
        multi = room.max_players > 1
        key = (
            "games.blackjack.bet_seconds"
            if room.phase == "betting"
            else "games.blackjack.turn_seconds"
        )
        room.deadline = utcnow() + dt.timedelta(seconds=cfg[key] if multi else SOLO_TURN_SECONDS)
    _touch(room, copy.deepcopy(room.state))
    return room


# --------------------------------------------------------------------------- views
async def room_view(db: AsyncSession, room: GameRoom, user_id: uuid.UUID) -> dict[str, Any]:
    """What one player may see: no shoe, no next seed, the hole card hidden until the end."""
    cfg = await config(db)
    players = await players_of(db, room.id)
    names = dict(
        (
            await db.execute(
                select(GameProfile.user_id, GameProfile.nickname).where(
                    GameProfile.user_id.in_([p.user_id for p in players] or [user_id])
                )
            )
        ).all()
    )
    state = room.state
    eng = state.get("round")
    me = next((p for p in players if p.user_id == user_id), None)
    now = utcnow()
    view_round = None
    if eng is not None:
        view_round = bj.public_view(eng)
        for s in view_round["seats"]:
            s.pop("user", None)
        if view_round["results"]:
            for r in view_round["results"]["seats"]:
                r.pop("user", None)
    stakes = bool(cfg["games.blackjack.stakes_enabled"])
    bal = (await wallet.get_wallet(db, user_id)).balance_hours
    actions: list[str] = []
    extra: dict[str, int] = {}
    if me is not None and eng is not None and room.phase in LIVE and room.status == "open":
        actions = bj.allowed_actions(eng, me.seat)
        for a in ("double", "split", "insurance"):
            if a in actions:
                extra[a] = bj.extra_stake(eng, me.seat, a)
        actions = [a for a in actions if extra.get(a, 0) <= bal]  # can't afford → not offered
    return {
        "id": str(room.id),
        "code": room.code,
        "visibility": room.visibility,
        "max_players": room.max_players,
        "status": room.status,
        "phase": room.phase,
        "round_no": room.round_no,
        "version": room.version,
        "deadline": room.deadline.isoformat() if room.deadline else None,
        "server_time": now.isoformat(),
        "stakes": stakes,
        "stake_options_days": cfg["games.blackjack.stake_options_days"] if stakes else [],
        "next_seed_hash": fair.seed_hash(state["next_seed"]),
        "players": [
            {
                "seat": p.seat,
                "nickname": names.get(p.user_id, "Player"),
                "me": p.user_id == user_id,
                "owner": p.user_id == room.owner_id,
                "online": bool(
                    p.last_seen_at and (now - p.last_seen_at).total_seconds() < ONLINE_SECONDS
                ),
                "ready": str(p.seat) in state["bets"],
                "stake_days": state["bets"].get(str(p.seat), {}).get("hours", 0) // H,
            }
            for p in players
        ],
        "round": view_round,
        "me": {
            "seat": me.seat if me else None,
            "actions": actions,
            "extra_hours": extra,
            "balance_hours": bal,
            "in_round": bool(eng and me and any(s["seat"] == me.seat for s in eng["seats"])),
        },
        "last_fair": state.get("last_fair"),
    }


async def touch_seen(db: AsyncSession, room_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await db.execute(
        update(GameRoomPlayer)
        .where(
            GameRoomPlayer.room_id == room_id,
            GameRoomPlayer.user_id == user_id,
            GameRoomPlayer.left_at.is_(None),
        )
        .values(last_seen_at=utcnow())
    )


async def public_rooms(db: AsyncSession, limit: int = 20) -> list[dict[str, Any]]:
    seated = (
        select(GameRoomPlayer.room_id, func.count().label("n"))
        .where(GameRoomPlayer.left_at.is_(None))
        .group_by(GameRoomPlayer.room_id)
        .subquery()
    )
    rows = await db.execute(
        select(GameRoom, seated.c.n)
        .join(seated, seated.c.room_id == GameRoom.id)
        .where(
            GameRoom.status == "open",
            GameRoom.visibility == "public",
            seated.c.n < GameRoom.max_players,
        )
        .order_by(GameRoom.updated_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": str(r.id),
            "code": r.code,
            "players": int(n),
            "max_players": r.max_players,
            "phase": r.phase,
        }
        for r, n in rows.all()
    ]


def profile_out(p: GameProfile) -> dict[str, Any]:
    return {
        "nickname": p.nickname,
        "rounds": p.rounds,
        "wins": p.wins,
        "losses": p.losses,
        "pushes": p.pushes,
        "blackjacks": p.blackjacks,
        "net_hours": p.net_hours,
        "streak": p.streak,
        "best_streak": p.best_streak,
    }


async def history(
    db: AsyncSession, user_id: uuid.UUID, limit: int, offset: int
) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(GameRoundPlayer, GameRound)
        .join(GameRound, GameRound.id == GameRoundPlayer.round_id)
        .where(GameRoundPlayer.user_id == user_id)
        .order_by(GameRound.finished_at.desc())
        .limit(limit)
        .offset(offset)
    )
    out = []
    for rp, rnd in rows.all():
        summary = rnd.summary or {}
        seat = next((s for s in summary.get("seats", []) if s["seat"] == rp.seat), None)
        out.append(
            {
                "round_id": str(rnd.id),
                "finished_at": rnd.finished_at.isoformat() if rnd.finished_at else None,
                "result": rp.result,
                "blackjack": rp.blackjack,
                "staked_hours": rp.staked_hours,
                "returned_hours": rp.returned_hours,
                "net_hours": rp.returned_hours - rp.staked_hours,
                "dealer": summary.get("dealer"),
                "hands": seat["hands"] if seat else [],
                "players": len(summary.get("seats", [])),
            }
        )
    return out


async def leaderboard(db: AsyncSession, user_id: uuid.UUID, limit: int = 20) -> dict[str, Any]:
    order = (
        GameProfile.wins.desc(),
        GameProfile.blackjacks.desc(),
        GameProfile.rounds.asc(),
        GameProfile.user_id,
    )
    rows = (
        await db.scalars(
            select(GameProfile).where(GameProfile.rounds > 0).order_by(*order).limit(limit)
        )
    ).all()
    top = [
        {
            "rank": i + 1,
            "nickname": p.nickname,
            "wins": p.wins,
            "rounds": p.rounds,
            "blackjacks": p.blackjacks,
            "best_streak": p.best_streak,
            "me": p.user_id == user_id,
        }
        for i, p in enumerate(rows)
    ]
    mine = await db.get(GameProfile, user_id)
    my_rank = None
    if mine is not None and mine.rounds > 0:
        better = await db.scalar(
            select(func.count())
            .select_from(GameProfile)
            .where(
                GameProfile.rounds > 0,
                (GameProfile.wins > mine.wins)
                | ((GameProfile.wins == mine.wins) & (GameProfile.blackjacks > mine.blackjacks)),
            )
        )
        my_rank = int(better or 0) + 1
    return {"top": top, "my_rank": my_rank}


async def fairness(db: AsyncSession, round_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    """Seeds of a round the player took part in. The server seed is revealed only afterwards."""
    rnd = await db.get(GameRound, round_id)
    took_part = await db.scalar(
        select(GameRoundPlayer.id).where(
            GameRoundPlayer.round_id == round_id, GameRoundPlayer.user_id == user_id
        )
    )
    if rnd is None or took_part is None:
        raise NotFound("No such round.")
    done = rnd.finished_at is not None
    return {
        "round_id": str(rnd.id),
        "number": rnd.number,
        "server_seed_hash": rnd.server_seed_hash,
        "server_seed": rnd.server_seed if done else None,
        "client_seed": rnd.client_seed,
        "decks": rnd.rules["decks"],
        "algorithm": "HMAC-SHA256(server_seed, client_seed:nonce:counter) → Fisher-Yates, see docs",
        "summary": rnd.summary if done else None,
    }


async def admin_adjust(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    user_id: uuid.UUID,
    delta_days: int,
    reason: str,
    ip: str | None,
) -> int:
    if await db.get(User, user_id) is None:
        raise NotFound("No such user.")
    after = await wallet.move(
        db, user_id, delta_days * H, "admin", f"admin:{uuid.uuid4()}", note=reason[:200]
    )
    audit.record(
        db,
        action="game.bonus_adjusted",
        actor_id=actor_id,
        actor_type=ActorType.USER,
        target_type="user",
        target_id=user_id,
        ip=ip,
        details={"delta_days": delta_days, "reason": reason[:200], "balance_hours": after},
    )
    return after
