"""Mini-games: bonus wallet + ledger, rooms, rounds, per-user stats (ADR-019)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk


class BonusWallet(Timestamps, Base):
    """Game bonus balance, in hours. Completely separate from the subscription: paid days are
    never here and can never be staked; the balance cannot go below zero."""

    __tablename__ = "bonus_wallets"
    __table_args__ = (CheckConstraint("balance_hours >= 0", name="non_negative"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    balance_hours: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    welcome_granted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class BonusLedger(UUIDPk, Timestamps, Base):
    """Append-only history of every balance change. (user, idem_key) is unique, so replaying a
    request or a settlement can't move the balance twice."""

    __tablename__ = "bonus_ledger"
    __table_args__ = (UniqueConstraint("user_id", "idem_key", name="uq_bonus_ledger_user_idem"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    delta_hours: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(
        String(24)
    )  # stake / payout / refund / redeem / admin / welcome
    idem_key: Mapped[str] = mapped_column(String(96))
    round_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    note: Mapped[str | None] = mapped_column(String(200))


class GameProfile(Timestamps, Base):
    """One game profile per account: display name and lifetime statistics."""

    __tablename__ = "game_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    nickname: Mapped[str] = mapped_column(String(24))
    rounds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    wins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    losses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pushes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    blackjacks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    net_hours: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    best_streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class GameRoom(UUIDPk, Timestamps, Base):
    """A blackjack table for 1-4 players. `state` holds the live round including the shoe and the
    next server seed — it is never sent to clients as is (see games.service.room_view)."""

    __tablename__ = "game_rooms"
    __table_args__ = (
        CheckConstraint("max_players BETWEEN 1 AND 4", name="max_players"),
        CheckConstraint("visibility IN ('public', 'private')", name="visibility"),
        CheckConstraint("status IN ('open', 'paused', 'closed')", name="status"),
        Index("ix_game_rooms_status_deadline", "status", "deadline"),
    )

    code: Mapped[str] = mapped_column(String(8), unique=True)
    game: Mapped[str] = mapped_column(String(16), default="blackjack", server_default="blackjack")
    visibility: Mapped[str] = mapped_column(String(8), default="private", server_default="private")
    max_players: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(8), default="open", server_default="open")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    phase: Mapped[str] = mapped_column(String(12), default="waiting", server_default="waiting")
    round_no: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deadline: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'"))
    round_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class GameRoomPlayer(UUIDPk, Timestamps, Base):
    __tablename__ = "game_room_players"
    __table_args__ = (
        CheckConstraint("seat BETWEEN 0 AND 3", name="seat"),
        # one seat per player, one player per seat — among those still at the table
        Index(
            "uq_game_room_players_seat",
            "room_id",
            "seat",
            unique=True,
            postgresql_where=text("left_at IS NULL"),
        ),
        Index(
            "uq_game_room_players_user",
            "user_id",
            unique=True,
            postgresql_where=text("left_at IS NULL"),
        ),
    )

    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_rooms.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    seat: Mapped[int] = mapped_column(Integer)
    left_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    missed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class GameRound(UUIDPk, Timestamps, Base):
    """A finished (or running) round, kept for history and fairness verification. `server_seed`
    is only exposed once `finished_at` is set."""

    __tablename__ = "game_rounds"
    __table_args__ = (UniqueConstraint("room_id", "number", name="uq_game_rounds_room_number"),)

    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_rooms.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    server_seed: Mapped[str] = mapped_column(String(64))
    server_seed_hash: Mapped[str] = mapped_column(String(64))
    client_seed: Mapped[str] = mapped_column(String(400))
    stakes: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class GameRoundPlayer(UUIDPk, Timestamps, Base):
    __tablename__ = "game_round_players"
    __table_args__ = (
        UniqueConstraint("round_id", "user_id", name="uq_game_round_players_round_user"),
    )

    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_rounds.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    seat: Mapped[int] = mapped_column(Integer)
    staked_hours: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    returned_hours: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    result: Mapped[str | None] = mapped_column(String(8))  # win / lose / push
    blackjack: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
