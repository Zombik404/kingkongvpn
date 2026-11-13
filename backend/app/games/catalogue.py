# ruff: noqa: RUF001  (Russian names in the catalogue)
"""Default achievements and daily challenge kinds (ADR-021).

Migration 0010 seeds them; staff can edit or add more in the admin panel. `seed()` puts back any
missing default (by code) without touching edited rows — the tests use it after wiping tables.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection


def _t(ru: str, en: str) -> dict[str, str]:
    return {"ru": ru, "en": en}


# code, category, icon, metric, threshold, xp, names, descriptions, title
ACHIEVEMENTS = [
    (
        "first_victory",
        "game",
        "🏆",
        "wins",
        1,
        20,
        _t("Первая победа", "First Victory"),
        _t("Обыграйте Кинг-Конга в первый раз.", "Beat King Kong for the first time."),
        None,
    ),
    (
        "lucky_seven",
        "game",
        "🍀",
        "wins",
        7,
        40,
        _t("Счастливая семёрка", "Lucky Seven"),
        _t("Выиграйте 7 партий.", "Win 7 rounds."),
        None,
    ),
    (
        "blackjack_master",
        "game",
        "🃏",
        "blackjacks",
        10,
        100,
        _t("Мастер блэкджека", "Blackjack Master"),
        _t("Соберите 10 блэкджеков.", "Get 10 blackjacks."),
        None,
    ),
    (
        "unstoppable",
        "game",
        "🔥",
        "best_win_streak",
        5,
        100,
        _t("Неудержимый", "Unstoppable"),
        _t("Выиграйте 5 партий подряд.", "Win 5 rounds in a row."),
        None,
    ),
    (
        "perfect_player",
        "game",
        "🎯",
        "perfect_wins",
        1,
        30,
        _t("Идеальная игра", "Perfect Player"),
        _t("Выиграйте с ровно 21 очком (не блэкджеком).", "Win with exactly 21 (not a blackjack)."),
        None,
    ),
    (
        "jungle_legend",
        "game",
        "🌴",
        "wins",
        100,
        300,
        _t("Легенда джунглей", "Jungle Legend"),
        _t("Выиграйте 100 партий.", "Win 100 rounds."),
        None,
    ),
    (
        "king_slayer",
        "game",
        "👑",
        "wins",
        500,
        1000,
        _t("Победитель короля", "King Slayer"),
        _t("Обыграйте дилера 500 раз.", "Beat the dealer 500 times."),
        "King Slayer",
    ),
    (
        "first_steps",
        "activity",
        "👣",
        "rounds",
        1,
        10,
        _t("Первые шаги", "First Steps"),
        _t("Сыграйте первую партию.", "Finish your first round."),
        None,
    ),
    (
        "daily_player",
        "activity",
        "📅",
        "best_day_streak",
        3,
        50,
        _t("Каждый день", "Daily Player"),
        _t("Играйте 3 дня подряд.", "Play 3 days in a row."),
        None,
    ),
    (
        "dedicated_player",
        "activity",
        "💪",
        "rounds",
        100,
        150,
        _t("Преданный игрок", "Dedicated Player"),
        _t("Сыграйте 100 партий.", "Finish 100 rounds."),
        None,
    ),
    (
        "veteran",
        "activity",
        "🎖️",
        "rounds",
        500,
        500,
        _t("Ветеран", "Veteran"),
        _t("Сыграйте 500 партий.", "Finish 500 rounds."),
        None,
    ),
    (
        "jungle_addict",
        "activity",
        "🐒",
        "days_played",
        30,
        300,
        _t("Житель джунглей", "Jungle Addict"),
        _t("Играйте в 30 разных дней.", "Play on 30 different days."),
        None,
    ),
    (
        "level_5",
        "progress",
        "⭐",
        "level",
        5,
        50,
        _t("Уровень 5", "Level 5"),
        _t("Достигните 5 уровня.", "Reach level 5."),
        None,
    ),
    (
        "level_10",
        "progress",
        "🌟",
        "level",
        10,
        100,
        _t("Уровень 10", "Level 10"),
        _t("Достигните 10 уровня.", "Reach level 10."),
        None,
    ),
    (
        "level_20",
        "progress",
        "💫",
        "level",
        20,
        200,
        _t("Уровень 20", "Level 20"),
        _t("Достигните 20 уровня.", "Reach level 20."),
        None,
    ),
    (
        "level_30",
        "progress",
        "✨",
        "level",
        30,
        300,
        _t("Уровень 30", "Level 30"),
        _t("Достигните 30 уровня.", "Reach level 30."),
        None,
    ),
    (
        "level_50",
        "progress",
        "🌠",
        "level",
        50,
        500,
        _t("Уровень 50", "Level 50"),
        _t("Достигните 50 уровня.", "Reach level 50."),
        None,
    ),
    (
        "xp_10000",
        "progress",
        "💎",
        "xp",
        10000,
        200,
        _t("10 000 XP", "10,000 XP"),
        _t("Наберите 10 000 XP.", "Earn 10,000 XP."),
        None,
    ),
    (
        "season_top100",
        "season",
        "🥥",
        "season_rank",
        100,
        50,
        _t("Топ-100 сезона", "Season Top 100"),
        _t("Закончите сезон в первой сотне.", "Finish a season in the top 100."),
        None,
    ),
    (
        "season_top10",
        "season",
        "🍌",
        "season_rank",
        10,
        150,
        _t("Топ-10 сезона", "Season Top 10"),
        _t("Закончите сезон в первой десятке.", "Finish a season in the top 10."),
        None,
    ),
    (
        "season_third",
        "season",
        "🥉",
        "season_rank",
        3,
        250,
        _t("Третье место", "Third Place"),
        _t("Займите третье место в сезоне.", "Finish a season third."),
        None,
    ),
    (
        "season_second",
        "season",
        "🥈",
        "season_rank",
        2,
        400,
        _t("Второе место", "Second Place"),
        _t("Займите второе место в сезоне.", "Finish a season second."),
        None,
    ),
    (
        "season_first",
        "season",
        "🥇",
        "season_rank",
        1,
        600,
        _t("Чемпион сезона", "Season Champion"),
        _t("Займите первое место в сезоне.", "Win a season."),
        None,
    ),
]

# code, difficulty, metric, target, xp, names
CHALLENGES = [
    ("rounds_3", "easy", "rounds", 3, 20, _t("Сыграйте 3 партии", "Finish 3 rounds")),
    ("rounds_5", "easy", "rounds", 5, 30, _t("Сыграйте 5 партий за день", "Finish 5 rounds today")),
    ("wins_2", "medium", "wins", 2, 40, _t("Выиграйте 2 партии", "Win 2 rounds")),
    (
        "high_win",
        "medium",
        "high_wins",
        1,
        40,
        _t("Победите дилера с 20 или 21 очком", "Beat the dealer with 20 or 21"),
    ),
    ("blackjack_1", "hard", "blackjacks", 1, 60, _t("Соберите блэкджек", "Get a blackjack")),
    (
        "win_run_3",
        "hard",
        "win_run",
        3,
        80,
        _t("Выиграйте 3 партии подряд", "Win 3 rounds in a row"),
    ),
]


def achievement_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.uuid4(),
            "code": c,
            "category": cat,
            "icon": icon,
            "metric": m,
            "threshold": th,
            "xp_reward": xp,
            "names": n,
            "descriptions": d,
            "title": title,
            "sort_order": i * 10,
        }
        for i, (c, cat, icon, m, th, xp, n, d, title) in enumerate(ACHIEVEMENTS)
    ]


def challenge_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.uuid4(),
            "code": c,
            "difficulty": d,
            "metric": m,
            "target": t,
            "xp_reward": xp,
            "names": n,
        }
        for c, d, m, t, xp, n in CHALLENGES
    ]


async def seed(conn: AsyncConnection) -> None:
    from app.models import Achievement, ChallengeTemplate

    await conn.execute(pg_insert(Achievement).values(achievement_rows()).on_conflict_do_nothing())
    await conn.execute(
        pg_insert(ChallengeTemplate).values(challenge_rows()).on_conflict_do_nothing()
    )
