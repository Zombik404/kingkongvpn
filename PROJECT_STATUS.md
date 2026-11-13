# Project Status

Last updated: 2026-11-13 · Current phase: **Telegram test version built and verified, code on GitHub with green CI → next: deploy to a VPS (`documentation/TEST_LAUNCH_RU.md`)**

## Phases

| Phase | State | Notes |
|---|---|---|
| 1 — Initialization | ✅ Complete | Repo, architecture, ADR summary, roadmap, env template, dev Compose, scripts |
| 2 — Database & backend | ✅ Complete | FastAPI + SQLAlchemy 2 + Alembic + Celery; auth, users, devices, plans, subscriptions, promo, RBAC, audit, email; 165 tests, 97 % coverage |
| 3 — VPN infrastructure | 🟡 Test slice done | Agent network client + systemd unit, firewall, one-command install; real tunnels verified with wireguard-go in netns. Open: mTLS enrollment, unbound, Ansible/Terraform, real VPS run |
| 4 — VPN management engine | 🟡 Test slice done | Locations, `POST /vpn/connect` (least-loaded healthy node, one active peer per device), long-poll desired state, **staff API for locations and servers** (register, drain, disable, rotate token, health), **idle-peer release** (off by default). Open: node-down alerts, auto-scaling |
| 5 — Telegram bot | 🟡 Test slice done | aiogram bot + Mini App (keys on device, QR/file), invites, Telegram notifications. Open: admin commands, Stars |
| 6 — Mobile apps | ⏳ Pending | Needs Flutter SDK, Android device/emulator, Mac + Xcode, Apple org account |
| 7 — Desktop apps | ⏳ Pending | Needs Windows machine, Mac, code-signing |
| 8 — Web app | ⏳ Pending | API contract ready (`shared/api-contracts/openapi.json`) |
| 9 — Admin panel | 🟡 First version done | `admin-panel/` at `/admin/`: sign-in with forced TOTP, overview, users (case file + actions), payments, plans/prices, promo, servers, blackjack, settings, audit; RBAC-aware; clickable demo. Open: English UI, WebAuthn, support tickets |
| 10 — Payments | 🟡 Started | Crypto (Gram + USDC) via @CryptoBot done (ADR-016, testnet). Telegram Stars / Stripe / stores later |
| 11 — Security & optimization | 🟡 Started | Data-protection review 2026-11-13 (`documentation/SECURITY_PRIVACY.md`): 8 findings fixed (public API docs via Caddy order, deletion/export for Telegram users, nickname leak, address-pool drain, missing limits, unencrypted backups). Open: external pentest, load tests |
| 12 — Production launch | ⏳ Pending | |

## Completed in Phase 2
- **Settings** (`app/core/config.py`): every value from env; outside dev/test the app refuses to start with placeholder or missing secrets (DB password, pepper, JWT keys, encryption key, MFA off, test hashing).
- **Schema**: 23 tables from Architecture §4 (SQLAlchemy 2 async models, UUIDv7 keys), one reviewed Alembic migration, reversible. Details: `documentation/DATABASE_SCHEMA.md`.
- **Auth** (ADR-007): register (enumeration-safe) → email verification → login; Argon2id; EdDSA JWT access tokens re-checked against DB each request; opaque refresh tokens stored as HMAC, rotated on every use, reuse revokes the session; logout / logout-all / per-session revoke; password reset and change; TOTP 2FA with encrypted seeds and replay protection; Redis sliding-window rate limits.
- **Users**: profile/locale, full data export, account deletion (immediate anonymisation, purge after 30 days).
- **Devices**: public-key-only registration with strict key validation, plan-based device limit (race-safe), concurrency-safe tunnel IPv4+IPv6 allocator, rename, revoke (marks node peers for removal).
- **Plans/prices/settings**: public plan list with live prices and i18n names; admin CRUD; typed global settings.
- **Subscriptions**: pure state machine (trialing/active/past_due/grace/canceled/expired/refunded); trial, cancel/resume, grant/revoke; expiry & reminder jobs (idempotent, `SKIP LOCKED`).
- **Promo codes**: free-days redemption (row-locked `max_redemptions`), discount validation.
- **RBAC + audit**: support/ops/finance/superadmin permission map; staff routes need an MFA-verified session; every mutation audit-logged with secret scrubbing and truncated IPs.
- **Workers**: Celery app + beat schedule (expiry 5 min, reminders hourly, purge and token cleanup daily); SMTP email task with back-off.
- **Email**: 6 transactional templates × 5 languages (en, de, hu, uk, ru), HTML + text.
- **Contract & docs**: `shared/api-contracts/openapi.json` (49 operations), `documentation/BACKEND_API.md`, `documentation/DATABASE_SCHEMA.md`, `documentation/adr/0015-backend-core-decisions.md`.
- **Tooling**: hash-pinned `requirements.lock` / `requirements-dev.lock`; Dockerfile installs from them; Compose `migrate` service runs before API/worker; CI workflow (`.github/workflows/ci.yml`); `app.cli grant-role` / `seed-dev`; new Makefile targets.

