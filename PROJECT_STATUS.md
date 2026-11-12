# Project Status

Last updated: 2026-11-12 · Current phase: **Phase 1 complete → Phase 2 blocked on package installs; Phase 3 started (stdlib-only parts)**

## Phases

| Phase | State | Notes |
|---|---|---|
| 1 — Initialization | ✅ Complete | Repo, architecture, ADR summary, roadmap, env template, dev Compose, scripts |
| 2 — Database & backend | ⛔ Blocked | FastAPI, SQLAlchemy, Alembic, asyncpg, redis-py, Celery, argon2-cffi not installed; package installs disabled in this environment |
| 3 — VPN infrastructure | 🟡 In progress | Node-agent reconciler core done + tested with a fake driver. Real WireGuard needs a VPS (no `wg`/`ip` tools or netns here) |
| 4 — VPN management engine | ⏳ Pending | Depends on 2 |
| 5 — Telegram bot | ⏳ Pending | Needs aiogram + bot token |
| 6 — Mobile apps | ⏳ Pending | Needs Flutter SDK, Android device/emulator, Mac + Xcode, Apple org account |
| 7 — Desktop apps | ⏳ Pending | Needs Windows machine, Mac, code-signing |
| 8 — Web app | ⏳ Pending | Needs npm installs |
| 9 — Admin panel | ⏳ Pending | Needs npm installs |
| 10 — Payments | ⏳ Pending | Needs Stripe test keys, store accounts |
| 11 — Security & optimization | ⏳ Pending | |
| 12 — Production launch | ⏳ Pending | |

## Completed in Phase 1
- Environment inspected (below); repository initialised on `main`.
- `documentation/PROJECT_ARCHITECTURE.md` — system design, 14 ADRs (control/data-plane split, pull-based node agent, client-side key generation, one-address-per-device, isolation rules, auth design, payments per channel, kill switch per platform, privacy/data inventory, i18n, protocol extensibility), data model outline, key flows.
- `documentation/ROADMAP.md` — tasks and demonstrable exit criteria per phase, with where each can run.
- `documentation/EXTERNAL_REQUIREMENTS.md` — 19 accounts/credentials/approvals with lead times.
- `.env.example` (placeholders only), `docker-compose.yml` (postgres 16, redis 7, mailpit; app services behind `app` profile), Postgres init SQL, backend multi-stage Dockerfile, `pyproject.toml`, `Makefile`, `.gitignore`, `.editorconfig`, proprietary `LICENSE`.
- `scripts/check-env.sh` — tool inventory; `scripts/generate-dev-secrets.py` — Ed25519 JWT keys + dev node CA with 0600 permissions.

## Started in Phase 3
- `node-agent/agent/wg.py` — parses `wg show dump` (discards client endpoints and the server private key on parse), CLI driver using argument lists (no shell), public-key validation.
- `node-agent/agent/reconcile.py` — diff/apply with safety rules: host routes inside tunnel pools only (blocks a `0.0.0.0/0` peer from hijacking traffic), no duplicate addresses/keys, mass-removal guard, removals before additions, continues past single failures.

## Tests
| Suite | Result | Command |
|---|---|---|
| node-agent reconciler & parser (21 tests) | ✅ pass | `make test` |
| dev secret generator (2 tests) | ✅ pass | `make test` |
| mypy `--strict` on node-agent | ✅ pass | `cd node-agent && mypy --strict agent` |
| `docker compose config` | ✅ valid | `make compose-check` |
| Real WireGuard handshake | ⛔ not run | needs staging VPS |
| Backend tests | ⛔ not written | Phase 2 blocked |

Failed tests: none.

## Known issues / limitations
- `backend/Dockerfile` `prod` stage copies `migrations/` and `alembic.ini`, which arrive in Phase 2; the image can't be built until then.
- Dependency versions in `backend/pyproject.toml` are lower bounds only; the lock file is created in Phase 2.
- Docker daemon isn't running in this environment, so containers have not been started here (compose file validated only).
- Node agent has no network client yet (long-poll, mTLS, heartbeat) — next Phase 3 step; can be written with stdlib `http.client`/`ssl` but end-to-end testing needs the backend.

## Environment (inspected 2026-11-12)
Available: Ubuntu 24.04, Python 3.13, Node 22, npm 10, git, Docker CLI + Compose v5 (daemon not running), PostgreSQL 16 & Redis 7 binaries, nftables, Rust; Python: pydantic 2, PyJWT, cryptography, starlette, uvicorn, pytest, mypy, PyYAML, requests.
Missing: FastAPI, SQLAlchemy, Alembic, asyncpg, redis-py, Celery, argon2-cffi, pytest-asyncio, aiogram, Stripe SDK; `wg`, `ip` (iproute2), Ansible, Terraform, Flutter/Dart, Xcode.
Network: package installs (pip/npm) are disabled for this account.

## Missing credentials / external needs
None blocking right now except package installs. Full list with lead times: `documentation/EXTERNAL_REQUIREMENTS.md`.
**Start now (long lead time):** legal entity → D-U-N-S → Apple Developer Program as an organization.

## Open decisions for the owner
1. Brand name and domain.
2. Where the repository lives (private GitHub repo, or a folder on your computer).
3. Tax approach for EU sales (VAT OSS yourself vs merchant-of-record) — affects Phase 10 design.

## Next actions
1. Enable package installs (or run Phase 2 on your machine) → implement Phase 2 backend core.
2. Meanwhile: node-agent network client (desired-state long-poll, heartbeat, mTLS) + systemd unit; Ansible `base`/`wireguard`/`nftables` roles with ansible-lint-clean structure; nftables ruleset with isolation and anti-leak rules.
3. Provision one staging VPS (Ubuntu 24.04) when you authorize it → first real handshake.
