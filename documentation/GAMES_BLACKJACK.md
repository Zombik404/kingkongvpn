# Jungle Kong Blackjack — integration plan and reference

A blackjack mini-game inside the existing VPN platform (not a separate product): the same
accounts, backend, Telegram bot, Mini App, admin API, settings, audit log and look.
Decisions: [ADR-019](adr/0019-mini-games-blackjack.md).

## What exists in the project and how the game uses it

| Existing piece | Used for |
|---|---|
| Accounts + Telegram WebApp login (server-side `initData` check) | One account = one game profile, one bonus wallet. No separate sign-up |
| Subscriptions (`grant_days`) | The only way bonus days become VPN time: a one-way exchange |
| Settings service + `/admin/settings` | Every game switch and rule (`games.*`) |
| RBAC + MFA + audit log | Staff API `/admin/games/*`, permissions `games:read` / `games:write` |
| Redis | Rate limits and the real-time channel of each table |
| Celery beat | Turn/bet timers, closing idle tables |
| Mini App design tokens, cards, buttons, themes | All game screens |
| Notifications (Telegram/email) | Game notices |

Not in the repository yet: a native mobile app and a visual admin panel. The game API is
platform-neutral, so both will use the same endpoints when they are built.

## Architecture

```
Mini App ──HTTPS──▶ /api/v1/games/*        (every change: authenticated, rate-limited, idempotent)
    ▲   ◀─WebSocket─ /api/v1/games/ws      (server → client only: "here is the new table")
    │
backend/app/games/
  blackjack.py   engine: pure functions over a JSON round state, no I/O, no randomness
  fair.py        provably fair shuffle (commit → shuffle → reveal)
  wallet.py      bonus wallet + ledger (hours), one-way exchange into VPN days
  service.py     tables for 1–4 players, betting, turns, timers, settlement, statistics
```

The server is the only source of truth for the shoe, cards, turn order, stakes, balances and
results. Clients receive `room_view()`: no shoe, no next seed, the dealer's hole card hidden
until the round is settled. Every change to a table runs under a row lock on `game_rooms`, so
simultaneous requests are applied one after another.

**Table phases:** `waiting → betting → [insurance] → playing → settled → betting → …`