## Jungle Kong Blackjack (2026-11-13) — ADR-019, documentation/GAMES_BLACKJACK.md
Stage plan from the owner's brief; ✅ = done and tested, ⏳ = next.
- ✅ 1-3 Project analysis and integration plan.
- ✅ 4 Blackjack engine (`app/games/blackjack.py`): blackjack, bust, push, double, split, surrender, insurance, dealer rules; 17 unit tests.
- ✅ 5 Tables and multiplayer (`app/games/service.py`): 1-4 seats, public/private, codes, turn order, bet/turn timers, reconnect, leaving, idle cleanup; real-time push over WebSocket with polling fallback.
- ✅ 6 Bonus wallet + ledger (`app/games/wallet.py`): hours, row locks, no negative balance, idempotent, one-way exchange into VPN days. Paid days can never be staked (tested).
- ✅ 7 Uses the existing accounts (one profile, one wallet per user), settings, RBAC, audit.
- ✅ 10 Staff API `/admin/games/*` (overview, rooms pause/resume/close, rounds, ledger, players, suspicious, events, bonus adjust) with permissions `games:read`/`games:write`.
- ✅ Provably fair shuffle (commit-reveal), CSPRNG.
- ⚠️ **Stakes are OFF by default** (`games.blackjack.stakes_enabled`): legal check for target countries is the owner's decision. Fun mode works fully.
- ✅ 8-9 Mini App "Games" section: solo table against the crowned dealer (reactions: eats bananas between rounds, cheers/sulks at results), card dealing and flip animations, synthesised sounds with a mute button, stats, history, jackpot board, on-device provably-fair check; bot `/games`; notices (round finished while away, removed for inactivity, bonus exchange, staff adjustment).
- ✅ Owner's decisions (evening): **solo only** (shared tables off, screens and invites removed; server path kept), **fun chips** (no value, 1000 a day) for stakes in fun mode, **leaderboard = biggest single win + its stake**. Migration 0009.
- ✅ 11 Browser end-to-end on the real backend (two players: chip stakes, wins/losses/push, fairness check, board) and in the clickable demo; fixed: fairness check compared the wrong round, a stale result banner after a quick new round.
- ✅ Code on GitHub (`Zombik404/kingkongvpn`, private); CI green there. Graphify connector: repository added, indexing in progress; meanwhile the local graph (`make graph`) is used.
- Not in the repo (so not built): native mobile app screens, visual admin panel — the API is ready for both.
- Verified: 279 backend tests (Python 3.13), bot 7, Mini App 7; migrations 0008-0009 applied to a database with data.

## KingKong VPN rebrand (2026-11-13) — ADR-018 §5–6
- Renamed to **KingKong VPN**: jungle look (black & green, leaves and vines), the owner's gorilla patch as the logo; ranks renamed Monkey/Parrot/Jaguar/Gorilla/King Kong, themes Volcano/Night/Banana/Orchid.
- Jungle dressing, rendered realistically (`miniapp/tools/render_*.py`, no stock photos): misty rainforest backdrop, swaying lianas, fireflies, leaf wreath; **page transitions with the crowned jungle-king gorilla swinging on a liana, banana in hand** (forward → right, back → left; off with reduced motion).
- **"Hidden in the jungle"** effect while the VPN is on: leaves overgrow the screen edges (springy growth, creeping lianas, popping and falling leaves, status chip), shrinking back when it's off. Detected via new `GET /vpn/status` (request comes through our tunnel / a node's IP). 221 backend tests.
- **Clickable demo** of the Mini App on sample data in `miniapp/demo/` (published as a private page for the owner).
- Bot avatar: `branding/bot-avatar-640.png` → @BotFather `/setuserpic`.
- ⚠️ "King Kong" is a famous trademarked name — clear it before a public launch.

