# global-vpn

Commercial WireGuard VPN platform: control-plane API, VPN node agent and infrastructure, Telegram bot,
Android/iOS/Windows/macOS apps, website and admin panel. Working name — the brand is not chosen yet.

- **Architecture and decisions:** [`documentation/PROJECT_ARCHITECTURE.md`](documentation/PROJECT_ARCHITECTURE.md)
- **Roadmap:** [`documentation/ROADMAP.md`](documentation/ROADMAP.md)
- **Status (what works, what's blocked):** [`PROJECT_STATUS.md`](PROJECT_STATUS.md)
- **Запуск тестовой версии (RU):** [`documentation/TEST_LAUNCH_RU.md`](documentation/TEST_LAUNCH_RU.md)
- **Backend API / database:** [`documentation/BACKEND_API.md`](documentation/BACKEND_API.md), [`documentation/DATABASE_SCHEMA.md`](documentation/DATABASE_SCHEMA.md)
- **Accounts and credentials needed:** [`documentation/EXTERNAL_REQUIREMENTS.md`](documentation/EXTERNAL_REQUIREMENTS.md)

## Repository layout

| Path | Contents | Status |
|---|---|---|
| `backend/` | FastAPI control-plane API + Celery workers | Phase 2 ✅ — auth, devices, subscriptions, admin API, crypto payments, VPN connect, Telegram auth; 200 tests |
| `node-agent/` | Agent on each VPN server; reconciles WireGuard peers with the backend | Test slice ✅ — reconciler, control-plane client, systemd unit |
| `vpn-infrastructure/` | Ansible roles, Terraform, nftables, unbound, exporters | Phase 3 |
| `telegram-bot/` | aiogram 3 bot (entry point to the Mini App) | Test slice ✅ |
| `miniapp/` | Telegram Mini App (keys generated on the device) | Test slice ✅ |
| `deploy/` | One-server test deployment (`install.sh`) | Ready — guide: `documentation/TEST_LAUNCH_RU.md` |
| `mobile-app/` | Flutter app with native Android VpnService / iOS Network Extension | Phase 6 |
| `desktop-app/` | Flutter desktop with native Windows / macOS tunnel integration | Phase 7 |
| `web-app/` | Next.js website and account dashboard | Phase 8 |
| `admin-panel/` | Next.js admin dashboard (separate deployment) | Phase 9 |
| `shared/` | OpenAPI contract (`api-contracts/openapi.json`), locale catalogs | Phase 2+ |
| `infrastructure/` | Docker configs, deployment, CI/CD, backups, monitoring | Phase 1+ |
| `documentation/` | Architecture, roadmap, guides, ADRs | ongoing |
| `scripts/` | Dev tooling | Phase 1 |

## Development quick start

Requirements: Docker with Compose v2, Python 3.12+, GNU make.

```bash
make check-env     # what's installed, what's missing
make env           # create .env from .env.example
make keys          # dev JWT signing keys + node CA into ./secrets (git-ignored)
make up            # postgres, redis, mailpit (mail UI: http://localhost:8025)
make up-app        # build + migrate + start API (http://localhost:8000/api/docs), worker, beat
make seed          # optional dev sample plans
make test          # node-agent + scripts suites (no services needed)
make test-backend  # backend suite against the running postgres/redis
make lint          # ruff + mypy --strict
```

First staff account: register and verify normally, then
`docker compose --profile app run --rm backend python -m app.cli grant-role you@example.com superadmin`
and enable 2FA (`/api/v1/auth/mfa/totp/setup`).

## Ground rules
Secrets never go into Git (`.env`, `secrets/` and key files are ignored; `make secret-scan` checks).
No mocked feature is reported as working. See the strict development rules in the architecture document.
