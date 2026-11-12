# Project Status

Last updated: 2026-11-12 · Current phase: **Phase 2 complete → next: Phase 3 (node enrollment + agent network client) and Phase 4**

## Phases

| Phase | State | Notes |
|---|---|---|
| 1 — Initialization | ✅ Complete | Repo, architecture, ADR summary, roadmap, env template, dev Compose, scripts |
| 2 — Database & backend | ✅ Complete | FastAPI + SQLAlchemy 2 + Alembic + Celery; auth, users, devices, plans, subscriptions, promo, RBAC, audit, email; 165 tests, 97 % coverage |
| 3 — VPN infrastructure | 🟡 In progress | Node-agent reconciler core done + tested with a fake driver. Unblocked now: enrollment + desired-state API. Real WireGuard needs a VPS |
| 4 — VPN management engine | ⏳ Pending | Unblocked by Phase 2 |
| 5 — Telegram bot | ⏳ Pending | Needs bot token |
| 6 — Mobile apps | ⏳ Pending | Needs Flutter SDK, Android device/emulator, Mac + Xcode, Apple org account |
| 7 — Desktop apps | ⏳ Pending | Needs Windows machine, Mac, code-signing |
| 8 — Web app | ⏳ Pending | API contract ready (`shared/api-contracts/openapi.json`) |
| 9 — Admin panel | ⏳ Pending | Staff API ready |
| 10 — Payments | ⏳ Pending | Needs Stripe test keys, store accounts |
| 11 — Security & optimization | ⏳ Pending | |
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

## Tests
| Suite | Result | Command |
|---|---|---|
| Backend: 165 tests on real PostgreSQL 16 + Redis 7 | ✅ pass (Python 3.12 and 3.13) | `make up && make test-backend` |
| Backend coverage | ✅ 97 % total — auth 96 %, subscriptions 96 %, devices 95 % (target ≥ 85 %) | same |
| Migration up → down → up on a fresh DB; models ↔ migration drift; OpenAPI drift | ✅ pass | part of backend suite |
| Concurrency: 8 parallel device registrations vs limit 3; parallel address allocation; parallel promo redemption vs `max_redemptions` | ✅ pass | part of backend suite |
| `ruff check` + `ruff format --check`; `mypy --strict` on `backend/app` (53 files) | ✅ clean | `make lint` |
| `pip-audit` on the lock file | ✅ no known vulnerabilities | CI |
| End-to-end smoke (staging-mode settings, real uvicorn + Celery worker + SMTP sink): register → localized email delivered by worker → verify → login → device registered with tunnel addresses; beat starts | ✅ pass (run manually 2026-11-12) | see `documentation/BACKEND_API.md` flows |
| node-agent reconciler & parser (21) + secret generator (2) | ✅ pass | `make test` |
| Docker image build | ⛔ not run | Docker daemon unavailable in the build environment — run `make up-app` locally |
| CI workflow on GitHub | ⛔ not run | repository not on GitHub yet |
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
2. Where the repository lives (private GitHub repo enables the CI workflow).
3. Tax approach for EU sales (VAT OSS yourself vs merchant-of-record) — affects Phase 10.
4. Trial: enable or not, and length (`trial.enabled`, `trial.days` in admin settings; off by default).
5. Prices per plan and currency (set via admin API; dev seed values are placeholders).

## Next actions
1. **Phase 3**: node enrollment (one-time token → CSR → cert signed by the node CA), `GET /internal/v1/nodes/{id}/desired-state` long-poll + heartbeat endpoints (mTLS), node-agent network client + systemd unit; Ansible `base`/`wireguard`/`nftables` roles.
2. **Phase 4**: server registry admin API, `POST /vpn/connect` with server selection (ADR-006), idle-peer GC, Redis wake-ups for agents.
3. Provision one staging VPS when authorized → first real handshake.
