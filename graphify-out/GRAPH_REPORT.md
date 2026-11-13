# Graph Report - global-vpn  (2026-11-13)

## Corpus Check
- 162 files · ~123,093 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 20 file(s) not represented in the graph (top: (none) 9, .lock 3, .service 2)

## Summary
- 2391 nodes · 7863 edges · 121 communities (99 shown, 22 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 594 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b6e8b73a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- new_user
- vpn/service.py
- pytest
- blackjack.py
- numpy
- sqlalchemy
- models/__init__.py
- Principal
- Settings
- account.py
- AuthService
- games/service.py
- post
- subscriptions/service.py
- v1/games.py
- mock.js
- admin/games.py
- backend
- tasks.py
- AppContext
- test_platform.py
- TokenService
- app/main.py
- routes.py
- sqlalchemy
- test_payments.py
- __main__.py
- bot/main.py
- test_reconcile.py
- test_telegram_vpn.py
- payments/service.py
- base64
- app.js
- test_games.py
- AppContext
- utcnow
- notifications/telegram.py
- CryptoBotClient
- payments.py
- initGames
- Any
- wg.test.mjs
- createGames
- referrals.py
- test_agent_loop.py
- package.json
- backend/tests/conftest.py
- worker
- Project Status
- services
- 3. Architectural decisions (ADR summary)
- Implementation Roadmap
- reconcile.py
- options
- Jungle Kong Blackjack — integration plan and reference
- README.md
- charts.js
- fair.py
- _admin_user_out
- Запуск тестовой версии в Telegram
- vpn/service.py
- send_notices
- config.py
- redis
- redis
- install.sh
- redis
- jungle.js
- ip_prefix
- x-backend-common
- room_updates
- backend
- beat
- bot
- migrate
- postgres
- Backend API (v1)
- os
- context
- caddy
- postgres
- x-app
- Endpoints
- Project Architecture
- enums.py
- path
- healthcheck
- asyncio
- backend
- redis
- i18n.js
- .__init__
- ConfigError
- beat
- migrate
- passwords.py
- check-env.sh
- backup.sh
- docker-user.sh
- 0015-backend-core-decisions.md
- 0016-crypto-payments-cryptobot.md
- 0017-telegram-test-deployment.md
- 0018-vpnhub-traffic-referrals.md
- globalvpn-backend
- globalvpn-bot
- test_devices.py
- __main__.py
- env.py
- list_plans
- Conflict
- KingKong VPN — notes for AI assistants
- make_sessionmaker

## God Nodes (most connected - your core abstractions)
1. `AppContext` - 123 edges
2. `utcnow()` - 108 edges
3. `new_user()` - 89 edges
4. `Settings` - 71 edges
5. `AuthService` - 57 edges
6. `post()` - 55 edges
7. `AppError` - 51 edges
8. `User` - 50 edges
9. `ActorType` - 46 edges
10. `record()` - 45 edges

## Surprising Connections (you probably didn't know these)
- `ADR-008 — Payments: one entitlement model, several stores` --references--> `Subscription`  [INFERRED]
  documentation/PROJECT_ARCHITECTURE.md → backend/app/models/billing.py
- `What exists in the project and how the game uses it` --references--> `grant_days()`  [INFERRED]
  documentation/GAMES_BLACKJACK.md → backend/app/subscriptions/service.py
- `Architecture` --references--> `room_view()`  [INFERRED]
  documentation/GAMES_BLACKJACK.md → backend/app/games/service.py
- `Billing` --references--> `device_limit()`  [INFERRED]
  documentation/DATABASE_SCHEMA.md → backend/app/services/devices.py
- `Background jobs (Celery beat)` --references--> `poll_pending()`  [INFERRED]
  documentation/BACKEND_API.md → backend/app/payments/service.py

## Import Cycles
- None detected.

## Communities (121 total, 22 thin omitted)

### Community 0 - "new_user"
Cohesion: 0.06
Nodes (46): _secret(), sign_init_data(), TelegramUser, validate_init_data(), b32(), code_at(), current_counter(), new_secret() (+38 more)

### Community 1 - "vpn/service.py"
Cohesion: 0.08
Nodes (22): connect(), ConnectIn, ConnectOut, desired_state(), heartbeat(), HeartbeatIn, list_locations(), LocationOut (+14 more)

### Community 2 - "pytest"
Cohesion: 0.09
Nodes (32): SubscriptionStatus, apply(), Event, InvalidTransition, start(), SubState, AddressPool, insert_with_address() (+24 more)

### Community 3 - "blackjack.py"
Cohesion: 0.08
Nodes (42): act(), _advance(), _after_peek(), allowed_actions(), card_value(), _dealer_natural(), _dealer_play(), decide_insurance() (+34 more)

### Community 4 - "numpy"
Cohesion: 0.07
Nodes (32): bezier(), blur(), leaf_tile(), noise(), paste_leaf(), _safe_composite(), stroke(), banana() (+24 more)

### Community 5 - "sqlalchemy"
Cohesion: 0.07
Nodes (10): violated_constraint(), RateLimited, ServiceUnavailable, InsufficientBonus, AccessClaims, _def(), get_all(), InvalidSetting (+2 more)

### Community 6 - "models/__init__.py"
Cohesion: 0.13
Nodes (27): Base, Timestamps, UUIDPk, Campaign, FamilyMember, Payment, PaymentEvent, Plan (+19 more)

### Community 7 - "Principal"
Cohesion: 0.12
Nodes (27): require(), dependency(), _audit(), audit_logs(), create_plan(), create_price(), create_promo(), _get_plan() (+19 more)

### Community 8 - "Settings"
Cohesion: 0.10
Nodes (6): Settings, make_engine(), _load_keys(), test_database_url_assembled(), test_production_accepts_real_secrets(), settings()

### Community 9 - "account.py"
Cohesion: 0.11
Nodes (27): cancel(), claim_referral(), delete_me(), export_me(), get_subscription(), list_devices(), list_sessions(), me() (+19 more)

### Community 10 - "AuthService"
Cohesion: 0.08
Nodes (19): get_client(), get_ctx(), InvalidCredentials, InvalidToken, NotAuthenticated, ActorType, AuditResult, AuditLog (+11 more)

### Community 11 - "games/service.py"
Cohesion: 0.15
Nodes (34): act(), admin_adjust(), bank_move(), clean_nickname(), close_room(), config(), create_room(), current_seat() (+26 more)

### Community 12 - "post"
Cohesion: 0.13
Nodes (35): login(), logout(), logout_all(), mfa_verify(), _pair_out(), password_change(), password_reset_confirm(), password_reset_request() (+27 more)

### Community 13 - "subscriptions/service.py"
Cohesion: 0.15
Nodes (19): Subscription, Provider, notify(), Entitlement, entitlement(), get_live(), grant_days(), has_access_to_purchase() (+11 more)

### Community 14 - "v1/games.py"
Cohesion: 0.12
Nodes (25): action(), ActionIn, bet(), BetIn, create_room(), fairness(), get_room(), get_wallet() (+17 more)

### Community 15 - "mock.js"
Cohesion: 0.07
Nodes (33): addDays(), backend(), device(), el(), fail(), friendPaid(), iso(), json() (+25 more)

### Community 16 - "admin/games.py"
Cohesion: 0.12
Nodes (18): adjust_bonus(), BonusAdjustIn, close_room(), events(), ledger(), overview(), pause_room(), players() (+10 more)

### Community 17 - "backend"
Cohesion: 0.05
Nodes (43): defaults, runs-on, services, steps, timeout-minutes, concurrency, cancel-in-progress, group (+35 more)

### Community 18 - "tasks.py"
Cohesion: 0.10
Nodes (17): normalize(), CeleryDispatcher, EmailDispatcher, EmailJob, make_dispatcher(), MemoryDispatcher, render(), RenderedEmail (+9 more)

### Community 19 - "AppContext"
Cohesion: 0.29
Nodes (14): bootstrap_catalog(), create_invites(), grant_role(), main(), node_register(), seed_dev(), set_price(), set_setting() (+6 more)

### Community 20 - "test_platform.py"
Cohesion: 0.09
Nodes (14): catalog(), _lookup(), negotiate(), _SafeDict, t(), scrub(), test_catalogs_have_identical_keys(), keys() (+6 more)

### Community 22 - "app/main.py"
Cohesion: 0.15
Nodes (4): create_app(), lifespan(), __getattr__(), test_production_hides_docs()

### Community 23 - "routes.py"
Cohesion: 0.11
Nodes (29): AdminRolesIn, AdminUserOut, AdminUserStatusIn, AuditLogOut, DeleteAccountIn, DeviceIn, DeviceListOut, DeviceRenameIn (+21 more)

### Community 24 - "sqlalchemy"
Cohesion: 0.09
Nodes (14): downgrade(), upgrade(), downgrade(), _provider_check(), upgrade(), upgrade(), upgrade(), upgrade() (+6 more)

### Community 25 - "test_payments.py"
Cohesion: 0.18
Nodes (23): poll_pending(), checkout(), fake(), FakeCryptoPay, seed(), settings(), test_amount_and_payload_mismatch_do_not_grant(), test_checkout_creates_invoice() (+15 more)

### Community 26 - "__main__.py"
Cohesion: 0.16
Nodes (8): AgentConfig, ControlPlane, ControlPlaneError, parse_desired(), DesiredPeer, parse_pools(), test_env_file_parsing(), test_parse_desired_rejects_garbage()

### Community 27 - "bot/main.py"
Cohesion: 0.15
Nodes (18): BotConfig, build_dispatcher(), on_games(), on_help(), on_other(), on_start(), configure(), lang_of() (+10 more)

### Community 28 - "test_reconcile.py"
Cohesion: 0.23
Nodes (23): DesiredState, DesiredStateError, make_plan(), reconcile(), validate(), PeerState, FakeDriver, key() (+15 more)

### Community 29 - "test_telegram_vpn.py"
Cohesion: 0.29
Nodes (18): beat(), entitled_user_with_device(), init_data(), node_get(), register_node(), test_cleanup_purges_old_removed_assignments(), test_connect_flow_and_desired_state(), test_expired_user_is_dropped_even_without_bump() (+10 more)

### Community 30 - "payments/service.py"
Cohesion: 0.10
Nodes (20): uuid7(), PromoKind, add_period(), apply_invoice(), checkout(), _client(), _credit(), describe() (+12 more)

### Community 31 - "base64"
Cohesion: 0.15
Nodes (7): CliWgDriver, InterfaceState, is_valid_public_key(), _parse_allowed_ips(), parse_dump(), WgError, test_parse_dump_rejects_malformed()

### Community 32 - "app.js"
Cohesion: 0.12
Nodes (53): addDeviceForm(), api(), applyTheme(), APPS, brand(), celebrate(), checkVpn(), chooseTheme() (+45 more)

### Community 33 - "test_games.py"
Cohesion: 0.21
Nodes (34): balance(), bet(), chip_round(), chips(), ctx_session(), do(), expire(), give() (+26 more)

### Community 34 - "AppContext"
Cohesion: 0.24
Nodes (16): set_value(), fake(), _pay(), _refer(), settings(), test_promo_code_beats_referral_discount(), test_referral_bonus_days_extend_existing_subscription(), test_referral_bonus_days_off_and_suspended_referrer() (+8 more)

### Community 35 - "utcnow"
Cohesion: 0.22
Nodes (18): PromoCode, new_user(), test_cleanup_tokens(), test_free_days_redeem_starts_then_extends(), test_invalid_codes(), test_max_redemptions_under_concurrency(), test_trial_converted_by_promo(), test_validate_discount_codes() (+10 more)

### Community 36 - "notifications/telegram.py"
Cohesion: 0.14
Nodes (11): CeleryTelegramDispatcher, make_telegram_dispatcher(), MemoryTelegramDispatcher, NullTelegramDispatcher, send_sync(), TelegramDispatcher, TelegramJob, TelegramSendError (+3 more)

### Community 37 - "CryptoBotClient"
Cohesion: 0.16
Nodes (11): cryptobot_check(), CryptoBotClient, Invoice, minor_to_amount(), parse_webhook(), PaymentProviderError, _ts(), test_amounts_and_periods() (+3 more)

### Community 38 - "payments.py"
Cohesion: 0.14
Nodes (10): checkout(), CheckoutIn, cryptobot_webhook(), get_payment(), InvalidWebhook, list_payments(), _out(), PaymentOut (+2 more)

### Community 39 - "initGames"
Cohesion: 0.22
Nodes (22): initGames(), apply(), card(), closeTable(), connect(), drawControls(), drawFoot(), fairSheet() (+14 more)

### Community 40 - "Any"
Cohesion: 0.11
Nodes (16): hub(), balance_in(), chips_of(), currency_of(), ensure_profile(), fairness(), leaderboard(), profile_out() (+8 more)

### Community 41 - "wg.test.mjs"
Cohesion: 0.16
Nodes (15): ADR-0003, RFC-7748, moveDevice(), params, root, ru, b64decode(), b64encode() (+7 more)

### Community 42 - "createGames"
Cohesion: 0.17
Nodes (22): createGames(), act(), actions(), deal(), finish(), nextHand(), publicRound(), view() (+14 more)

### Community 43 - "referrals.py"
Cohesion: 0.16
Nodes (13): claim(), ensure_code(), _grant_bonus_days(), Granted, _has_paid(), InvalidReferral, invitee_discount(), Level (+5 more)

### Community 44 - "test_agent_loop.py"
Cohesion: 0.24
Nodes (9): Agent, backend(), Backend, cfg(), test_backend_down_keeps_peers(), test_bad_token_and_unsafe_state(), test_failed_apply_requests_full_state(), test_step_applies_desired_state_and_heartbeat() (+1 more)

### Community 45 - "package.json"
Cohesion: 0.13
Nodes (15): js, description, devDependencies, esbuild@0.25.10, @noble/curves@1.9.7, qrcode-generator@1.4.4, name, private (+7 more)

### Community 46 - "backend/tests/conftest.py"
Cohesion: 0.22
Nodes (7): alembic_config(), client(), make_settings(), outbox(), _schema(), settings(), token_from()

### Community 47 - "worker"
Cohesion: 0.12
Nodes (16): name, services, worker, volumes, caddyconfig, caddydata, pgdata, redisdata (+8 more)

### Community 48 - "Project Status"
Cohesion: 0.12
Nodes (17): Added after Phase 2: crypto payments (@CryptoBot), Completed in Phase 2, Environment, How to run the backend locally, Jungle Kong Blackjack (2026-11-13) — ADR-019, documentation/GAMES_BLACKJACK.md, KingKong VPN rebrand (2026-11-13) — ADR-018 §5–6, Known issues / limitations, Mini App redesign (2026-11-13) — ADR-018 (+9 more)

### Community 49 - "services"
Cohesion: 0.13
Nodes (14): image, ports, restart, name, services, mailpit, worker, volumes (+6 more)

### Community 50 - "3. Architectural decisions (ADR summary)"
Cohesion: 0.13
Nodes (15): 3. Architectural decisions (ADR summary), ADR-001 — Modular monolith backend, not microservices, ADR-002 — Pull-based node agent for VPN servers (control/data plane split), ADR-003 — Client-side key generation; no private keys on the platform, ADR-004 — One tunnel address per device, valid on any server, ADR-005 — Traffic isolation and anti-leak on nodes, ADR-006 — Server selection, ADR-007 — Authentication (+7 more)

### Community 51 - "Implementation Roadmap"
Cohesion: 0.14
Nodes (14): Implementation Roadmap, Phase 10 — Payments  [S]+[X], Phase 11 — Security & optimization  [S]+[V], Phase 12 — Production launch  [V]+[X], Phase 1 — Project initialization  ✅ (this commit), Phase 2 — Database and backend core  [S]  ✅ (2026-11-12), Phase 3 — VPN infrastructure  [S]+[V], Phase 4 — VPN management engine  [S]+[V] (+6 more)

### Community 52 - "reconcile.py"
Cohesion: 0.27
Nodes (4): apply(), ApplyResult, Plan, WgDriver

### Community 53 - "options"
Cohesion: 0.26
Nodes (13): logging, logging, logging, logging, driver, options, logging, max-file (+5 more)

### Community 54 - "Jungle Kong Blackjack — integration plan and reference"
Cohesion: 0.15
Nodes (11): ADR-019 — Mini-games: Jungle Kong Blackjack, API (all under `/api/v1`, bearer token), Architecture, Bonus days, Fun chips and the jackpot board, Jungle Kong Blackjack — integration plan and reference, Notices (Telegram / email), Provably fair (+3 more)

### Community 55 - "README.md"
Cohesion: 0.15
Nodes (6): Credentials the platform generates itself (no action needed), External Accounts, Credentials and Approvals, Development quick start, global-vpn, Ground rules, Repository layout

### Community 56 - "charts.js"
Cohesion: 0.31
Nodes (12): dashboard(), fmtShort(), arcPath(), areaChart(), el(), formatBytes(), gradient(), progressRing() (+4 more)

### Community 57 - "fair.py"
Cohesion: 0.29
Nodes (6): combine_client_seeds(), new_server_seed(), seed_hash(), shuffled_shoe(), _stream(), test_fair_shuffle_is_deterministic_verifiable_and_unbiased_enough()

### Community 58 - "_admin_user_out"
Cohesion: 0.33
Nodes (3): _admin_user_out(), export_data(), _iso()

### Community 59 - "Запуск тестовой версии в Telegram"
Cohesion: 0.17
Nodes (12): Если что-то не работает, Запуск тестовой версии в Telegram, Полезные команды (на сервере), Чего в тестовой версии нет, Что понадобится, Шаг 0. Оформление бота, Шаг 1. Сервер, Шаг 2. Адрес (DuckDNS) (+4 more)

### Community 60 - "vpn/service.py"
Cohesion: 0.13
Nodes (27): MfaRequiredForAdmin, AppError, NotFound, AssignmentState, DeviceStatus, Device, InvalidMfaCode, active_count() (+19 more)

### Community 62 - "config.py"
Cohesion: 0.13
Nodes (3): generate(), main(), test_openapi_contract_is_up_to_date()

### Community 63 - "redis"
Cohesion: 0.24
Nodes (11): depends_on, depends_on, migrate, postgres, redis, condition, depends_on, condition (+3 more)

### Community 64 - "redis"
Cohesion: 0.24
Nodes (11): interval, retries, test, timeout, healthcheck, command, healthcheck, image (+3 more)

### Community 65 - "install.sh"
Cohesion: 0.35
Nodes (9): ask(), cli(), DEBIAN_FRONTEND, die(), env_get(), keep_or(), say(), install.sh script (+1 more)

### Community 66 - "redis"
Cohesion: 0.24
Nodes (11): depends_on, depends_on, migrate, postgres, redis, condition, depends_on, condition (+3 more)

### Community 67 - "jungle.js"
Cohesion: 0.40
Nodes (10): buildOvergrowth(), el(), enter(), img(), leafFall(), mountJungle(), reduced(), setOvergrowth() (+2 more)

### Community 68 - "ip_prefix"
Cohesion: 0.22
Nodes (8): ip_prefix(), test_ip_prefix(), Accounts and auth, Billing, Database schema, Operations, Retention (as implemented), VPN

### Community 69 - "x-backend-common"
Cohesion: 0.29
Nodes (10): build, build, context, target, build, build, x-backend-common, build (+2 more)

### Community 70 - "room_updates"
Cohesion: 0.12
Nodes (7): get_db(), get_principal(), principal_from_token(), room_updates(), ws(), pump(), channel()

### Community 71 - "backend"
Cohesion: 0.22
Nodes (9): cap_drop, env_file, ports, read_only, restart, security_opt, tmpfs, volumes (+1 more)

### Community 72 - "beat"
Cohesion: 0.22
Nodes (9): cap_drop, command, env_file, read_only, restart, security_opt, tmpfs, volumes (+1 more)

### Community 73 - "bot"
Cohesion: 0.22
Nodes (9): cap_drop, environment, read_only, restart, security_opt, APP_NAME, MINIAPP_URL, TELEGRAM_BOT_TOKEN (+1 more)

### Community 74 - "migrate"
Cohesion: 0.22
Nodes (9): cap_drop, command, env_file, read_only, restart, security_opt, tmpfs, volumes (+1 more)

### Community 75 - "postgres"
Cohesion: 0.22
Nodes (9): POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER, environment, image, ports, restart, volumes (+1 more)

### Community 76 - "Backend API (v1)"
Cohesion: 0.22
Nodes (9): Backend API (v1), Conventions, Global settings (`/admin/settings`), Health, Payments (crypto via @CryptoBot), Staff API and permissions, Telegram Mini App and VPN connect, Traffic and referrals (+1 more)

### Community 77 - "os"
Cohesion: 0.27
Nodes (6): _wg_public_key(), purge_deleted_users(), test_delete_account(), test_export(), test_update_locale(), test_public_key_helper()

### Community 78 - "context"
Cohesion: 0.39
Nodes (8): build, build, build, context, target, build, build, build

### Community 79 - "caddy"
Cohesion: 0.25
Nodes (8): depends_on, environment, image, ports, restart, volumes, DOMAIN, caddy

### Community 80 - "postgres"
Cohesion: 0.25
Nodes (8): POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER, environment, image, restart, volumes, postgres

### Community 81 - "x-app"
Cohesion: 0.25
Nodes (8): x-app, cap_drop, env_file, read_only, restart, security_opt, tmpfs, volumes

### Community 82 - "Endpoints"
Cohesion: 0.25
Nodes (8): account, admin, auth, devices, Endpoints, plans, promo, subscription

### Community 83 - "Project Architecture"
Cohesion: 0.25
Nodes (8): 1. System overview, 2. Components, 4. Core data model (outline), 5. Key flows, 6. Environments, 7. Security baseline (expanded in `SECURITY_POLICY.md`), 8. Scalability envelope (initial targets), Project Architecture

### Community 84 - "enums.py"
Cohesion: 0.23
Nodes (11): ActionTokenPurpose, DevicePlatform, NotificationChannel, NotificationStatus, PaymentKind, PeriodUnit, Role, ServerStatus (+3 more)

### Community 85 - "path"
Cohesion: 0.48
Nodes (7): env_file, env_file, path, required, env_file, env_file, env_file

### Community 86 - "healthcheck"
Cohesion: 0.57
Nodes (7): healthcheck, interval, retries, test, timeout, healthcheck, healthcheck

### Community 87 - "asyncio"
Cohesion: 0.29
Nodes (8): cleanup_tokens_task(), game_timers_task(), poll_payments_task(), process_due_task(), purge_deleted_task(), send_reminders_task(), _with_db(), test_periodic_task_wrappers_run()

### Community 88 - "backend"
Cohesion: 0.33
Nodes (6): command, ports, profiles, restart, volumes, backend

### Community 89 - "redis"
Cohesion: 0.33
Nodes (6): command, image, ports, restart, volumes, redis

### Community 90 - "i18n.js"
Cohesion: 0.33
Nodes (5): en, makeT(), pickLang(), ru, STRINGS

### Community 91 - ".__init__"
Cohesion: 0.60
Nodes (4): _auth(), do_GET(), do_POST(), _json()

### Community 92 - "ConfigError"
Cohesion: 0.20
Nodes (5): ConfigError, FieldCipher, test_field_cipher_key_validation(), test_jwt_key_loading_edge_cases(), test_production_refuses_placeholders()

### Community 93 - "beat"
Cohesion: 0.40
Nodes (5): command, profiles, restart, volumes, beat

### Community 94 - "migrate"
Cohesion: 0.40
Nodes (5): command, profiles, restart, volumes, migrate

### Community 95 - "passwords.py"
Cohesion: 0.19
Nodes (3): PasswordService, VerifyResult, WeakPassword

### Community 114 - "test_devices.py"
Cohesion: 0.45
Nodes (8): give_plan(), test_concurrent_registrations_respect_limit(), test_device_limit_without_and_with_plan(), test_duplicate_key_rejected_even_across_users(), test_invalid_public_keys_rejected(), test_register_device_allocates_addresses(), test_rename_revoke_and_isolation(), wg_key()

### Community 116 - "env.py"
Cohesion: 0.27
Nodes (4): _do_run(), run_migrations_offline(), run_migrations_online(), _url()

### Community 117 - "list_plans"
Cohesion: 0.25
Nodes (4): list_plans(), PlanOut, _price_live(), public_plans()

### Community 118 - "Conflict"
Cohesion: 0.29
Nodes (3): Conflict, create_plan(), plan_by_code()

### Community 119 - "KingKong VPN — notes for AI assistants"
Cohesion: 0.33
Nodes (5): Checks (run what you touched), Find your way with the code graph (do this first), KingKong VPN — notes for AI assistants, Layout, Rules that must not break

## Knowledge Gaps
- **5 isolated node(s):** `globalvpn-backend`, `globalvpn-bot`, `ADR-0003`, `RFC-7748`, `DEBIAN_FRONTEND`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 723 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `utcnow()` connect `games/service.py` to `vpn/service.py`, `sqlalchemy`, `models/__init__.py`, `Principal`, `account.py`, `AuthService`, `subscriptions/service.py`, `admin/games.py`, `AppContext`, `routes.py`, `test_payments.py`, `test_telegram_vpn.py`, `payments/service.py`, `test_games.py`, `AppContext`, `utcnow`, `payments.py`, `Any`, `_admin_user_out`, `vpn/service.py`, `room_updates`, `os`, `list_plans`, `Conflict`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Are the 95 inferred relationships involving `AppContext` (e.g. with `get_ctx()` and `principal_from_token()`) actually correct?**
  _`AppContext` has 95 INFERRED edges - model-reasoned connections that need verification._
- **What connects `globalvpn-backend`, `globalvpn-bot`, `ADR-0003` to the rest of the system?**
  _5 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `new_user` be split into smaller, more focused modules?**
  _Cohesion score 0.062456140350877196 - nodes in this community are weakly interconnected._
- **Why does `AppContext` connect `AppContext` to `new_user`, `vpn/service.py`, `pytest`, `sqlalchemy`, `Settings`, `AuthService`, `games/service.py`, `post`, `subscriptions/service.py`, `v1/games.py`, `admin/games.py`, `tasks.py`, `test_platform.py`, `TokenService`, `app/main.py`, `test_payments.py`, `test_telegram_vpn.py`, `payments/service.py`, `test_games.py`, `AppContext`, `utcnow`, `notifications/telegram.py`, `CryptoBotClient`, `backend/tests/conftest.py`, `vpn/service.py`, `send_notices`, `room_updates`, `os`, `asyncio`, `ConfigError`, `passwords.py`, `test_devices.py`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Are the 24 inferred relationships involving `Settings` (e.g. with `AppContext` and `make_engine()`) actually correct?**
  _`Settings` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Should `vpn/service.py` be split into smaller, more focused modules?**
  _Cohesion score 0.0784313725490196 - nodes in this community are weakly interconnected._