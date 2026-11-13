"""Mini-games API: Jungle Kong Blackjack (ADR-019).

Players change a table only through POST requests (authenticated, rate limited, idempotent via
`action_id`). The WebSocket is server → client only: it pushes a fresh view of the table when
something changes; clients that can't keep a socket open poll GET /games/rooms/{id} instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import Annotated, Any, Literal

from babel.dates import format_date
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Ctx, CurrentPrincipal, Db, principal_from_token
from app.core.context import AppContext
from app.core.errors import AppError, NotFound, PermissionDenied
from app.games import boards, progress, views, wallet
from app.games import service as games
from app.models import BonusLedger, GameRoom, Season
from app.notifications.notify import miniapp_url, notify
from app.security.rate_limit import Limit

router = APIRouter(prefix="/games", tags=["games"])

ACTIONS_PER_USER = Limit("game-act", 180, 60)
ROOMS_PER_USER = Limit("game-room", 30, 600)
JOINS_PER_USER = Limit("game-join", 30, 60)  # also slows guessing private table codes
REDEEM_PER_USER = Limit("game-redeem", 10, 3600)
READS_PER_USER = Limit("game-read", 120, 60)  # boards, seasons, achievements, challenges

ActionId = Annotated[
    str | None, Field(default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
]


class ProfileIn(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=64)
    avatar: str | None = Field(default=None, max_length=8)
    title: str | None = Field(default=None, max_length=32)  # "" = back to the level title


class RoomCreateIn(BaseModel):
    max_players: int = Field(ge=1, le=4)
    visibility: Literal["public", "private"] = "private"


class JoinIn(BaseModel):
    code: str | None = Field(default=None, min_length=4, max_length=8)
    room_id: uuid.UUID | None = None


class BetIn(BaseModel):
    stake_days: int = Field(default=0, ge=0, le=30)
    stake: int | None = Field(default=None, ge=0, le=100_000)  # in the table's currency
    client_seed: str | None = Field(default=None, max_length=64)
    action_id: ActionId


class ActionIn(BaseModel):
    action: Literal["hit", "stand", "double", "split", "surrender", "insurance", "no_insurance"]
    action_id: ActionId


class RedeemIn(BaseModel):
    days: int = Field(ge=1, le=365)
    action_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


async def _view(db: Db, room: GameRoom, user_id: uuid.UUID) -> dict[str, Any]:
    await games.touch_seen(db, room.id, user_id)
    view = await games.room_view(db, room, user_id)
    await db.commit()
    return view


@router.get("")
async def hub(principal: CurrentPrincipal, db: Db) -> dict[str, Any]:
    """Everything the Mini Games screen needs: switches, profile and statistics, bonus balance,
    and the table the player is sitting at (if any)."""
    uid = principal.user.id
    cfg = await games.config(db)
    profile = await games.ensure_profile(db, uid, cfg) if cfg["games.enabled"] else None
    seat = await games.current_seat(db, uid)
    bal = (await wallet.get_wallet(db, uid)).balance_hours
    cur = games.currency_of(cfg)
    chips = await games.chips_of(db, uid, cfg) if profile is not None else 0
    await db.commit()
    stakes = bool(cfg["games.blackjack.stakes_enabled"])
    return {
        "enabled": bool(cfg["games.enabled"]),
        "multiplayer": bool(cfg["games.multiplayer_enabled"]),
        "stakes": stakes,
        "stake_options_days": cfg["games.blackjack.stake_options_days"] if stakes else [],
        "redeem_enabled": bool(cfg["games.bonus_redeem_enabled"]),
        "balance_hours": bal,
        "currency": cur,
        "chips": chips if cur == games.CHIPS else None,
        "chips_daily": cfg["games.chips.daily"],
        "chip_options": cfg["games.chips.stake_options"],
        "profile": games.profile_out(profile) if profile else None,
        "progress": views.card(profile, cfg) if profile else None,
        "room_id": str(seat.room_id) if seat else None,
        "rules": games.rules_from(cfg).to_json(),
    }


@router.put("/profile")
async def set_profile(body: ProfileIn, principal: CurrentPrincipal, db: Db) -> dict[str, Any]:
    """Nickname, avatar (one of the offered ones) and the title to wear (only titles earned)."""
    cfg = await games.config(db)
    profile = await games.ensure_profile(db, principal.user.id, cfg, body.nickname)
    await views.set_looks(db, profile, cfg, avatar=body.avatar, title=body.title)
    await db.commit()
    return {**games.profile_out(profile), "progress": views.card(profile, cfg)}


async def _profile(ctx: Ctx, db: Db, uid: uuid.UUID) -> tuple[dict[str, Any], Any]:
    await ctx.limiter.hit(READS_PER_USER, str(uid))
    cfg = await games.config(db)
    if not cfg["games.enabled"]:
        raise AppError("Mini games are switched off.", code="games_disabled")
    return cfg, await games.ensure_profile(db, uid, cfg)


@router.get("/me")
async def my_profile(principal: CurrentPrincipal, ctx: Ctx, db: Db) -> dict[str, Any]:
    """The game profile: level and XP, statistics, ranks, titles, achievements so far, avatars
    to choose from, the latest rounds."""
    uid = principal.user.id
    cfg, p = await _profile(ctx, db, uid)
    ach = await views.achievements(db, p)
    out = {
        **views.card(p, cfg),
        "ranks": await views.ranks(db, cfg, uid),
        "titles": await views.titles_of(db, p, cfg),
        "chosen_title": p.title,
        "avatars": list(progress.AVATARS),
        "achievements": {
            "unlocked": sum(1 for a in ach if a["unlocked_at"]),
            "total": len(ach),
            "latest": sorted(
                (a for a in ach if a["unlocked_at"]), key=lambda a: a["unlocked_at"], reverse=True
            )[:6],
        },
        "recent": await games.history(db, uid, 5, 0),
    }
    await db.commit()
    return out


@router.get("/achievements")
async def my_achievements(principal: CurrentPrincipal, ctx: Ctx, db: Db) -> list[dict[str, Any]]:
    _cfg, p = await _profile(ctx, db, principal.user.id)
    out = await views.achievements(db, p)
    await db.commit()
    return out


@router.get("/challenges")
async def my_challenges(principal: CurrentPrincipal, ctx: Ctx, db: Db) -> dict[str, Any]:
    """Today's challenges (handed out on first look), the daily streak and its calendar."""
    cfg, p = await _profile(ctx, db, principal.user.id)
    out = await views.challenges(db, cfg, p)
    await db.commit()
    return out


