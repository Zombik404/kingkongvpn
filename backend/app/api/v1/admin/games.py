"""Staff API for mini-games: tables, rounds, bonus ledger, statistics, suspicious activity.
Same rules as the rest of the admin API: a permission on an MFA-verified session, and an
audit-log row for every change. Game switches and rules are ordinary settings
(`games.*` via /admin/settings)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from app.api.deps import Client, Ctx, Db, require
from app.games import service as games
from app.games import wallet
from app.models import (
    AuditLog,
    BonusLedger,
    BonusWallet,
    GameProfile,
    GameRoom,
    GameRoomPlayer,
    GameRound,
    GameRoundPlayer,
)
from app.models.base import utcnow
from app.security.principal import Principal
from app.security.rbac import Perm
from app.services import audit

router = APIRouter(prefix="/admin/games", tags=["admin", "games"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100_000)]
Reader = Annotated[Principal, Depends(require(Perm.GAMES_READ))]
Writer = Annotated[Principal, Depends(require(Perm.GAMES_WRITE))]


class BonusAdjustIn(BaseModel):
    delta_days: int = Field(ge=-365, le=365)
    reason: str = Field(min_length=3, max_length=200)


class RoomActionIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


def _room_out(room: GameRoom, players: int) -> dict[str, Any]:
    return {
        "id": str(room.id),
        "code": room.code,
        "visibility": room.visibility,
        "max_players": room.max_players,
        "players": players,
        "status": room.status,
        "phase": room.phase,
        "round_no": room.round_no,
        "updated_at": room.updated_at.isoformat(),
    }


@router.get("/overview")
async def overview(_: Reader, db: Db) -> dict[str, Any]:
    """Live numbers and today's bonus movements."""
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    cfg = await games.config(db)
    open_rooms = await db.scalar(
        select(func.count()).select_from(GameRoom).where(GameRoom.status == "open")
    )
    seated = await db.scalar(
        select(func.count()).select_from(GameRoomPlayer).where(GameRoomPlayer.left_at.is_(None))
    )
    rounds_today = await db.scalar(
        select(func.count()).select_from(GameRound).where(GameRound.finished_at >= today)
    )
    moved = (
        await db.execute(
            select(BonusLedger.kind, func.coalesce(func.sum(BonusLedger.delta_hours), 0))
            .where(BonusLedger.created_at >= today)
            .group_by(BonusLedger.kind)
        )
    ).all()
    total = await db.scalar(select(func.coalesce(func.sum(BonusWallet.balance_hours), 0)))
    return {
        "enabled": cfg["games.enabled"],
        "stakes_enabled": cfg["games.blackjack.stakes_enabled"],
        "multiplayer_enabled": cfg["games.multiplayer_enabled"],
        "open_rooms": int(open_rooms or 0),
        "seated_players": int(seated or 0),
        "rounds_today": int(rounds_today or 0),
        "bonus_hours_today": {k: int(v) for k, v in moved},
        "bonus_hours_outstanding": int(total or 0),
    }


@router.get("/rooms")
async def rooms(
    _: Reader,
    db: Db,
    status: Annotated[str | None, Query(pattern="^(open|paused|closed)$")] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict[str, Any]]:
    seated = (
        select(GameRoomPlayer.room_id, func.count().label("n"))
        .where(GameRoomPlayer.left_at.is_(None))
        .group_by(GameRoomPlayer.room_id)
        .subquery()
    )
    stmt = select(GameRoom, func.coalesce(seated.c.n, 0)).outerjoin(
        seated, seated.c.room_id == GameRoom.id
    )
    if status:
        stmt = stmt.where(GameRoom.status == status)
    rows = await db.execute(stmt.order_by(GameRoom.updated_at.desc()).limit(limit).offset(offset))
    return [_room_out(r, int(n)) for r, n in rows.all()]


async def _room_change(
    db: Db, ctx: Ctx, actor: Principal, client: Client, room: GameRoom, action: str, reason: str
) -> dict[str, Any]:
    audit.record(
        db,
        action=action,
        actor_id=actor.user.id,
        target_type="game_room",
        target_id=room.id,
        ip=client.ip,
        details={"reason": reason, "code": room.code},
    )
    await db.commit()
    await db.refresh(room)
    await games.publish(ctx, room)
    return _room_out(room, len(await games.players_of(db, room.id)))


@router.post("/rooms/{room_id}/pause")
async def pause_room(
    room_id: uuid.UUID, body: RoomActionIn, actor: Writer, ctx: Ctx, db: Db, client: Client
) -> dict[str, Any]:
    room = await games.set_paused(db, room_id, True)
    return await _room_change(db, ctx, actor, client, room, "game.room_paused", body.reason)


@router.post("/rooms/{room_id}/resume")
async def resume_room(
    room_id: uuid.UUID, body: RoomActionIn, actor: Writer, ctx: Ctx, db: Db, client: Client
) -> dict[str, Any]:
    room = await games.set_paused(db, room_id, False)
    return await _room_change(db, ctx, actor, client, room, "game.room_resumed", body.reason)


@router.post("/rooms/{room_id}/close")
async def close_room(
    room_id: uuid.UUID, body: RoomActionIn, actor: Writer, ctx: Ctx, db: Db, client: Client
) -> dict[str, Any]:
    """Finish the running round (everyone stands), refund unplayed stakes, close the table."""
    room = await games.close_room(db, room_id, reason="closed by staff")
    return await _room_change(db, ctx, actor, client, room, "game.room_closed", body.reason)


