# KingKong VPN — notes for AI assistants

WireGuard VPN service run from a Telegram bot + Telegram Mini App, with a FastAPI backend, a
node agent on each VPN server, and a Jungle Kong Blackjack mini-game. Status and history:
`PROJECT_STATUS.md`; decisions: `documentation/adr/`; API: `documentation/BACKEND_API.md`;
game: `documentation/GAMES_BLACKJACK.md`; launch: `documentation/TEST_LAUNCH_RU.md`.

## Find your way with the code graph (do this first)

The repository has a code graph built by graphify (AST-based, local, no API cost):

- `make graph` (or `graphify update .`) rebuilds `graphify-out/graph.json`, `graph.html` and
  `GRAPH_REPORT.md`. Rebuild after pulling or before a larger change; the report says which
  commit it was built from.
- `graphify query "<question>" --budget 2000` — where a behaviour lives (BFS over the graph).
- `graphify explain "<symbol>"` — a symbol and its neighbours; `graphify path "A" "B"`.
- `graphify affected "<symbol>"` — what depends on it (blast radius before editing).
- `graphify god-nodes` — the hubs (AppContext, Settings, AuthService, User, …).
- `graphify-out/graph.html` — open in a browser for the interactive map.
- When the private GitHub repo is indexed by the Graphify connector, its tools
  (`graphify_find`, `query_graph`, `graphify_callers`, `graphify_impact`, `graphify_tests_for`)
  answer the same questions without a local build.

## Layout

| Path | What |
|---|---|
| `backend/app/` | FastAPI app: `api/v1` (routes), `services` (auth, users, devices, referrals, settings, audit), `subscriptions`, `payments` (@CryptoBot), `vpn` (locations, connect, node agent API, usage), `games` (blackjack engine, fair shuffle, bonus wallet, tables), `notifications`, `workers` (Celery), `models`, `i18n/locales` (en/ru/uk/de/hu) |
| `backend/migrations/versions/` | Alembic `0001`–`0009` (a test fails if models and migrations drift) |
| `backend/tests/` | pytest against real PostgreSQL + Redis |
| `miniapp/src/` | Telegram Mini App (vanilla JS, esbuild): `app.js`, `games.js`, `fair.js`, `jungle.js`, `charts.js`, `wg.js`, `i18n.js`, `style.css`, `assets/` |
| `miniapp/demo/` | Clickable demo with a stand-in Telegram + API (`node demo/build.mjs`) |
| `miniapp/tools/` | Python scripts that render the artwork (jungle, gorilla, dealer, overgrowth) |
| `admin-panel/` | Staff console at `/admin/` (vanilla JS, esbuild, commit `dist/`): `src/main.js` (sign-in, 2FA, router), `src/api.js` (tokens in memory), `src/pages/*`; `demo/` = same UI on a fake API |
| `telegram-bot/` | aiogram bot (stateless: opens the Mini App, deep links, `/games`) |
| `node-agent/` | Agent on each VPN server (stdlib): applies peers, heartbeats with counters |
| `deploy/` | Single-server install (`install.sh`), Caddy, compose, nftables firewall |

## Checks (run what you touched)

- Backend: `cd backend && pytest -q` (needs Postgres + Redis), `ruff check app tests`,
  `ruff format --check app tests migrations`, `mypy --strict app`, `python -m app.openapi`
  (regenerates `shared/api-contracts/openapi.json`; a test compares it).
- Mini App: `cd miniapp && npm test && npm run build` (commit `miniapp/dist/`), demo:
  `node demo/build.mjs`.
- Admin panel: `cd admin-panel && npm test && npm run build` (commit `admin-panel/dist/`), demo:
  `node demo/build.mjs`.
- Bot: `cd telegram-bot && pytest -q`. Node agent: `cd node-agent && pytest -q`.

## Rules that must not break

- Private WireGuard keys are generated on the user's device and never sent anywhere (ADR-003).
- Mini App and admin panel put API data into the page as text only (no `innerHTML` of API
  data); the admin panel's CSP forbids inline styles, so set styles through `el.style`.
- Admin panel keeps tokens in memory only; staff routes need TOTP. What we store about users:
  `documentation/SECURITY_PRIVACY.md` — update it when adding personal data.
- Bot token and Crypto Pay token live only in `.env` on the server; never in git or chat.
- Paid subscription days can never be staked or lost in a game; only the bonus wallet
  (`games.blackjack.stakes_enabled`, off by default — legal check pending) or fun chips (no
  value) are staked. Game outcomes, cards and balances are decided on the server only.
- Every money/balance change is idempotent (unique keys, row locks) and audited.
- The owner's brand is "KingKong VPN" (trademark check pending, ADR-018 §5); the gorilla
  dealer/swinger is an original character, not the film's.