@router.get("/xp")
async def my_xp(
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[dict[str, Any]]:
    await ctx.limiter.hit(READS_PER_USER, str(principal.user.id))
    return await views.xp_history(db, principal.user.id, offset, limit)


@router.get("/rewards")
async def my_rewards(
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[dict[str, Any]]:
    await ctx.limiter.hit(READS_PER_USER, str(principal.user.id))
    return await views.rewards(db, principal.user.id, offset, limit)


@router.get("/boards")
async def leaderboards(
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: Db,
    board: Annotated[Literal["wins", "winrate", "xp"], Query()] = "xp",
    period: Annotated[Literal["all", "weekly", "monthly"], Query()] = "all",
    season_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=24)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> dict[str, Any]:
    """Wins / win rate / XP for all time, this week's or this month's season, or any season."""
    cfg, _p = await _profile(ctx, db, principal.user.id)
    season = None
    if season_id is not None:
        season = await db.get(Season, season_id)
        if season is None:
            raise NotFound("No such season.")
    elif period != "all":
        season = await boards.current(db, period)
        if season is None:  # the first round of the week opens it; show the empty board
            await boards.ensure_current(db, cfg)
            season = await boards.current(db, period)
    out = await boards.board(
        db, cfg, board, season=season, user_id=principal.user.id, offset=offset, limit=limit,
        q=(q or "").strip() or None,
    )  # fmt: skip
    await db.commit()
    return out


@router.get("/seasons")
async def seasons(
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> dict[str, Any]:
    """This week's and month's seasons (timer, prizes, top 3, my place) and the archive."""
    cfg, _p = await _profile(ctx, db, principal.user.id)
    await boards.ensure_current(db, cfg)
    out = await views.seasons(db, cfg, principal.user.id, offset, limit)
    await db.commit()
    return out


@router.get("/seasons/{season_id}/results")
async def season_results(
    season_id: uuid.UUID,
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: Db,
    board: Annotated[Literal["wins", "winrate", "xp"], Query()] = "xp",
) -> dict[str, Any]:
    await ctx.limiter.hit(READS_PER_USER, str(principal.user.id))
    season = await db.get(Season, season_id)
    if season is None or season.status != "closed":
        raise NotFound("No final results for this season.")
    rows = await boards.results(db, season.id, board)
    for r in rows:
        r["me"] = r.pop("user_id") == str(principal.user.id)
    return {"season": boards.season_out(season), "board": board, "rows": rows}


@router.get("/wallet")
async def get_wallet(
    principal: CurrentPrincipal, db: Db, limit: Annotated[int, Query(ge=1, le=100)] = 30
) -> dict[str, Any]:
    """Bonus balance and the history of every change to it."""
    uid = principal.user.id
    w = await wallet.get_wallet(db, uid)
    rows = await db.scalars(
        select(BonusLedger)
        .where(BonusLedger.user_id == uid)
        .order_by(BonusLedger.created_at.desc())
        .limit(limit)
    )
    await db.commit()
    return {
        "balance_hours": w.balance_hours,
        "ledger": [
            {
                "at": r.created_at.isoformat(),
                "delta_hours": r.delta_hours,
                "balance_after": r.balance_after,
                "kind": r.kind,
                "round_id": str(r.round_id) if r.round_id else None,
            }
            for r in rows.all()
        ],
    }


@router.post("/wallet/redeem")
async def redeem(body: RedeemIn, principal: CurrentPrincipal, ctx: Ctx, db: Db) -> dict[str, Any]:
    """Turn whole bonus days into VPN days (one way: they can't come back to the game)."""
    cfg = await games.config(db)
    if not cfg["games.bonus_redeem_enabled"]:
        raise AppError(
            "Exchanging bonus days is turned off.", code="redeem_disabled", status_code=409
        )
    await ctx.limiter.hit(REDEEM_PER_USER, str(principal.user.id))
    sub = await wallet.redeem(db, principal.user.id, body.days, f"redeem:{body.action_id}")
    bal = (await wallet.get_wallet(db, principal.user.id)).balance_hours
    await db.commit()
    user = principal.user
    await notify(
        ctx,
        user,
        "game_redeem",
        {
            "days": str(body.days),
            "date": format_date(sub.current_period_end, format="long", locale=user.locale),
            "balance": games.fmt_days(bal, user.locale),
        },
        miniapp_url(ctx),
    )
    return {
        "days": body.days,
        "balance_hours": bal,
        "access_until": sub.current_period_end.isoformat(),
    }


@router.get("/rooms")
async def list_rooms(principal: CurrentPrincipal, db: Db) -> list[dict[str, Any]]:
    """Open public tables with a free seat."""
    return await games.public_rooms(db)


@router.post("/rooms", status_code=201)
async def create_room(
    body: RoomCreateIn, principal: CurrentPrincipal, ctx: Ctx, db: Db
) -> dict[str, Any]:
    await ctx.limiter.hit(ROOMS_PER_USER, str(principal.user.id))
    room = await games.create_room(
        db, ctx, principal.user.id, max_players=body.max_players, visibility=body.visibility
    )
    return await _view(db, room, principal.user.id)


@router.post("/rooms/solo")
async def solo(principal: CurrentPrincipal, ctx: Ctx, db: Db) -> dict[str, Any]:
    """The player's own table against the dealer (created on first use)."""
    await ctx.limiter.hit(ROOMS_PER_USER, str(principal.user.id))
    room = await games.solo_room(db, ctx, principal.user.id)
    return await _view(db, room, principal.user.id)


@router.post("/rooms/join")
async def join(body: JoinIn, principal: CurrentPrincipal, ctx: Ctx, db: Db) -> dict[str, Any]:
    """Sit down at a table: public by id, private only with its code."""
    await ctx.limiter.hit(JOINS_PER_USER, str(principal.user.id))
    room = await games.join_room(db, ctx, principal.user.id, room_id=body.room_id, code=body.code)
    view = await _view(db, room, principal.user.id)
    await games.publish(ctx, room)
    return view


async def _member_room(db: Db, room_id: uuid.UUID, user_id: uuid.UUID) -> GameRoom:
    room = await db.get(GameRoom, room_id, populate_existing=True)
    if room is None:
        raise NotFound("No such table.")
    seat = await games.current_seat(db, user_id)
    if seat is None or seat.room_id != room_id:
        raise PermissionDenied("You are not at this table.")
    return room


@router.get("/rooms/{room_id}")
async def get_room(
    room_id: uuid.UUID, principal: CurrentPrincipal, ctx: Ctx, db: Db
) -> dict[str, Any]:
    """The table as this player may see it. Also applies an expired turn timer."""
    room = await _member_room(db, room_id, principal.user.id)
    if room.deadline is not None and room.status == "open":
        ticked = await games.tick(db, room_id)
        await db.commit()
        if ticked is not None:
            await games.publish(ctx, ticked)
        room = await _member_room(db, room_id, principal.user.id)
    return await _view(db, room, principal.user.id)


@router.post("/rooms/{room_id}/bet")
async def bet(
    room_id: uuid.UUID, body: BetIn, principal: CurrentPrincipal, ctx: Ctx, db: Db
) -> dict[str, Any]:
    """Confirm taking part in the next round (and the stake, when stakes are enabled)."""
    await ctx.limiter.hit(ACTIONS_PER_USER, str(principal.user.id))
    room = await games.place_bet(
        db,
        principal.user.id,
        room_id,
        stake_days=body.stake_days,
        stake=body.stake,
        client_seed=body.client_seed,
        action_id=body.action_id,
    )
    view = await _view(db, room, principal.user.id)
    await games.publish(ctx, room)
    return view


@router.post("/rooms/{room_id}/actions")
async def action(
    room_id: uuid.UUID, body: ActionIn, principal: CurrentPrincipal, ctx: Ctx, db: Db
) -> dict[str, Any]:
    await ctx.limiter.hit(ACTIONS_PER_USER, str(principal.user.id))
    room = await games.act(db, principal.user.id, room_id, body.action, body.action_id)
    view = await _view(db, room, principal.user.id)
    await games.publish(ctx, room)
    return view


@router.post("/rooms/{room_id}/leave", status_code=204)
async def leave(room_id: uuid.UUID, principal: CurrentPrincipal, ctx: Ctx, db: Db) -> None:
    room = await games.leave_room(db, principal.user.id, room_id)
    await db.commit()
    await games.publish(ctx, room)


@router.get("/history")
async def history(
    principal: CurrentPrincipal,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=5000)] = 0,
) -> list[dict[str, Any]]:
    return await games.history(db, principal.user.id, limit, offset)


@router.get("/leaderboard")
async def leaderboard(principal: CurrentPrincipal, db: Db) -> dict[str, Any]:
    return await games.leaderboard(db, principal.user.id)


@router.get("/rounds/{round_id}/fairness")
async def fairness(round_id: uuid.UUID, principal: CurrentPrincipal, db: Db) -> dict[str, Any]:
    """Seeds for checking a finished round (see documentation/GAMES_BLACKJACK.md)."""
    return await games.fairness(db, round_id, principal.user.id)


# --------------------------------------------------------------------------- realtime
async def room_updates(
    ctx: AppContext, room_id: uuid.UUID, user_id: uuid.UUID, *, heartbeat: float = 5.0
) -> Any:
    """Yield the player's view of the table: once now, then after every change (or heartbeat,
    which also applies expired timers and keeps the player marked as online)."""
    pubsub = ctx.redis.pubsub()
    await pubsub.subscribe(games.channel(room_id))
    try:
        last = -1
        while True:
            event: dict[str, Any] | None = None
            async with ctx.sessionmaker() as db:
                room = await db.get(GameRoom, room_id)
                seat = await games.current_seat(db, user_id)
                if room is None or seat is None or seat.room_id != room_id:
                    event = {"type": "left"}
                else:
                    if room.deadline is not None and room.status == "open":
                        ticked = await games.tick(db, room_id)
                        await db.commit()
                        if ticked is not None:
                            await games.publish(ctx, ticked)
                            room = await db.get(GameRoom, room_id, populate_existing=True)
                            assert room is not None
                    await games.touch_seen(db, room_id, user_id)
                    if room.version != last:
                        last = room.version
                        event = {"type": "room", "room": await games.room_view(db, room, user_id)}
                    await db.commit()  # never hold a transaction (and its row locks) across a yield
            if event is not None:
                yield event
                if event["type"] == "left":
                    return
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(heartbeat):
                    while True:
                        msg = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=heartbeat
                        )
                        if msg is not None:
                            break
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe()
            await pubsub.aclose()  # type: ignore[no-untyped-call]


@router.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    """First message: {"token": <access token>, "room": <room id>}. Then the server only sends."""
    ctx: AppContext = websocket.app.state.ctx
    await websocket.accept()
    try:
        async with asyncio.timeout(10):
            hello = await websocket.receive_json()
        room_id = uuid.UUID(str(hello["room"]))
        async with ctx.sessionmaker() as db:
            principal = await principal_from_token(ctx, db, str(hello["token"]))
            await _member_room(db, room_id, principal.user.id)
        user_id = principal.user.id
    except (AppError, KeyError, ValueError, TimeoutError, WebSocketDisconnect):
        with contextlib.suppress(Exception):
            await websocket.close(code=4401)
        return

    async def pump() -> None:
        async for event in room_updates(ctx, room_id, user_id):
            await websocket.send_json(event)
            if event["type"] == "left":
                return

    sender = asyncio.create_task(pump())
    try:
        while not sender.done():  # the client only sends pings; a close ends the loop
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(1):
                    await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        sender.cancel()
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await sender
        with contextlib.suppress(Exception):
            await websocket.close()
