# global-vpn

Commercial WireGuard VPN platform: control-plane API, VPN node agent and infrastructure, Telegram bot,
Android/iOS/Windows/macOS apps, website and admin panel. Working name — the brand is not chosen yet.

- **Architecture and decisions:** [`documentation/PROJECT_ARCHITECTURE.md`](documentation/PROJECT_ARCHITECTURE.md)
- **Roadmap:** [`documentation/ROADMAP.md`](documentation/ROADMAP.md)
- **Status (what works, what's blocked):** [`PROJECT_STATUS.md`](PROJECT_STATUS.md)
- **Accounts and credentials needed:** [`documentation/EXTERNAL_REQUIREMENTS.md`](documentation/EXTERNAL_REQUIREMENTS.md)

## Repository layout

| Path | Contents | Status |
|---|---|---|
| `backend/` | FastAPI control-plane API + Celery workers | Phase 2 — skeleton (Dockerfile, pyproject) |
| `node-agent/` | Agent on each VPN server; reconciles WireGuard peers with the backend | Phase 3 — reconciler core implemented & tested |
| `vpn-infrastructure/` | Ansible roles, Terraform, nftables, unbound, exporters | Phase 3 |
| `telegram-bot/` | aiogram 3 bot (webhook) | Phase 5 |
| `mobile-app/` | Flutter app with native Android VpnService / iOS Network Extension | Phase 6 |
| `desktop-app/` | Flutter desktop with native Windows / macOS tunnel integration | Phase 7 |
| `web-app/` | Next.js website and account dashboard | Phase 8 |
| `admin-panel/` | Next.js admin dashboard (separate deployment) | Phase 9 |
| `shared/` | OpenAPI contract, locale catalogs | Phase 2+ |
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
make test          # run existing test suites
```

Application services (`backend`, `worker`, `beat`) start with `make up-app` once Phase 2 lands.

## Ground rules
Secrets never go into Git (`.env`, `secrets/` and key files are ignored; `make secret-scan` checks).
No mocked feature is reported as working. See the strict development rules in the architecture document.
