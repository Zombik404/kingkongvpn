"""Mini-games: bonus wallet + ledger, rooms, rounds, per-user stats (ADR-019)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
    __table_args__ = (
        CheckConstraint("chips >= 0", name="chips_non_negative"),
        CheckConstraint("xp >= 0", name="xp_non_negative"),
        Index("ix_game_profiles_xp", "xp", "score_at"),
        Index("ix_game_profiles_wins", "wins", "score_at"),
    )

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
    # fun chips: no value, topped up daily (games.chips.daily); the biggest single win counts
    chips: Mapped[int] = mapped_column(Integer, default=1000, server_default="1000")
    chips_day: Mapped[dt.date | None] = mapped_column(Date)
    best_win: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    best_win_stake: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    best_win_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # progression (ADR-021): XP only grows; level is derived from XP and stored for sorting
    xp: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    level: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    avatar: Mapped[str] = mapped_column(String(8), default="🦍", server_default="🦍")
    title: Mapped[str | None] = mapped_column(String(32))  # chosen title (None = level title)
    frame: Mapped[str | None] = mapped_column(String(8))  # gold / silver / bronze (seasons)
    day_streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    best_day_streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_play_day: Mapped[dt.date | None] = mapped_column(Date)
    days_played: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    perfect_wins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # when wins/xp last went up (ties on the boards: whoever got there first)
    score_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # staff decision after a cheating review: hidden from every board (reason in the audit log)
    excluded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


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
    # what the stakes were in: "hours" (bonus wallet), "chips" (fun chips) or None (no stakes)
    currency: Mapped[str | None] = mapped_column(String(8))
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


# --- progression: XP, achievements, daily challenges, seasons (ADR-021) ---------------------
class XpEvent(UUIDPk, Timestamps, Base):
    """Append-only XP history. XP is only ever added (never lost, staked or exchanged);
    (user, idem_key) is unique so a replayed round or reward can't add it twice."""

    __tablename__ = "game_xp_events"
    __table_args__ = (
        UniqueConstraint("user_id", "idem_key", name="uq_game_xp_events_user_idem"),
        CheckConstraint("amount > 0", name="positive"),
        Index("ix_game_xp_events_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    amount: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # round/win/blackjack/challenge/achievement/…
    source: Mapped[str | None] = mapped_column(String(64))  # e.g. round id, achievement code
    idem_key: Mapped[str] = mapped_column(String(96))


class Achievement(UUIDPk, Timestamps, Base):
    """Catalogue (seeded by migration 0010, editable by staff). Progress is read from the
    player's counters (`metric`), so there is no separate progress table to drift."""

    __tablename__ = "game_achievements"
    __table_args__ = (
        CheckConstraint("category IN ('game', 'activity', 'progress', 'season')", name="category"),
        CheckConstraint("threshold > 0", name="threshold"),
        CheckConstraint("xp_reward >= 0", name="xp_reward"),
    )

    code: Mapped[str] = mapped_column(String(32), unique=True)
    category: Mapped[str] = mapped_column(String(12))
    names: Mapped[dict[str, str]] = mapped_column(JSONB)
    descriptions: Mapped[dict[str, str]] = mapped_column(JSONB)
    icon: Mapped[str] = mapped_column(String(8))
    metric: Mapped[str] = mapped_column(String(24))
    threshold: Mapped[int] = mapped_column(Integer)
    xp_reward: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    title: Mapped[str | None] = mapped_column(String(32))  # optional title it unlocks
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class UserAchievement(UUIDPk, Timestamps, Base):
    __tablename__ = "game_user_achievements"
    __table_args__ = (
        UniqueConstraint("user_id", "achievement_id", name="uq_game_user_achievements"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    achievement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_achievements.id", ondelete="CASCADE")
    )
    unlocked_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class ChallengeTemplate(UUIDPk, Timestamps, Base):
    """Daily challenge kinds (seeded, editable by staff)."""

    __tablename__ = "game_challenge_templates"
    __table_args__ = (
        CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="difficulty"),
        CheckConstraint("target > 0", name="target"),
        CheckConstraint("xp_reward >= 0", name="xp_reward"),
    )

    code: Mapped[str] = mapped_column(String(32), unique=True)
    difficulty: Mapped[str] = mapped_column(String(8))
    names: Mapped[dict[str, str]] = mapped_column(JSONB)
    metric: Mapped[str] = mapped_column(String(24))  # rounds / wins / blackjacks / …
    target: Mapped[int] = mapped_column(Integer)
    xp_reward: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class DailyChallenge(UUIDPk, Timestamps, Base):
    """A challenge given to one player for one day (in the game's time zone)."""

    __tablename__ = "game_daily_challenges"
    __table_args__ = (
        UniqueConstraint("user_id", "day", "template_id", name="uq_game_daily_challenges"),
        Index("ix_game_daily_challenges_user_day", "user_id", "day"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    day: Mapped[dt.date] = mapped_column(Date)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_challenge_templates.id", ondelete="CASCADE")
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    target: Mapped[int] = mapped_column(Integer)
    xp_reward: Mapped[int] = mapped_column(Integer)
    run: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # wins in a row today
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class PlayDay(Base):
    """A day (game time zone) on which the player finished at least one round: the streak
    calendar and the "days played" counter."""

    __tablename__ = "game_play_days"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    rounds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    round_xp: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # for the cap


class UserTitle(UUIDPk, Timestamps, Base):
    """Titles won (seasons, streaks, achievements). Level titles are derived, not stored."""

    __tablename__ = "game_user_titles"
    __table_args__ = (UniqueConstraint("user_id", "title", name="uq_game_user_titles"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64))


class Season(UUIDPk, Timestamps, Base):
    __tablename__ = "game_seasons"
    __table_args__ = (
        CheckConstraint("kind IN ('weekly', 'monthly', 'event')", name="kind"),
        CheckConstraint("status IN ('active', 'closed')", name="status"),
        CheckConstraint("ends_at > starts_at", name="dates"),
        Index("ix_game_seasons_status_ends", "status", "ends_at"),
        # one automatic weekly/monthly season per start date
        Index(
            "uq_game_seasons_auto",
            "kind",
            "starts_at",
            unique=True,
            postgresql_where=text("kind IN ('weekly', 'monthly')"),
        ),
    )

    kind: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(64))
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(8), default="active", server_default="active")
    board: Mapped[str] = mapped_column(String(8), default="xp", server_default="xp")
    rewards: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'")
    )
    finalized_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class SeasonStat(Base):
    __tablename__ = "game_season_stats"
    __table_args__ = (
        Index("ix_game_season_stats_xp", "season_id", "xp", "score_at"),
        Index("ix_game_season_stats_wins", "season_id", "wins", "score_at"),
    )

    season_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_seasons.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    rounds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    wins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    losses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pushes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    blackjacks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    xp: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # when the score last went up: equal scores rank by who got there first
    score_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class SeasonResult(Base):
    """Frozen final table of a season (top places of each board)."""

    __tablename__ = "game_season_results"

    season_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_seasons.id", ondelete="CASCADE"), primary_key=True
    )
    board: Mapped[str] = mapped_column(String(8), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    nickname: Mapped[str] = mapped_column(String(24))
    value: Mapped[int] = mapped_column(Integer)  # win rate in basis points (6543 = 65.43 %)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class GameReward(UUIDPk, Timestamps, Base):
    """Every reward given (season place, streak, …): what it was and whether bonus days were
    actually paid (only when games.rewards.bonus_days_enabled). Unique per (user, idem_key)."""

    __tablename__ = "game_rewards"
    __table_args__ = (UniqueConstraint("user_id", "idem_key", name="uq_game_rewards_user_idem"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(16))  # season / streak / achievement / admin
    source_ref: Mapped[str] = mapped_column(String(64))
    xp: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    title: Mapped[str | None] = mapped_column(String(32))
    frame: Mapped[str | None] = mapped_column(String(8))
    bonus_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    bonus_paid: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    idem_key: Mapped[str] = mapped_column(String(96))