> **Solo only for now** (owner's decision): `games.multiplayer_enabled` is off by default and the
> Mini App shows only the table against the dealer. The server still supports 1–4 seats.

- *betting*: each player confirms taking part (and the stake, when stakes are on). When everyone
  has confirmed — or the bet timer runs out — cards are dealt to those who confirmed.
- *playing*: turns go by seat. At a shared table a move has `turn_seconds`; when it runs out the
  server stands for the player. A solo round left unattended ends the same way after 10 minutes.
- A player who sits out or times out 3 rounds in a row leaves the table. Leaving mid-round
  stands their hands — the stake stays in play and settles normally. Leaving before the deal
  refunds the stake.
- One table per player at a time; reconnecting returns the same seat.

## Rules (all configurable in `/admin/settings`)

52-card decks without jokers; 2–10 at face value, J/Q/K = 10, ace = 1 or 11. Blackjack, bust,
push, Double Down, Split (same rank; split aces get one card each; up to `max_hands`), late
Surrender (half back), Insurance (pays 2:1), dealer peek on an ace or ten.

| Setting (`games.blackjack.*`) | Default |
|---|---|
| `decks` | 6 |
| `dealer_hits_soft_17` | false (dealer stands on all 17s) |
| `blackjack_pays` | `3:2` (or `6:5`) |
| `allow_double`, `allow_double_after_split`, `allow_split`, `allow_surrender`, `allow_insurance` | true |
| `max_hands` | 4 |
| `turn_seconds` / `bet_seconds` | 30 / 20 |

## Bonus days

Three kinds of VPN time are kept apart:

1. **Paid subscription period** — never in the game. There is no code path from a subscription
   into the wallet, so paid days cannot be staked or lost (tested).
2. **Promo days** from the administration, invites and referrals — go straight into the
   subscription, also never in the game.
3. **Game bonus days** — the bonus wallet (`bonus_wallets`, in hours so that 3:2 payouts and
   halves are exact). Only these can be staked.

Wallet rules: row lock for every change; the balance can't go below zero (code + CHECK
constraint); every change writes `bonus_ledger`; `(user, idem_key)` is unique, so a repeated
request, retry or settlement can't move the balance twice. The stake is taken when the bet is
confirmed; Double/Split/Insurance take their extra stake at that moment (not offered if the
player can't afford them); the payout is credited once per round.

A player can **exchange whole bonus days for VPN days** (`POST /games/wallet/redeem`, switch
`games.bonus_redeem_enabled`). It is one-way. There is no purchase of game credit, no cash-out,
no transfer between users.

> **Stakes are OFF by default** (`games.blackjack.stakes_enabled = false`). Staking something
> of value on a game of chance is regulated as gambling in many countries, even without money.
> Until the owner has checked the legal requirements for the target countries, the game runs for
> fun: nothing is won or lost, and statistics and the leaderboard still work. Related settings:
> `stake_options_days` (default 1/2/3/5), `daily_win_cap_days` (10), `welcome_bonus_days` (0).

## Fun chips and the jackpot board

While bonus-day stakes are off, players stake **fun chips** (`games.chips.enabled`, on by
default): a play currency kept on the game profile. Chips have no value — they can't be bought,
exchanged for VPN days, cashed out or transferred — and the balance is topped up to
`games.chips.daily` (1000) once per UTC day (never reduced). Stakes come from
`games.chips.stake_options` (10/20/50/100/200/500; multiples of 10 so every payout is whole
chips). "Play without a stake" (0 chips) is always possible.

The **leaderboard** (`GET /games/leaderboard`) lists players by their **biggest single-round win
in chips** with the total stake of that round (including doubles/splits); ties go to whoever got
there first. When bonus-day stakes are switched on, rounds use bonus days instead and do not
touch chips or the board.

## Progression: XP, levels, achievements, challenges, boards, seasons (ADR-021)

Everything below is computed on the server from settled rounds only; rounds the server had to
finish (timeout, leaving, a table closed by staff) give no progress. All numbers are settings
(`games.xp.*`, `games.levels.*`, `games.streak.rewards`, `games.seasons.*`,
`games.leaderboard.min_rounds_winrate`, `games.timezone`) editable in the admin panel.

| Piece | How it works (defaults) |
|---|---|
| XP | +5 per finished round, +10 for a win, +10 for a blackjack; at most 600 XP a day from rounds. Challenges, achievements and prizes add their own XP. XP is never lost, traded or cashed out |
| Levels | Level 1→2 costs 100 XP, each next level 50 more; no upper limit. Titles: 1 Jungle Rookie, 2 Jungle Explorer, 3 Wild Player, 4 Jungle Hunter, 5 Gorilla Fighter, 10 Jungle Master, 20 King of Jungle |
| Achievements | 23 in four categories (game, activity, progress, season), each with icon, progress bar, XP and sometimes a title; given once |
| Daily challenges | One easy, one medium, one hard per game day (new at 00:00 in `games.timezone`), progress bar, XP on completion, history |
| Day streak | A day counts when you finish a round in it. Rewards at 3 / 7 / 14 / 30 days (XP, titles; bonus days only when allowed). Calendar of the last 5 weeks |
| Boards | XP, wins, win rate (wins ÷ (wins + losses), from 20 decided rounds) for the week, month and all time, plus the jackpot board; top 3 highlighted, your place pinned, search, pages, number of players |
| Seasons | Weekly and monthly, plus event seasons from staff. Countdown, prizes by place (1st: King of Jungle + gold frame, 2nd: Jungle Champion + silver, 3rd: Jungle Warrior + bronze, top 10 and top 100 XP), at least 10 rounds for a prize, archive with winners |
| Profile | Nickname, avatar (jungle emoji), chosen title, level and XP bar, statistics, places, latest achievements and rounds, XP and reward history |
| VPN bonus days | **Off** (`games.rewards.bonus_days_enabled`) until the legal check: prizes are XP, titles and frames; paid days are never touched |

Staff (`/admin/games/*`, admin panel "Прогресс и сезоны"): players and their progress,
exclude a cheater from every board and prize with a reason, edit achievements and challenges,
create / edit / finish seasons and see results, change the XP and reward settings.

## Notices (Telegram / email)

`game_round_away` (a round finished while you weren't looking at the table),
`game_kicked` (left the table after missing several turns), `game_redeem` (bonus days exchanged
for VPN days), `game_bonus_admin` (staff changed your bonus balance). Sent after the change is
committed. The bot's `/games` opens the games section.

## Provably fair

1. Before each round the table shows `next_seed_hash = SHA-256(server_seed)`.
2. Each player may send a `client_seed` with the bet; the table's seed is all of them in seat
   order (`0=alice|1=bob`). The nonce is the round number at the table.
3. Shoe = Fisher–Yates shuffle of the canonical shoe (`decks ×` suits S,H,D,C `×` ranks
   A,2…9,T,J,Q,K) driven by `HMAC-SHA256(server_seed, "client_seed:nonce:counter")`, read as
   32-bit big-endian integers with rejection sampling. Deal order: one card to each seat, dealer
   up card, a second card to each seat, dealer hole card, then draws.
4. After the round `server_seed` is revealed (`last_fair` in the table view,
   `GET /games/rounds/{id}/fairness`, which also returns that round's cards). The Mini App's
   "Verify this round" re-runs the shuffle on the device (`miniapp/src/fair.js`, tested against
   the server's) and checks that exactly that round's cards came off the top of the shoe. Check that its SHA-256 equals the hash shown before the
   bet and re-run the shuffle (`app/games/fair.py`, 30 lines) to see the same cards.

Randomness comes from the OS CSPRNG (`secrets`).

## API (all under `/api/v1`, bearer token)

| Endpoint | Purpose |
|---|---|
| `GET /games` | Switches, profile and statistics, bonus balance, current table, rules |
| `PUT /games/profile` | Display name (sanitised) |
| `GET /games/wallet`, `POST /games/wallet/redeem` | Balance + history; exchange for VPN days |
| `POST /games/rooms/solo` | The player's own table against the dealer |
| `POST /games/rooms`, `GET /games/rooms`, `POST /games/rooms/join` | Create (1–4 seats, public/private), list public, join by id or code |
| `GET /games/rooms/{id}` | The table as this player may see it (also the polling fallback) |
| `POST /games/rooms/{id}/bet`, `/actions`, `/leave` | Confirm the round (`stake` in the table's currency: chips or bonus days), play, leave |
| `GET /games/history`, `/leaderboard`, `/rounds/{id}/fairness` | History (with each round's currency), jackpot board, seeds and cards |
| `WS /games/ws` | First message `{"token", "room"}`; then the server pushes `{"type":"room","room":…}` |

Staff (`/api/v1/admin/games/*`, MFA session): `overview`, `rooms` (+ `pause` / `resume` /
`close`), `rounds`, `ledger`, `players`, `suspicious`, `events`, `players/{id}/bonus`. Every
change is written to the audit log.

## Status

See `PROJECT_STATUS.md`. Done and tested: engine, fairness (server and on-device check), bonus
wallet, fun chips, jackpot board, solo table screens, dealer reactions, sounds, notices, bot
`/games`, admin API, clickable demo.
