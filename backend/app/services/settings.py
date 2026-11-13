"""Typed global settings ("everything commercial is data"). Each key has a schema and a default;
the DB row overrides the default. Admins change them through the API, never via code."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict
from zoneinfo import available_timezones

from pydantic import AfterValidator, Field, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFound
from app.models import Setting


class RewardTier(TypedDict, total=False):
    """A season prize for places `from`..`to` (inclusive)."""

    places: Annotated[
        list[Annotated[int, Field(ge=1, le=100_000)]], Field(min_length=2, max_length=2)
    ]
    xp: Annotated[int, Field(ge=0, le=100_000)]
    title: Annotated[str, Field(min_length=1, max_length=32)]
    frame: Literal["gold", "silver", "bronze", "jade"]
    bonus_days: Annotated[int, Field(ge=0, le=30)]


class StreakReward(TypedDict, total=False):
    xp: Annotated[int, Field(ge=0, le=100_000)]
    title: Annotated[str, Field(min_length=1, max_length=32)]
    bonus_days: Annotated[int, Field(ge=0, le=30)]


def _tz(v: str) -> str:
    if v not in available_timezones():
        raise ValueError("unknown time zone (use an IANA name like Europe/Moscow or UTC)")
    return v


Xp = Annotated[int, Field(ge=0, le=10_000)]
TimeZone = Annotated[str, AfterValidator(_tz)]

SEASON_REWARDS_WEEKLY: list[dict[str, Any]] = [
    {"places": [1, 1], "xp": 500, "title": "King of Jungle", "frame": "gold", "bonus_days": 3},
    {"places": [2, 2], "xp": 300, "title": "Jungle Champion", "frame": "silver", "bonus_days": 2},
    {"places": [3, 3], "xp": 200, "title": "Jungle Warrior", "frame": "bronze", "bonus_days": 1},
    {"places": [4, 10], "xp": 100},
    {"places": [11, 100], "xp": 30},
]
SEASON_REWARDS_MONTHLY: list[dict[str, Any]] = [
    {"places": [1, 1], "xp": 1500, "title": "King of Jungle", "frame": "gold", "bonus_days": 7},
    {"places": [2, 2], "xp": 900, "title": "Jungle Champion", "frame": "silver", "bonus_days": 5},
    {"places": [3, 3], "xp": 600, "title": "Jungle Warrior", "frame": "bronze", "bonus_days": 3},
    {"places": [4, 10], "xp": 300, "frame": "jade"},
    {"places": [11, 100], "xp": 100},
]


@dataclass(frozen=True)
class SettingDef:
    adapter: TypeAdapter[Any]
    default: Any
    description: str


def _def(tp: Any, default: Any, description: str) -> SettingDef:
    adapter: TypeAdapter[Any] = TypeAdapter(tp)
    adapter.validate_python(default)
    return SettingDef(adapter, default, description)


REGISTRY: dict[str, SettingDef] = {
    "trial.enabled": _def(bool, False, "Offer a free trial to accounts that never had one."),
    "trial.days": _def(Annotated[int, Field(ge=1, le=30)], 3, "Trial length in days."),
    "trial.plan_code": _def(
        Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,31}$")],
        "trial",
        "Code of the plan whose entitlements a trial grants.",
    ),
    "subscription.grace_days": _def(
        Annotated[int, Field(ge=0, le=30)],
        3,
        "Days of continued access after a period ends without renewal.",
    ),
    "devices.limit_without_subscription": _def(
        Annotated[int, Field(ge=0, le=10)],
        1,
        "Devices an account may register before subscribing.",
    ),
    "reminders.days_before": _def(
        Annotated[list[Annotated[int, Field(ge=1, le=30)]], Field(max_length=5)],
        [3],
        "Days before a non-renewing period ends to email a reminder.",
    ),
    "access.invite_only": _def(
        bool,
        False,
        "Closed test: paying or a trial requires having redeemed an invite (free-days) code.",
    ),
    # --- mini-games (ADR-019) ---
    "games.enabled": _def(bool, True, "Mini Games section and Jungle Kong Blackjack."),
    "games.multiplayer_enabled": _def(
        bool, False, "Tables for 2-4 players (off: the owner chose solo play only)."
    ),
    "games.chips.enabled": _def(
        bool,
        True,
        "Fun chips: stakes with no value (no purchase, no exchange) while bonus-day stakes are "
        "off. They make the biggest-win leaderboard work in fun mode.",
    ),
    "games.chips.daily": _def(
        Annotated[int, Field(ge=10, le=1_000_000)], 1000, "Chips are topped up to this every day."
    ),
    "games.chips.stake_options": _def(
        Annotated[
            list[Annotated[int, Field(ge=10, le=100_000, multiple_of=10)]],
            Field(min_length=1, max_length=8),
        ],
        [10, 20, 50, 100, 200, 500],
        "Chip stakes offered (multiples of 10, so 3:2, 6:5 and halves pay whole chips).",
    ),
    "games.blackjack.stakes_enabled": _def(
        bool,
        False,
        "Staking game bonus days. OFF by default: enable only after the legal check for your "
        "target countries. When off the game is for fun: nothing is won or lost.",
    ),
    "games.blackjack.stake_options_days": _def(
        Annotated[list[Annotated[int, Field(ge=1, le=30)]], Field(min_length=1, max_length=6)],
        [1, 2, 3, 5],
        "Stakes a player can choose, in bonus days.",
    ),
    "games.blackjack.daily_win_cap_days": _def(
        Annotated[int, Field(ge=1, le=365)],
        10,
        "A player who is this many bonus days up today can only play for fun until tomorrow.",
    ),
    "games.blackjack.welcome_bonus_days": _def(
        Annotated[int, Field(ge=0, le=30)],
        0,
        "One-time game bonus for a new game profile while stakes are enabled (0 = none).",
    ),
    "games.bonus_redeem_enabled": _def(
        bool, True, "Players may turn whole game bonus days into VPN subscription days."
    ),
    "games.blackjack.decks": _def(Annotated[int, Field(ge=1, le=8)], 6, "Decks in the shoe."),
    "games.blackjack.dealer_hits_soft_17": _def(bool, False, "Dealer draws on a soft 17."),
    "games.blackjack.blackjack_pays": _def(
        Annotated[str, Field(pattern=r"^(3:2|6:5)$")], "3:2", "Blackjack payout: 3:2 or 6:5."
    ),
    "games.blackjack.allow_double": _def(bool, True, "Double Down."),
    "games.blackjack.allow_double_after_split": _def(bool, True, "Double Down after a split."),
    "games.blackjack.allow_split": _def(bool, True, "Split pairs."),
    "games.blackjack.max_hands": _def(Annotated[int, Field(ge=2, le=4)], 4, "Hands after splits."),
    "games.blackjack.allow_surrender": _def(bool, True, "Late surrender (half the stake back)."),
    "games.blackjack.allow_insurance": _def(bool, True, "Insurance against a dealer blackjack."),
    "games.blackjack.turn_seconds": _def(
        Annotated[int, Field(ge=10, le=120)], 30, "Time for a move at a shared table."
    ),
    "games.blackjack.bet_seconds": _def(
        Annotated[int, Field(ge=5, le=60)], 20, "Time to join the next round at a shared table."
    ),
    "referrals.enabled": _def(
        bool, True, "Referral program: discount for invited users, free days for referrers."
    ),
    "referrals.percent_off": _def(
        Annotated[int, Field(ge=1, le=100)],
        30,
        "Discount an invited user gets on their first payment.",
    ),
    "referrals.milestones": _def(
        bool, True, "Referral ranks (3/5/10/25 paying friends) with free days and app themes."
    ),
    "referrals.bonus_days": _def(
        Annotated[int, Field(ge=0, le=365)],
        14,
        "Free days for the referrer per invited user's first payment (0 = off).",
    ),
    # --- blackjack progression (ADR-021) ---
    "games.timezone": _def(
        TimeZone, "UTC", "Time zone for game days, daily challenges and season boundaries."
    ),
    "games.xp.round": _def(Xp, 5, "XP for every finished round."),
    "games.xp.win": _def(Xp, 10, "Extra XP for a win."),
    "games.xp.blackjack": _def(Xp, 10, "Extra XP for a blackjack."),
    "games.xp.daily_round_cap": _def(
        Annotated[int, Field(ge=0, le=100_000)],
        600,
        "Most XP a player can get from rounds in one game day (0 = no limit); challenges, "
        "achievements and rewards are not capped. Slows down bots.",
    ),
    "games.levels.base_xp": _def(
        Annotated[int, Field(ge=10, le=100_000)], 100, "XP from level 1 to level 2."
    ),
    "games.levels.step_xp": _def(
        Annotated[int, Field(ge=0, le=100_000)],
        50,
        "How much more each next level costs (level 2→3 = base + step, 3→4 = base + 2·step…).",
    ),
    "games.levels.titles": _def(
        dict[
            Annotated[str, Field(pattern=r"^[1-9][0-9]{0,3}$")],
            Annotated[str, Field(max_length=32)],
        ],
        {
            "1": "Jungle Rookie",
            "2": "Jungle Explorer",
            "3": "Wild Player",
            "4": "Jungle Hunter",
            "5": "Gorilla Fighter",
            "10": "Jungle Master",
            "20": "King of Jungle",
        },
        "Title for each level (a level without one keeps the title of the level below).",
    ),
    "games.leaderboard.min_rounds_winrate": _def(
        Annotated[int, Field(ge=1, le=10_000)],
        20,
        "Rounds (wins + losses) needed in the period to appear on the win-rate board.",
    ),
    "games.achievements.enabled": _def(bool, True, "Achievements and their XP rewards."),
    "games.challenges.enabled": _def(bool, True, "Daily challenges (easy, medium, hard)."),
    "games.streak.rewards": _def(
        dict[Annotated[str, Field(pattern=r"^[1-9][0-9]{0,3}$")], StreakReward],
        {
            "3": {"xp": 30},
            "7": {"xp": 100},
            "14": {"xp": 250, "title": "Jungle Regular"},
            "30": {"xp": 600, "title": "Jungle Devotee", "bonus_days": 1},
        },
        "Rewards for playing N days in a row (a finished round counts, opening the app doesn't).",
    ),
    "games.seasons.enabled": _def(bool, True, "Weekly and monthly seasons with prizes."),
    "games.seasons.board": _def(
        Literal["xp", "wins"], "xp", "Which season board decides the prizes: xp or wins."
    ),
    "games.seasons.rewards_weekly": _def(
        list[RewardTier], SEASON_REWARDS_WEEKLY, "Prizes of the weekly season by place."
    ),
    "games.seasons.rewards_monthly": _def(
        list[RewardTier], SEASON_REWARDS_MONTHLY, "Prizes of the monthly season by place."
    ),
    "games.seasons.min_rounds": _def(
        Annotated[int, Field(ge=1, le=10_000)], 10, "Rounds in a season needed for a prize."
    ),
    "games.seasons.participation_xp": _def(
        Xp, 20, "XP for everyone who played the minimum rounds in a season (0 = off)."
    ),
    "games.rewards.bonus_days_enabled": _def(
        bool,
        False,
        "Pay the bonus days of season and streak prizes into the game bonus wallet. OFF until "
        "the legal check: until then prizes are XP, titles and frames only.",
    ),
    "peers.idle_ttl_hours": _def(
        Annotated[int, Field(ge=0, le=24 * 90)],
        0,
        "Take a peer off its node after this many hours without a handshake (0 = never). "
        "Keep 0 while users import a fixed config into the WireGuard app (Telegram version): "
        "that app doesn't ask us before connecting, so a removed peer would just stop working "
        "until the user taps Connect in the Mini App again.",
    ),
}


class InvalidSetting(AppError):
    status_code = 422
    code = "invalid_setting"


async def get_value(session: AsyncSession, key: str) -> Any:
    definition = REGISTRY.get(key)
    if definition is None:
        raise NotFound(f"Unknown setting {key!r}.")
    row = await session.get(Setting, key)
    if row is None:
        return definition.default
    try:
        return definition.adapter.validate_python(row.value)
    except ValidationError:
        # A stored value that no longer matches the schema must not break requests.
        return definition.default


async def get_all(session: AsyncSession) -> dict[str, Any]:
    rows = {r.key: r for r in (await session.scalars(select(Setting))).all()}
    out: dict[str, Any] = {}
    for key, definition in REGISTRY.items():
        out[key] = definition.default
        if key in rows:
            try:
                out[key] = definition.adapter.validate_python(rows[key].value)
            except ValidationError:
                pass
    return out


async def set_value(
    session: AsyncSession, key: str, value: Any, *, actor_id: uuid.UUID | None
) -> Any:
    definition = REGISTRY.get(key)
    if definition is None:
        raise NotFound(f"Unknown setting {key!r}.")
    try:
        validated = definition.adapter.validate_python(value, strict=True)
    except ValidationError as exc:
        raise InvalidSetting(f"Invalid value for {key}: {exc.errors()[0]['msg']}") from exc
    stored = definition.adapter.dump_python(validated, mode="json")
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=stored, updated_by=actor_id))
    else:
        row.value = stored
        row.updated_by = actor_id
    return validated
