# ADR-021: Blackjack progression — XP, levels, achievements, daily challenges, boards, seasons

Status: accepted · 2026-11-13 · owner's brief "Progression, achievements & leaderboards"

## Context

The game is solo only (player against King Kong). The owner wants players to compete through
a shared profile, XP and levels, achievements, daily challenges and a day streak, three
leaderboards, weekly / monthly seasons with prizes, and staff tools, without multiplayer and
without touching paid VPN time. The brief asks not to duplicate existing tables or services.

## Decisions

1. **Extend, don't duplicate.** The existing `game_profiles` row gains XP, level, avatar,
   title, frame, day streak and exclusion; rounds stay in `game_rounds` /
   `game_round_players`; VPN bonus days keep using the existing bonus wallet and ledger. New
   tables only for what didn't exist: `game_xp_events`, `game_achievements` +
   `game_user_achievements`, `game_challenge_templates` + `game_daily_challenges`,
   `game_play_days`, `game_user_titles`, `game_seasons` + `game_season_stats` +
   `game_season_results`, `game_rewards` (migration `0010`).
2. **Server-settled rounds are the only source.** `record_round()` runs inside the round's
   settlement transaction. The client never sends wins, XP, progress or ranks. Rounds the
   server had to finish (turn timeout, leaving the table, staff closing it) settle and pay but
   give no XP, challenge, streak or season progress.
3. **Idempotent everything.** Each XP grant, reward, achievement, title and daily challenge
   has a unique key (`round:<id>`, `ach:<code>`, `challenge:<id>`, `reward:<season>:<board>`,
   `streak:<days>:<start>`), inserted with `ON CONFLICT DO NOTHING`; XP is positive only and
   never lost. A season is finalised once (`finalized_at` under a row lock).
4. **Levels** follow `base + step·(n-1)` XP per level (100 / 50 by default, any number of
   levels); titles per level from settings. XP from rounds has a daily cap (600) to blunt
   farming; challenges, achievements and prizes are outside the cap.
5. **Achievements and challenges are data** with a metric from a fixed list the server counts
   (wins, rounds, blackjacks, best win streak, wins with exactly 21, day streak, days played,
   level, XP, season place; per day: rounds, wins, blackjacks, wins with 20–21, wins in a row).
   Staff can add and edit them without code. Each day a player gets one easy, one medium and
   one hard challenge, picked stably from the enabled templates.
6. **Day streak** counts a day only when a round is finished in it (opening the app doesn't).
   Rewards at 3 / 7 / 14 / 30 days, once per streak. No reminders that push people to play.
7. **Boards**: XP, wins, win rate (= wins / (wins + losses), pushes ignored, at least 20
   decided rounds in the period) — for the week, month and all time — plus the earlier
   jackpot board. Ties go to whoever got there first. Your own place is returned even far
   below the first page. Excluded, suspended and deleted players never appear.
8. **Seasons**: weekly (from Monday 00:00) and monthly in the game time zone (`games.timezone`),
   opened on demand and closed by the `games.seasons` task every minute; staff can add event
   seasons. Closing freezes the top 100 of each board, pays prizes by place (XP, title, frame,
   and bonus days only if allowed), season achievements and participation XP, and sends the
   top 10 a Telegram notice.
9. **VPN bonus days from the game are OFF** (`games.rewards.bonus_days_enabled = false`) until
   the legal check. Prizes are then recorded with `bonus_paid = false` and nothing reaches the
   wallet; paid subscription days are never touched by any game code.
10. **Staff**: exclusion from boards and prizes with a reason (audited), catalogue editing,
    season management, all behind `games:read` / `games:write` on an MFA session.
11. **Avatars** are a fixed set of jungle emoji, not Telegram photos: we don't store users'
    photos or names (SECURITY_PRIVACY.md).

## Consequences

- Board queries read profile counters and season stats directly, with indexes on
  `(xp, score_at)`, `(wins, score_at)` and season stats; fine for tens of thousands of players,
  a materialised ranking can come later if needed.
- A partial unique index guards the automatic seasons. Its `ON CONFLICT` predicate must be a
  literal: with bound parameters Postgres rejects the statement once it switches to a generic
  plan (found in the browser test, covered by a regression test).
