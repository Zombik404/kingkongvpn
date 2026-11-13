# ADR-019 — Mini-games: Jungle Kong Blackjack

Status: accepted (2026-11-13). Reference: `documentation/GAMES_BLACKJACK.md`.

1. **Part of the platform, not a product of its own.** Same accounts and login, settings,
   RBAC/audit, Redis, Celery, Mini App design system. New code lives in `backend/app/games/`;
   existing VPN code is touched only at integration points (router registration, settings
   registry, permissions, one periodic task).
2. **Server-authoritative.** The engine is pure and client-independent; the shoe, the hole card
   and the next seed never leave the server. All writes are POSTs with rate limits and an
   `action_id` for idempotency; the WebSocket only pushes views, and clients can poll instead.
3. **Bonus wallet in hours, separate from subscriptions.** Paid and promo days cannot enter the
   game; game bonus days leave it only through a one-way exchange into VPN days. Ledger with a
   unique idempotency key per user; row locks; CHECK `balance_hours >= 0`.
4. **Stakes are off by default** and switched by a setting, because staking things of value on a
   game of chance can be gambling by law. Fun mode has no wins or losses of bonus days.
5. **Provably fair** commit–reveal shuffle (SHA-256 commitment, HMAC-SHA256 stream, CSPRNG seed).
6. **One table code path for solo and multiplayer** (a solo game is a one-seat private table);
   one table per player; timers enforced lazily on access and by a 5-second periodic task.
7. **Dealer character** is the app's own crowned gorilla ("the jungle king"), an original design
   — not the film character. The name "King Kong" has the trademark caveat from ADR-018 §5.
8. **Not built because they don't exist yet:** native mobile screens and a visual admin panel.
   The API is ready for both.
9. **Owner's decisions, 2026-11-13 (evening):**
   - **Solo only.** Shared tables are switched off by default (`games.multiplayer_enabled =
     false`) and their screens and the bot's table invitations are removed. The server keeps the
     shared-table code path (a solo game is a one-seat table anyway) and its tests, so turning
     it on later is a setting plus screens.
   - **Fun chips** (`games.chips.*`): a play currency with no value — not bought, not exchanged,
     not transferred, topped up to `games.chips.daily` (1000) once a day. Used for stakes while
     bonus-day stakes are off; when bonus-day stakes are on they take over. Stakes are multiples
     of 10 so 3:2, 6:5 and halves pay whole chips. `game_rounds.currency` records what a round
     was played for.
   - **Leaderboard = biggest single win in chips** ("the jackpot") with the stake of that round;
     ties go to whoever got there first.
   - **Code graph:** the repository is to be indexed by the Graphify connector (needs the code on
     GitHub; see `PROJECT_STATUS.md`).
