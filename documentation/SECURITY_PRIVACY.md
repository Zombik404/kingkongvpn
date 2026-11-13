# Security and user data

What personal data the service holds, how it is protected, what the review of 2026-11-13 found
and fixed, and what is left for the owner. Decisions: [ADR-020](adr/0020-admin-panel-and-data-protection.md).

## What we keep, and what we don't

| Data | Where | Why | How long |
|---|---|---|---|
| Telegram ID (number only) | `users.telegram_id` | Sign-in through the Mini App | Until the account is deleted (cleared at once) |
| Email + Argon2id password hash | `users` | Staff accounts (admin panel), future web/app sign-in | Until deleted (cleared at once) |
| TOTP seed | `users.totp_secret_encrypted` (AES-GCM, per-user context) | Staff 2FA | Until deleted |
| Device name, platform, **public** WireGuard key, tunnel addresses | `devices` | Putting the device on a node | Addresses freed 30 days after the device is removed |
| Last handshake, 1-hour resolution | `devices.last_handshake_at` | "Last connected", idle cleanup | Overwritten |
| Bytes up/down per device per UTC day | `device_usage_daily` | Traffic chart | 90 days |
| Subscriptions, payments (amount, asset, status) | `subscriptions`, `payments` | Access and accounting | Payments kept (law), unlinked from the user at purge |
| Sessions: created/last used, user agent, IP shortened to /24 or /48 | `auth_sessions` | "Where am I signed in", theft detection | Cleaned 7 days after expiry |
| Audit log: action, actor, target, shortened IP, details with secrets stripped | `audit_logs` | Accountability for staff and money actions | Kept |
| Game nickname, stats, chips, bonus ledger | `game_*`, `bonus_*` | Blackjack | Nickname replaced at deletion; rows purged with the account |

**Never stored:** sites visited, DNS queries, traffic contents, connection logs, Telegram name,
username or photo (read from `initData` only to validate it), private WireGuard keys (generated
on the device, ADR-003), card or wallet details (only @CryptoBot sees them).

## Protections in place

- **Accounts:** server-side `initData` signature and age check; staff can't sign in through
  Telegram; staff routes need a role **and** a session that passed TOTP; roles re-read from the
  database on every request; refresh tokens rotate, a reused one revokes the session.
- **Abuse limits (Redis, hashed keys):** login, registration, email, MFA, promo codes, game
  actions, payments checkout, **device registration (10/day)**, **connect (30/10 min)**,
  **data export (5/hour)**, account deletion attempts.
- **Money and balances:** row locks, unique idempotency keys, CHECK constraints, audit rows in
  the same transaction; paid days can never be staked.
- **Web:** API responses carry `Content-Security-Policy: default-src 'none'`, `no-store`,
  `X-Frame-Options: DENY`, `Permissions-Policy`; the Mini App and admin panel have strict CSPs
  (`script-src 'self'`, no inline code, no third-party assets in the admin panel); API data is
  put into pages as text only.
- **Edge (Caddy):** node API, metrics, health and API docs are not served publicly; the admin
  panel and `/api/v1/admin/*` can be limited to the owner's networks (`ADMIN_ALLOWED_IPS`).
- **Server:** secrets only in `.env.prod` (mode 600) and `deploy/secrets`; own nftables table;
  Postgres and Redis not published; backups 0600 and **encrypted with `age`** when a recipient
  key is set.
- **CI:** secret scan, dependency audit (`pip-audit`), strict typing, tests on every push.

## Review of 2026-11-13: found and fixed

| # | Finding | Risk | Fix |
|---|---|---|---|
| 1 | Caddy ran `handle /api/*` before `respond @private`, so **API docs and the full OpenAPI schema were public** on the server (staging enables docs) | Medium: maps every route for an attacker | Rules wrapped in one `route` (run in written order); backend serves docs only in development/testing; tested with a real Caddy and a unit test |
| 2 | **Telegram accounts couldn't be deleted**: deletion required a password they don't have | High (privacy law: right to erasure) | Deletion confirmed with fresh signed `initData` of the same Telegram user; Mini App "Your data" card with export and delete |
| 3 | Data export missed traffic, referrals, game data, notification settings | Medium (right of access) | Export covers everything we keep |
| 4 | Game nickname of a deleted account stayed on the public leaderboard for 30 days | Medium (could be a real name) | Nickname replaced at deletion; deleted/suspended players hidden from the board |
| 5 | Register/remove device in a loop could **drain the tunnel address pool** for everyone | Medium (denial of service) | 10 registrations per account per day; addresses of devices removed 30+ days ago return to the pool |
| 6 | No limits on connect (node churn) and export (heavy query) | Low | Per-account limits |
| 7 | Daily database backups unencrypted | Medium if copied off the server | `age` encryption to an off-server key (`/etc/globalvpn/backup-recipients`) |
| 8 | No staff UI: staff actions needed raw API calls | Operational risk (mistakes) | Admin panel with reasons on every change, audit view, 2FA forced |

Accepted for now: uvicorn trusts `X-Forwarded-For` from any peer, but it is only reachable
from Caddy (which replaces that header) and from the host itself. The Mini App passes the
device config to an external browser in a URL fragment (never sent to a server), so it can stay
in that browser's history.

## For the owner

1. **Backups:** on your own computer run `age-keygen -o kingkong-backup.key` (keep this file
   safe and off the server), then on the server put the printed `age1…` line into
   `/etc/globalvpn/backup-recipients`.
2. **Admin from your networks only (optional):** set `ADMIN_ALLOWED_IPS="your.ip/32"` in
   `deploy/.env.prod` and re-run `install.sh`.
3. **Privacy policy text** for the bot/Mini App: needs a lawyer for your countries; the table
   above is the factual basis.
4. Payment record retention period: confirm with an accountant.
