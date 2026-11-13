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

## Provably fair

1. Before each round the table shows `next_seed_hash = SHA-256(server_seed)`.
2. Each player may send a `client_seed` with the bet; the table's seed is all of them in seat
   order (`0=alice|1=bob`). The nonce is the round number at the table.
3. Shoe = Fisher–Yates shuffle of the canonical shoe (`decks ×` suits S,H,D,C `×` ranks
   A,2…9,T,J,Q,K) driven by `HMAC-SHA256(server_seed, "client_seed:nonce:counter")`, read as
   32-bit big-endian integers with rejection sampling. Deal order: one card to each seat, dealer
   up card, a second card to each seat, dealer hole card, then draws.
4. After the round `server_seed` is revealed (`last_fair` in the table view,
   `GET /games/rounds/{id}/fairness`). Check that its SHA-256 equals the hash shown before the
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
| `POST /games/rooms/{id}/bet`, `/actions`, `/leave` | Confirm the round, play, leave |
| `GET /games/history`, `/leaderboard`, `/rounds/{id}/fairness` | History, rating, seeds |
| `WS /games/ws` | First message `{"token", "room"}`; then the server pushes `{"type":"room","room":…}` |

Staff (`/api/v1/admin/games/*`, MFA session): `overview`, `rooms` (+ `pause` / `resume` /
`close`), `rounds`, `ledger`, `players`, `suspicious`, `events`, `players/{id}/bonus`. Every
change is written to the audit log.

## Status

See `PROJECT_STATUS.md`. Server side: done and tested (engine, fairness, wallet, tables,
multiplayer, timers, admin API). Screens, bot integration and the clickable demo: next stage.