## Mini App redesign (2026-11-13) — ADR-018
- Mini App rebuilt in black & orange: radial menu (country, payment, upgrade, friends, devices, help) around a ring showing days left; traffic dashboard (7/30/90 days, download/upload, smooth area chart, top-5 devices as concentric rings).
- **Traffic accounting** from per-peer WireGuard counters (agent 0.3.0) → `device_usage_daily`, `GET /vpn/usage`.
- **Referrals (v2):** `GET /referrals`, `POST /referrals/claim`, bot `ref_` deep links; the **invited user gets 30 % off their first payment**, the **referrer gets +14 free days** per invited user who pays (`referrals.percent_off`, `referrals.bonus_days`; migrations 0005–0006); referral count shown in the Mini App; Telegram/email notice to the referrer.
- **Referral ranks:** 3/5/10/25 paying friends → 🦊/🕶/👑/🚀 with +7/+30/+90/+365 days and Mini App themes Lava/Matrix/Gold/Cosmos (migration 0007, `referrals.milestones`); confetti on a new rank; theme picker on the Friends screen.
- **Country switch** for devices created on the same phone (key kept in the device's local storage only).
- Not possible in the Telegram Mini App: per-app traffic (see ADR-018 §2) — shown as top devices; planned for the Android app.
- Verified: 221 backend tests (Python 3.12/3.13), Mini App flows in Chromium (invite → device → config → move to another country → remove; QR = file), screenshots reviewed.

## Telegram test version (2026-11-13) — ADR-017
- **Mini App** (`miniapp/`, built bundle in `miniapp/dist/`): sign-in with Telegram `initData`, invite code (auto-filled from `t.me/<bot>?start=INV-…`), plans and @CryptoBot payment with auto-confirmation, devices (add/remove), WireGuard keypair generated on the device, config as QR / file / browser page / copy.
- **Backend**: `POST /auth/telegram/webapp`, invite-only gate, `GET /vpn/locations`, `POST /vpn/connect`, node API `/internal/v1/nodes/{id}/desired-state` (long-poll) + `/heartbeat`, Telegram notifications, CLIs `node-register`, `create-invites`, `set-setting`; migration `0003`.
- **Node agent**: control-plane client, heartbeat thread, systemd unit with only `CAP_NET_ADMIN`.
- **Bot** (`telegram-bot/`): /start (with invite deep links), /help, menu button → Mini App.
- **Deploy** (`deploy/`): `install.sh` (one command on Ubuntu 24.04), `docker-compose.prod.yml`, Caddy with automatic HTTPS and strict CSP, own nftables table, daily DB backup. Guide: `documentation/TEST_LAUNCH_RU.md`.

### Verified here
| Check | Result |
|---|---|
| Backend suite (incl. Telegram auth, invites, connect, long-poll, notifications) | ✅ 200 passed (Python 3.12 and 3.13), 96 % coverage |
| Mini App in Chromium against the live API (mocked Telegram object, signed initData): invite → access → device → config → remove | ✅ no JS errors; QR decodes to exactly the downloaded config; private key never reached the server (DB, logs, audit) |
| Mini App crypto: X25519 public key equals libsodium/WireGuard reference | ✅ |
| **Real tunnels** (wireguard-go, 5 network namespaces, real agent + API + firewall from install.sh): handshake, internet via tunnel, NAT, LAN/metadata blocked, client-to-client blocked, SMTP rejected, revocation | ✅ 12/12; revoked device removed from the node in **0.44 s** (target ≤ 5 s); negative control: without the firewall the LAN *is* reachable |
| nftables rules loaded twice into a real kernel netns (idempotent) | ✅ |
| `install.sh` / helper scripts: `bash -n`, shellcheck; prod compose `config` | ✅ |
| Bot handlers (5), node agent (31 incl. loop/heartbeat), Mini App (4) | ✅ |

### Not verified yet (needs the VPS)
- `install.sh` end to end on a fresh Ubuntu 24.04 (Docker build, Let's Encrypt, systemd units, DOCKER-USER rules).
- IPv6 inside the tunnel (this build environment's kernel has no IPv6).
- Inside real Telegram clients (iOS/Android/Desktop webviews): file download behaviour differs — QR and "open in browser" are the fallbacks.
- @CryptoBot testnet with the real token.

## Added after Phase 2: crypto payments (@CryptoBot)
- Prices in USD — **1 mo $5, 3 mo $13, 6 mo $24, 12 mo $42** (confirmed by the owner 2026-11-13); paid in **Gram or USDC**; GRAM is matched to the API's `TON` code automatically if @CryptoBot hasn't renamed it yet — ADR-016.
- `POST /payments/checkout`, `GET /payments`, `GET /payments/{id}?refresh=true`, `POST /webhooks/cryptobot`.
- Signed-webhook verification, amount/currency/payload matching, idempotent and race-safe crediting, 60 s polling fallback (works without a domain), discount codes at checkout, "payment received" email in 5 languages.
- Migration `0002_cryptobot_payments`; CLI `bootstrap-catalog` (plans + launch prices, idempotent), `set-price`, `cryptobot-check`.
- 19 tests against a fake Crypto Pay API (incl. forged/stale webhooks, tampered amounts, webhook+poll race).
- **Not yet run against the real testnet API** (no network access from the build environment; the token stays on the server) — first check on the server: `python -m app.cli cryptobot-check`.

## Tests
| Suite | Result | Command |
|---|---|---|
| Backend: 308 tests on real PostgreSQL 16 + Redis 7 | ✅ pass (Python 3.12 and 3.13) | `make up && make test-backend` |
| Backend coverage | ✅ 97 % total — auth 96 %, subscriptions 96 %, devices 95 %, payments 94 % (target ≥ 85 %) | same |
| Migration up → down → up on a fresh DB; models ↔ migration drift; OpenAPI drift | ✅ pass | part of backend suite |
| Concurrency: 8 parallel device registrations vs limit 3; parallel address allocation; parallel promo redemption vs `max_redemptions` | ✅ pass | part of backend suite |
| `ruff check` + `ruff format --check`; `mypy --strict` on `backend/app` (53 files) | ✅ clean | `make lint` |
| `pip-audit` on the lock file | ✅ no known vulnerabilities | CI |
| End-to-end smoke (staging-mode settings, real uvicorn + Celery worker + SMTP sink): register → localized email delivered by worker → verify → login → device registered with tunnel addresses; beat starts | ✅ pass (run manually 2026-11-12) | see `documentation/BACKEND_API.md` flows |
| node-agent reconciler & parser (21) + secret generator (2) | ✅ pass | `make test` |
| Docker image build | ⛔ not run | Docker daemon unavailable in the build environment — run `make up-app` locally |
| CI workflow on GitHub (backend, node agent, bot, Mini App + dist drift, secret scan) | ✅ green on `main` | GitHub Actions |
| Real WireGuard handshake | ⛔ not run | needs staging VPS |

Failed tests: none.

## Known issues / limitations
- Refresh rotation is strict: two simultaneous refreshes with one token sign the session out (ADR-015 #2). Apps must serialise refresh.
- Web cookie-based refresh (HttpOnly + CSRF) is deferred to Phase 8 (ADR-015 #12).
- Staff MFA is TOTP only; WebAuthn comes with the admin panel (Phase 9).
- Discount promo codes are validated but only applied once checkout exists (Phase 10).
- Peer removal on expiry/revocation is recorded (`peer_assignments.state = removing`, server `revision` bump); pushing it to nodes is Phase 3/4.
- `support_tickets`, `notifications`, `family_members`, `payments`, `payment_events` tables exist; their APIs land in Phases 5, 9 and 10.
- Payment-record retention period needs an accountant's confirmation.
- `/metrics` is served by the API process; the production Nginx config (Phase 12) must not proxy it publicly.
- Email links (with one-time tokens) pass through the Redis broker briefly; tokens are single-use and short-lived, and stored hashed in the DB.

## Environment
Build environment (2026-11-12): Ubuntu 24.04, Python 3.12 + 3.13, PostgreSQL 16, Redis 7, package installs **now working**; Docker daemon not running.
Missing for later phases: `wg`, `ip` (iproute2), Ansible, Terraform, Flutter/Dart, Xcode.

## How to run the backend locally
```bash
make env && make keys          # .env + dev JWT keys / node CA in ./secrets
make up                        # postgres, redis, mailpit (http://localhost:8025)
make up-app                    # builds image, runs migrations, starts API/worker/beat
make seed                      # optional: dev sample plans
# API docs: http://localhost:8000/api/docs
```
Tests outside Docker: `python3.12 -m venv .venv && . .venv/bin/activate && make backend-install && make test-backend` (with `make up` running).

## Missing credentials / external needs
None blocking Phase 3/4 code. Full list: `documentation/EXTERNAL_REQUIREMENTS.md`.
**Start now (long lead time):** legal entity → D-U-N-S → Apple Developer Program as an organization.

## Open decisions for the owner
1. Brand name and domain.
2. ~~Where the repository lives~~ — private GitHub repo `Zombik404/kingkongvpn` (2026-11-13).
3. Tax approach for EU sales (VAT OSS yourself vs merchant-of-record) — affects Phase 10.
4. Trial: enable or not, and length (`trial.enabled`, `trial.days` in admin settings; off by default).
5. Prices per plan and currency (set via admin API; dev seed values are placeholders).

## Phase 4 additions (2026-11-13)
- **Staff API `/admin/vpn/*`** (permissions `servers:read` for support/ops, `servers:write` for ops): locations (list with healthy-node counts and "visible to users", create, rename/reorder/hide) and servers (register with a one-time node token, list/detail with load, heartbeat, `accepting`, revision sync, agent version/errors; change status/capacity/tier/location with a reason; rotate the token). `disabled` refuses the node and releases its peers; `draining`/`maintenance` stop new connections only. Every change audited; tokens never logged.
- **Idle-peer release** (`vpn.release_idle_peers`, hourly): takes peers without a handshake for `peers.idle_ttl_hours` off their node; Connect puts them back. **Off by default** (0): in the Telegram version people import a fixed config into the WireGuard app, which never asks us before connecting.
- CI now also checks the bot (ruff, mypy, pytest) and the Mini App (tests, build, committed `dist/` up to date); actions moved off the deprecated Node 20.
- 4 new tests (permissions, register → heartbeat → connect → health, drain/rotate/disable, idle release); checked by breaking the code on purpose.

## Blackjack progression (2026-11-13, done) — ADR-021, owner's brief "Progression, achievements & leaderboards"
Stage plan from the brief; ✅ = done and tested.
- ✅ 1-3 Analysis and integration plan: extends the existing game profile, rounds, bonus wallet + ledger, settings, admin API — no second profile or wallet.
- ✅ 4 XP and levels: XP ledger (`game_xp_events`, unique per key, never negative or lost), level curve from settings (`games.levels.*`, any number of levels), level titles, daily XP cap from rounds (`games.xp.daily_round_cap`, logged once a day).
- ✅ 5 Achievements: 23 seeded in 4 categories (game, activity, progress, season), progress from the player's counters, XP and optional title, each once.
- ✅ 6 Daily challenges (one easy, medium, hard per game day; stable pick) and daily streak (a finished round counts; rewards at 3/7/14/30 days, once per streak).
- ✅ 7 Boards: wins, win rate (wins/(wins+losses), min 20 decided rounds, setting), XP — all time, weekly, monthly, any season; ties by who got there first; my place off the first page; search; pages; participants count; excluded and suspended players hidden.
- ✅ 8-9 Seasons: weekly (Monday 00:00) and monthly in the game time zone, event seasons by staff; finalised once by the `games.seasons` task: final tables frozen (top 100 per board), prizes by place (XP, title, frame; bonus days only with `games.rewards.bonus_days_enabled`, OFF), season achievements, participation XP, Telegram notice to the top 10.
- ✅ Anti-cheat: everything from server-settled rounds; rounds the server finished (timeout, leaving, table closed by staff) give no progress; idempotent keys everywhere; read limits; staff exclusion with a reason in the audit log.
- ✅ Staff API `/admin/games/progress/*`, `/achievements`, `/challenges`, `/seasons` (create event, edit active, finish early, results).
- ✅ 10 Mini App (`miniapp/src/progress.js`): profile card on the games screen; profile (avatar, title, level and XP bar, stats, places, achievements, recent rounds, XP and reward history); boards XP / wins / win % / jackpot × week / month / all time with search, paging, top-3 highlight and your pinned place; achievements by category with progress; daily challenges with timer, day streak and 5-week calendar; seasons with countdown, prizes and archive; after a round: floating XP, achievement / challenge / reward cards, level-up screen. Russian and English; clickable demo has it too.
- ✅ 11 Admin panel "Прогресс и сезоны": players, player page, exclude / return with reason, seasons (table, results, create event, edit, finish), achievements and challenges (enable, edit, create), XP and reward settings. Demo has it too.
- ✅ 12 Tests: backend 308 (Python 3.12 and 3.13) incl. 11 for progression and a privacy test for its data; browser runs on the real backend (4 rounds → XP, challenges, achievements, level-up; every screen; admin: exclude hides from the board and return restores, event season create/edit/finish, catalogue edits, settings, audit entries) and in both demos; no console errors.
- Fixed on the way: season "open if missing" failed after five requests per connection (generic plan vs. partial index; regression test forces the generic plan), blank season countdowns, a stray "null" under the board. Data export now includes XP, achievements, days played, seasons and rewards; account deletion also resets avatar/title and the nickname in past season tables.
- Open: English admin panel; the legal check before `games.rewards.bonus_days_enabled`.

## Admin panel and data protection (2026-11-13) — ADR-020
- **Admin panel** (`admin-panel/`, served at `/admin/` with a strict CSP; guide `documentation/ADMIN_PANEL_RU.md`): password + TOTP (set up on first sign-in), tokens in memory only, auto sign-out after 30 idle minutes, optional network allowlist (`ADMIN_ALLOWED_IPS`). Sections: overview (users, access, servers, revenue, 30-day charts), users (search by email / Telegram ID / referral code / ID; case file; extend or revoke access, block, roles, bonus days; payments, game and audit per user), payments, plans and prices, promo codes, servers and locations (register with a one-time token, drain, disable, rotate token, health), blackjack (switches, suspicious players, tables, events), settings, audit log. Every change asks for a reason and is audited.
- Backend for it: `/admin/me`, `/admin/overview`, `/admin/payments`, better user search, `payments:read`, `python -m app.cli create-staff`; `install.sh` creates the owner's superadmin and prints a one-time password.
- **Data protection** (`documentation/SECURITY_PRIVACY.md`): Telegram users can delete their account (fresh `initData`) and download all their data from the Mini App ("Your data" in Help); deleted players vanish from the board; device/connect/export limits; old revoked devices free their addresses; encrypted backups; API CSP; **Caddy rule order fixed — API docs and schema were publicly reachable**; docs off outside development.
- Verified: backend 291 tests (3.12 and 3.13), admin panel unit tests + full browser run on the real backend (2FA setup and code sign-in, search, extend access, register server and token, drain, settings, promo, audit, phone layout, CSP clean, nothing in storage), Mini App privacy flow in the demo, Caddy config with a real Caddy 2.8.4.

## Next actions
1. **Deploy the test version to a VPS** (`documentation/TEST_LAUNCH_RU.md`): run `install.sh`, register the first node, real WireGuard handshake, @CryptoBot testnet check, Mini App inside real Telegram clients. Needs the owner's server.
2. Admin panel next steps: English UI, support tickets, WebAuthn for staff.
3. Phase 4 rest: node-down alerts to staff, auto-scaling policy (needs a cloud provider decision).
4. Phase 5 rest: Telegram Stars payments, staff commands in the bot.
5. Legal: trademark check for "KingKong VPN"; gambling rules before switching on bonus-day stakes.