@router.get("/rounds")
async def rounds(
    _: Reader,
    db: Db,
    user_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict[str, Any]]:
    stmt = select(GameRound).where(GameRound.finished_at.is_not(None))
    if room_id:
        stmt = stmt.where(GameRound.room_id == room_id)
    if user_id:
        stmt = stmt.where(
            GameRound.id.in_(
                select(GameRoundPlayer.round_id).where(GameRoundPlayer.user_id == user_id)
            )
        )
    rows = (
        await db.scalars(stmt.order_by(GameRound.finished_at.desc()).limit(limit).offset(offset))
    ).all()
    out = []
    for r in rows:
        players = (
            await db.scalars(select(GameRoundPlayer).where(GameRoundPlayer.round_id == r.id))
        ).all()
        out.append(
            {
                "id": str(r.id),
                "room_id": str(r.room_id),
                "number": r.number,
                "stakes": r.stakes,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "dealer": (r.summary or {}).get("dealer"),
                "players": [
                    {
                        "user_id": str(p.user_id),
                        "seat": p.seat,
                        "result": p.result,
                        "blackjack": p.blackjack,
                        "staked_hours": p.staked_hours,
                        "returned_hours": p.returned_hours,
                    }
                    for p in players
                ],
                "server_seed": r.server_seed,
                "server_seed_hash": r.server_seed_hash,
                "client_seed": r.client_seed,
            }
        )
    return out


@router.get("/ledger")
async def ledger(
    _: Reader, db: Db, user_id: uuid.UUID | None = None, limit: Limit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    stmt = select(BonusLedger)
    if user_id:
        stmt = stmt.where(BonusLedger.user_id == user_id)
    rows = await db.scalars(
        stmt.order_by(BonusLedger.created_at.desc()).limit(limit).offset(offset)
    )
    return [
        {
            "at": r.created_at.isoformat(),
            "user_id": str(r.user_id),
            "delta_hours": r.delta_hours,
            "balance_after": r.balance_after,
            "kind": r.kind,
            "round_id": str(r.round_id) if r.round_id else None,
            "note": r.note,
        }
        for r in rows.all()
    ]


@router.get("/players")
async def players(
    _: Reader, db: Db, user_id: uuid.UUID | None = None, limit: Limit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    """Player statistics and balances; without `user_id` - the leaderboard (most wins first)."""
    stmt = select(GameProfile, func.coalesce(BonusWallet.balance_hours, 0)).outerjoin(
        BonusWallet, BonusWallet.user_id == GameProfile.user_id
    )
    if user_id:
        stmt = stmt.where(GameProfile.user_id == user_id)
    rows = await db.execute(stmt.order_by(GameProfile.wins.desc()).limit(limit).offset(offset))
    return [
        {"user_id": str(p.user_id), **games.profile_out(p), "balance_hours": int(b)}
        for p, b in rows.all()
    ]


@router.get("/suspicious")
async def suspicious(
    _: Reader,
    db: Db,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
    min_rounds: Annotated[int, Query(ge=10, le=1000)] = 30,
) -> list[dict[str, Any]]:
    """Players whose recent results are far from what blackjack allows: a win rate above 60 %
    over many rounds, or a large net bonus gain. A starting point for a manual look, not proof."""
    since = utcnow() - dt.timedelta(days=days)
    wins = func.sum(case((GameRoundPlayer.result == "win", 1), else_=0))
    net = func.sum(GameRoundPlayer.returned_hours - GameRoundPlayer.staked_hours)
    n = func.count()
    rows = await db.execute(
        select(GameRoundPlayer.user_id, n, wins, net)
        .where(GameRoundPlayer.created_at >= since)
        .group_by(GameRoundPlayer.user_id)
        .having((n >= min_rounds) & ((wins * 100 > n * 60) | (net > 24 * 30)))
        .order_by(net.desc())
        .limit(100)
    )
    return [
        {
            "user_id": str(u),
            "rounds": int(c),
            "wins": int(w),
            "win_rate": round(int(w) / int(c), 3),
            "net_hours": int(h),
        }
        for u, c, w, h in rows.all()
    ]


@router.get("/events")
async def events(_: Reader, db: Db, limit: Limit = 50, offset: Offset = 0) -> list[dict[str, Any]]:
    """Game-related audit events: staff actions, bonus adjustments and exchanges."""
    rows = await db.scalars(
        select(AuditLog)
        .where(AuditLog.action.like("game.%"))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        {
            "at": r.created_at.isoformat(),
            "action": r.action,
            "actor_id": str(r.actor_id) if r.actor_id else None,
            "target_id": r.target_id,
            "details": r.details,
        }
        for r in rows.all()
    ]


@router.post("/players/{user_id}/bonus")
async def adjust_bonus(
    user_id: uuid.UUID, body: BonusAdjustIn, actor: Writer, db: Db, client: Client
) -> dict[str, Any]:
    """Add or remove game bonus days by hand (never below zero); always audited."""
    after = await games.admin_adjust(
        db,
        actor_id=actor.user.id,
        user_id=user_id,
        delta_days=body.delta_days,
        reason=body.reason,
        ip=client.ip,
    )
    await db.commit()
    return {
        "user_id": str(user_id),
        "balance_hours": after,
        "balance_days": after / wallet.HOURS_PER_DAY,
    }
