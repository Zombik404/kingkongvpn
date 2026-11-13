# Graph Report - global-vpn  (2026-11-13)

## Corpus Check
- 201 files · ~176,453 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 22 file(s) not represented in the graph (top: (none) 9, .css 4, .lock 3)

## Summary
- 2955 nodes · 10038 edges · 125 communities (107 shown, 18 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 698 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `4a65a24a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_auth_api.py
- vpn/service.py
- subscriptions/service.py
- blackjack.py
- numpy
- typing
- models/__init__.py
- Principal
- Settings
- account.py
- User
- utcnow
- post
- h
- admin/progress.py
- mock.js
- admin/games.py
- ci.yml
- tasks.py
- AppContext
- test_platform.py
- NotAuthenticated
- backend/tests/conftest.py
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
- admin/vpn.py
- admin-panel/demo/mock.js
- notifications/telegram.py
- CryptoBotClient
- payments.py
- games/progress.py
- wallet.py
- AppError
- initGames
- referrals.py
- test_agent_loop.py
- package.json
- helpers.py
- worker
- Project Status
- services
- 3. Architectural decisions (ADR summary)
- Implementation Roadmap
- reconcile.py
- options
- test_progress.py
- README.md
- boards.py
- test_allocator.py
- _admin_user_out
- Запуск тестовой версии в Telegram
- vpn/service.py
- devices.py
- staff
- redis
- redis
- install.sh
- redis
- test_admin_vpn.py
- ip_prefix
- x-backend-common
- room_updates
- backend
- beat
- bot
- migrate
- postgres
- Backend API (v1)
- admin-panel/package.json
- context
- caddy
- postgres
- x-app
- Endpoints
- Project Architecture
- panel.py
- path
- healthcheck
- tasks.py
- backend
- redis
- test_admin_panel.py
- .__init__
- Security and user data
- beat
- migrate
- passwords.py
- check-env.sh
- views.py
- backup.sh
- docker-user.sh
- 0015-backend-core-decisions.md
- 0016-crypto-payments-cryptobot.md
- 0017-telegram-test-deployment.md
- 0018-vpnhub-traffic-referrals.md
- globalvpn-backend
- globalvpn-bot
- test_devices.py
- run
- run
- catalog.py
- with
- KingKong VPN — notes for AI assistants
- backend
- ref_esbuild
- postgres
- jobs
- ADR-021: Blackjack progression — XP, levels, achievements, daily challenges, boards, seasons

## God Nodes (most connected - your core abstractions)
1. `utcnow()` - 147 edges
2. `AppContext` - 136 edges
3. `new_user()` - 99 edges
4. `Settings` - 79 edges
5. `post()` - 64 edges
6. `User` - 57 edges
7. `AuthService` - 57 edges
8. `Base` - 55 edges
9. `AppError` - 54 edges
10. `ActorType` - 53 edges

## Surprising Connections (you probably didn't know these)
- `What we keep, and what we don't` --references--> `audit_logs()`  [INFERRED]
  documentation/SECURITY_PRIVACY.md → backend/app/api/v1/admin/routes.py
- `Decisions` --references--> `record_round()`  [INFERRED]
  documentation/adr/0021-blackjack-progression.md → backend/app/games/progress.py
- `Architecture` --references--> `room_view()`  [INFERRED]
  documentation/GAMES_BLACKJACK.md → backend/app/games/service.py
- `ADR-008 — Payments: one entitlement model, several stores` --references--> `Subscription`  [INFERRED]
  documentation/PROJECT_ARCHITECTURE.md → backend/app/models/billing.py
- `Billing` --references--> `device_limit()`  [INFERRED]
  documentation/DATABASE_SCHEMA.md → backend/app/services/devices.py

## Import Cycles
- None detected.

## Communities (125 total, 18 thin omitted)

### Community 0 - "test_auth_api.py"
Cohesion: 0.23
Nodes (19): login(), register_verified(), test_access_token_validation(), test_change_password_keeps_current_session(), test_expired_verification_token(), test_login_rate_limit_per_account(), test_login_success_and_me(), test_login_wrong_password_and_unknown_email_look_the_same() (+11 more)

### Community 1 - "vpn/service.py"
Cohesion: 0.11
Nodes (15): connect(), ConnectIn, ConnectOut, desired_state(), heartbeat(), HeartbeatIn, list_locations(), LocationOut (+7 more)

### Community 2 - "subscriptions/service.py"
Cohesion: 0.07
Nodes (49): Subscription, SubscriptionStatus, get_value(), Entitlement, entitlement(), get_live(), grant_days(), has_access_to_purchase() (+41 more)

### Community 3 - "blackjack.py"
Cohesion: 0.09
Nodes (40): act(), _advance(), _after_peek(), allowed_actions(), card_value(), _dealer_natural(), _dealer_play(), decide_insurance() (+32 more)

### Community 4 - "numpy"
Cohesion: 0.06
Nodes (38): purge_deleted_users(), test_delete_account(), test_export(), test_update_locale(), bezier(), blur(), leaf_tile(), noise() (+30 more)

### Community 5 - "typing"
Cohesion: 0.11
Nodes (7): make_engine(), make_sessionmaker(), session_scope(), CeleryTelegramDispatcher, make_telegram_dispatcher(), NullTelegramDispatcher, TelegramDispatcher

### Community 6 - "models/__init__.py"
Cohesion: 0.10
Nodes (35): Base, Timestamps, UUIDPk, Campaign, FamilyMember, PaymentEvent, Plan, PlanPrice (+27 more)

### Community 7 - "Principal"
Cohesion: 0.13
Nodes (26): require(), _admin_user_out(), _audit(), audit_logs(), create_plan(), create_price(), create_promo(), _get_plan() (+18 more)

### Community 8 - "Settings"
Cohesion: 0.05
Nodes (17): ConfigError, Settings, FieldCipher, _load_keys(), _do_run(), run_migrations_offline(), run_migrations_online(), _url() (+9 more)

### Community 9 - "account.py"
Cohesion: 0.11
Nodes (25): cancel(), claim_referral(), delete_me(), export_me(), get_subscription(), list_sessions(), me(), my_referrals() (+17 more)

### Community 10 - "User"
Cohesion: 0.18
Nodes (6): ActionTokenPurpose, User, ClientInfo, record(), AuthService, _normalize_email()

### Community 11 - "utcnow"
Cohesion: 0.05
Nodes (90): action(), ActionIn, bet(), BetIn, create_room(), fairness(), get_room(), get_wallet() (+82 more)

### Community 12 - "post"
Cohesion: 0.15
Nodes (33): login(), logout(), logout_all(), mfa_verify(), _pair_out(), password_change(), password_reset_confirm(), password_reset_request() (+25 more)

### Community 13 - "h"
Cohesion: 0.09
Nodes (89): api(), ApiError, listeners, logout(), message(), raw(), refresh(), session (+81 more)

### Community 14 - "admin/progress.py"
Cohesion: 0.10
Nodes (31): _ach_out(), AchievementIn, AchievementPatch, _audit(), _ch_out(), ChallengeIn, ChallengePatch, create_achievement() (+23 more)

### Community 15 - "mock.js"
Cohesion: 0.07
Nodes (33): addDays(), backend(), device(), el(), fail(), friendPaid(), iso(), json() (+25 more)

### Community 16 - "admin/games.py"
Cohesion: 0.16
Nodes (16): adjust_bonus(), BonusAdjustIn, close_room(), events(), ledger(), overview(), pause_room(), players() (+8 more)

### Community 17 - "ci.yml"
Cohesion: 0.18
Nodes (10): concurrency, cancel-in-progress, group, name, on, pull_request, push, permissions (+2 more)

### Community 18 - "tasks.py"
Cohesion: 0.12
Nodes (15): CeleryDispatcher, EmailDispatcher, EmailJob, make_dispatcher(), MemoryDispatcher, render(), RenderedEmail, send_smtp() (+7 more)

### Community 19 - "AppContext"
Cohesion: 0.18
Nodes (19): bootstrap_catalog(), create_invites(), create_staff(), grant_role(), main(), node_register(), seed_dev(), set_price() (+11 more)

### Community 20 - "test_platform.py"
Cohesion: 0.07
Nodes (18): catalog(), _lookup(), negotiate(), _SafeDict, t(), generate(), main(), scrub() (+10 more)

### Community 21 - "NotAuthenticated"
Cohesion: 0.12
Nodes (9): NotAuthenticated, _secret(), sign_init_data(), TelegramUser, validate_init_data(), AccessClaims, MfaClaims, TokenService (+1 more)

### Community 22 - "backend/tests/conftest.py"
Cohesion: 0.08
Nodes (16): ws(), pump(), create_app(), lifespan(), __getattr__(), alembic_config(), client(), ctx() (+8 more)

### Community 23 - "routes.py"
Cohesion: 0.11
Nodes (28): AdminRolesIn, AdminUserOut, AdminUserStatusIn, AuditLogOut, DeleteAccountIn, DeviceIn, DeviceListOut, DeviceRenameIn (+20 more)

### Community 24 - "sqlalchemy"
Cohesion: 0.09
Nodes (21): achievement_rows(), challenge_rows(), seed(), downgrade(), upgrade(), downgrade(), _provider_check(), upgrade() (+13 more)

### Community 25 - "test_payments.py"
Cohesion: 0.07
Nodes (59): PromoCode, verify_signature(), _def(), get_all(), InvalidSetting, set_value(), SettingDef, purge_old_usage() (+51 more)

### Community 26 - "__main__.py"
Cohesion: 0.21
Nodes (5): ControlPlane, ControlPlaneError, parse_desired(), DesiredPeer, test_parse_desired_rejects_garbage()

### Community 27 - "bot/main.py"
Cohesion: 0.14
Nodes (18): BotConfig, build_dispatcher(), on_games(), on_help(), on_other(), on_start(), configure(), lang_of() (+10 more)

### Community 28 - "test_reconcile.py"
Cohesion: 0.28
Nodes (18): DesiredState, make_plan(), MassRemovalRefused, FakeDriver, key(), nets(), peer(), test_apply_continues_after_failure_and_reports_it() (+10 more)

### Community 29 - "test_telegram_vpn.py"
Cohesion: 0.19
Nodes (24): release_revoked_addresses(), test_api_security_headers(), test_device_churn_is_limited_and_old_addresses_come_back(), test_export_covers_everything(), test_progression_data_is_exported_and_scrubbed_on_deletion(), test_telegram_account_can_be_deleted_with_fresh_init_data(), _uid(), beat() (+16 more)

### Community 30 - "payments/service.py"
Cohesion: 0.09
Nodes (25): Payment, AuditResult, DevicePlatform, NotificationChannel, NotificationStatus, PaymentKind, PaymentStatus, PeriodUnit (+17 more)

### Community 31 - "base64"
Cohesion: 0.14
Nodes (10): CliWgDriver, InterfaceState, is_valid_public_key(), _parse_allowed_ips(), parse_dump(), PeerState, WgError, test_public_key_helper() (+2 more)

### Community 32 - "app.js"
Cohesion: 0.05
Nodes (99): calls, ADR-0003, RFC-7748, addDeviceForm(), api(), applyTheme(), APPS, ask() (+91 more)

### Community 33 - "test_games.py"
Cohesion: 0.19
Nodes (35): balance(), bet(), chip_round(), chips(), ctx_session(), do(), expire(), give() (+27 more)

### Community 34 - "admin/vpn.py"
Cohesion: 0.15
Nodes (23): _audit(), create_location(), create_server(), _get_location(), get_server(), _get_server(), list_locations(), list_servers() (+15 more)

### Community 35 - "admin-panel/demo/mock.js"
Cohesion: 0.09
Nodes (34): AUDIT, audit(), bar, days(), fail(), GAMEPROFILES, iso(), json() (+26 more)

### Community 36 - "notifications/telegram.py"
Cohesion: 0.16
Nodes (8): MemoryTelegramDispatcher, send_sync(), TelegramJob, TelegramSendError, send_telegram(), test_telegram_send_sync_statuses(), run(), handler()

### Community 37 - "CryptoBotClient"
Cohesion: 0.17
Nodes (10): cryptobot_check(), CryptoBotClient, Invoice, minor_to_amount(), parse_webhook(), _ts(), test_amounts_and_periods(), test_asset_resolution() (+2 more)

### Community 38 - "payments.py"
Cohesion: 0.15
Nodes (8): checkout(), CheckoutIn, cryptobot_webhook(), get_payment(), InvalidWebhook, list_payments(), _out(), PaymentOut

### Community 39 - "games/progress.py"
Cohesion: 0.15
Nodes (21): active_seasons(), add_xp(), _challenge_step(), check_achievements(), display_title(), game_day(), grant_reward(), level_for() (+13 more)

### Community 40 - "wallet.py"
Cohesion: 0.29
Nodes (4): get_wallet(), InsufficientBonus, move(), redeem()

### Community 41 - "AppError"
Cohesion: 0.13
Nodes (15): AppError, InvalidCredentials, InvalidToken, RateLimited, ServiceUnavailable, normalize(), AuthSession, RefreshToken (+7 more)

### Community 42 - "initGames"
Cohesion: 0.05
Nodes (76): createGames(), act(), actions(), deal(), finish(), nextHand(), publicRound(), view() (+68 more)

### Community 43 - "referrals.py"
Cohesion: 0.12
Nodes (14): uuid7(), claim(), ensure_code(), _grant_bonus_days(), Granted, _has_paid(), InvalidReferral, invitee_discount() (+6 more)

### Community 44 - "test_agent_loop.py"
Cohesion: 0.16
Nodes (12): AgentConfig, Agent, main(), backend(), Backend, cfg(), test_backend_down_keeps_peers(), test_bad_token_and_unsafe_state() (+4 more)

### Community 45 - "package.json"
Cohesion: 0.16
Nodes (14): description, devDependencies, esbuild@0.25.10, @noble/curves@1.9.7, qrcode-generator@1.4.4, esbuild, qrcode-generator, name (+6 more)

### Community 46 - "helpers.py"
Cohesion: 0.16
Nodes (13): b32(), code_at(), current_counter(), new_secret(), provisioning_uri(), verify(), TotpSetup, enable_mfa() (+5 more)

### Community 47 - "worker"
Cohesion: 0.12
Nodes (16): name, services, worker, volumes, caddyconfig, caddydata, pgdata, redisdata (+8 more)

### Community 48 - "Project Status"
Cohesion: 0.10
Nodes (20): Added after Phase 2: crypto payments (@CryptoBot), Admin panel and data protection (2026-11-13) — ADR-020, Blackjack progression (2026-11-13, done) — ADR-021, owner's brief "Progression, achievements & leaderboards", Completed in Phase 2, Environment, How to run the backend locally, Jungle Kong Blackjack (2026-11-13) — ADR-019, documentation/GAMES_BLACKJACK.md, KingKong VPN rebrand (2026-11-13) — ADR-018 §5–6 (+12 more)

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
Cohesion: 0.15
Nodes (9): apply(), ApplyResult, DesiredStateError, parse_pools(), Plan, reconcile(), validate(), WgDriver (+1 more)

### Community 53 - "options"
Cohesion: 0.18
Nodes (15): logging, logging, driver, options, logging, max-file, max-size, command (+7 more)

### Community 54 - "test_progress.py"
Cohesion: 0.25
Nodes (16): only_challenges(), play(), _players(), profile_of(), rig(), _season(), test_admin_progress_exclusion_catalogue_and_seasons(), test_boards_order_ties_min_rounds_my_rank_and_search() (+8 more)

### Community 55 - "README.md"
Cohesion: 0.17
Nodes (6): Credentials the platform generates itself (no action needed), External Accounts, Credentials and Approvals, Development quick start, global-vpn, Ground rules, Repository layout

### Community 56 - "boards.py"
Cohesion: 0.20
Nodes (12): board(), BoardError, bounds(), current(), due(), ensure_current(), finalize(), _ranked() (+4 more)

### Community 57 - "test_allocator.py"
Cohesion: 0.23
Nodes (11): AddressPool, insert_with_address(), _lowest_free_index(), _next_sequence_index(), PoolExhausted, _allocate(), test_concurrent_gap_allocation_never_duplicates(), test_pool_mapping() (+3 more)

### Community 58 - "_admin_user_out"
Cohesion: 0.32
Nodes (3): delete_account(), export_data(), _iso()

### Community 59 - "Запуск тестовой версии в Telegram"
Cohesion: 0.11
Nodes (16): Админ-панель KingKong VPN, Вход, Разделы, Роли, Если что-то не работает, Запуск тестовой версии в Telegram, Полезные команды (на сервере), Чего в тестовой версии нет (+8 more)

### Community 60 - "vpn/service.py"
Cohesion: 0.13
Nodes (18): AssignmentState, Server, authenticate_node(), connect(), ConnectInfo, desired_state(), _endpoint(), _fresh() (+10 more)

### Community 61 - "devices.py"
Cohesion: 0.27
Nodes (14): list_devices(), violated_constraint(), DeviceStatus, Device, active_count(), device_limit(), device_out(), DeviceLimitReached (+6 more)

### Community 62 - "staff"
Cohesion: 0.29
Nodes (10): set_roles(), staff(), test_permission_matrix(), test_plan_and_price_management(), test_promo_admin(), test_role_change_signs_staff_out(), test_search_and_grant(), test_settings_validation_and_audit() (+2 more)

### Community 63 - "redis"
Cohesion: 0.24
Nodes (11): depends_on, depends_on, migrate, postgres, redis, condition, depends_on, condition (+3 more)

### Community 64 - "redis"
Cohesion: 0.53
Nodes (6): interval, retries, test, timeout, healthcheck, healthcheck

### Community 65 - "install.sh"
Cohesion: 0.35
Nodes (9): ask(), cli(), DEBIAN_FRONTEND, die(), env_get(), keep_or(), say(), install.sh script (+1 more)

### Community 66 - "redis"
Cohesion: 0.24
Nodes (11): depends_on, depends_on, migrate, postgres, redis, condition, depends_on, condition (+3 more)

### Community 67 - "test_admin_vpn.py"
Cohesion: 0.34
Nodes (9): release_idle_peers(), _location(), _ops(), _server(), settings(), test_drain_disable_and_rotate(), test_idle_peers_are_released_only_when_switched_on(), test_permissions() (+1 more)

### Community 68 - "ip_prefix"
Cohesion: 0.22
Nodes (8): ip_prefix(), test_ip_prefix(), Accounts and auth, Billing, Database schema, Operations, Retention (as implemented), VPN

### Community 69 - "x-backend-common"
Cohesion: 0.29
Nodes (10): build, build, context, target, build, build, x-backend-common, build (+2 more)

### Community 70 - "room_updates"
Cohesion: 0.15
Nodes (6): get_client(), get_ctx(), get_db(), get_principal(), MfaRequiredForAdmin, principal_from_token()

### Community 71 - "backend"
Cohesion: 0.22
Nodes (9): cap_drop, env_file, ports, read_only, restart, security_opt, tmpfs, volumes (+1 more)

### Community 72 - "beat"
Cohesion: 0.22
Nodes (9): cap_drop, command, env_file, read_only, restart, security_opt, tmpfs, volumes (+1 more)

### Community 73 - "bot"
Cohesion: 0.20
Nodes (10): cap_drop, environment, logging, read_only, restart, security_opt, APP_NAME, MINIAPP_URL (+2 more)

### Community 74 - "migrate"
Cohesion: 0.22
Nodes (9): cap_drop, command, env_file, read_only, restart, security_opt, tmpfs, volumes (+1 more)

### Community 75 - "postgres"
Cohesion: 0.22
Nodes (9): POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER, environment, image, ports, restart, volumes (+1 more)

### Community 76 - "Backend API (v1)"
Cohesion: 0.18
Nodes (11): Admin panel helpers, Backend API (v1), Conventions, Global settings (`/admin/settings`), Health, Locations and VPN servers (`/admin/vpn/*`), Payments (crypto via @CryptoBot), Staff API and permissions (+3 more)

### Community 77 - "admin-panel/package.json"
Cohesion: 0.18
Nodes (12): description, devDependencies, esbuild@0.25.10, qrcode-generator@1.4.4, esbuild, qrcode-generator, name, private (+4 more)

### Community 78 - "context"
Cohesion: 0.39
Nodes (8): build, build, build, context, target, build, build, build

### Community 79 - "caddy"
Cohesion: 0.20
Nodes (10): depends_on, environment, image, logging, ports, restart, volumes, ADMIN_ALLOWED_IPS (+2 more)

### Community 80 - "postgres"
Cohesion: 0.22
Nodes (9): POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER, environment, image, logging, restart, volumes (+1 more)

### Community 81 - "x-app"
Cohesion: 0.25
Nodes (8): x-app, cap_drop, env_file, read_only, restart, security_opt, tmpfs, volumes

### Community 82 - "Endpoints"
Cohesion: 0.25
Nodes (8): account, admin, auth, devices, Endpoints, plans, promo, subscription

### Community 83 - "Project Architecture"
Cohesion: 0.25
Nodes (8): 1. System overview, 2. Components, 4. Core data model (outline), 5. Key flows, 6. Environments, 7. Security baseline (expanded in `SECURITY_POLICY.md`), 8. Scalability envelope (initial targets), Project Architecture

### Community 84 - "panel.py"
Cohesion: 0.12
Nodes (8): dependency(), admin_me(), _days(), list_payments(), overview(), Role, UserStatus, permissions_for()

### Community 85 - "path"
Cohesion: 0.48
Nodes (7): env_file, env_file, path, required, env_file, env_file, env_file

### Community 86 - "healthcheck"
Cohesion: 0.57
Nodes (7): healthcheck, interval, retries, test, timeout, healthcheck, healthcheck

### Community 87 - "tasks.py"
Cohesion: 0.16
Nodes (11): cleanup_tokens(), cleanup_tokens_task(), game_seasons_task(), game_timers_task(), poll_payments_task(), process_due_task(), purge_deleted_task(), release_idle_peers_task() (+3 more)

### Community 88 - "backend"
Cohesion: 0.33
Nodes (6): command, ports, profiles, restart, volumes, backend

### Community 89 - "redis"
Cohesion: 0.33
Nodes (6): command, image, ports, restart, volumes, redis

### Community 90 - "test_admin_panel.py"
Cohesion: 0.29
Nodes (4): _create_staff(), test_create_staff_login_and_mfa_gate(), test_overview_payments_and_search(), test_staff_without_mfa_is_refused_everywhere()

### Community 91 - ".__init__"
Cohesion: 0.60
Nodes (4): _auth(), do_GET(), do_POST(), _json()

### Community 92 - "Security and user data"
Cohesion: 0.18
Nodes (9): ADR-020: Admin panel (Phase 9) and user-data protection, Consequences, Context, Decisions, For the owner, Protections in place, Review of 2026-11-13: found and fixed, Security and user data (+1 more)

### Community 93 - "beat"
Cohesion: 0.40
Nodes (5): command, profiles, restart, volumes, beat

### Community 94 - "migrate"
Cohesion: 0.40
Nodes (5): command, profiles, restart, volumes, migrate

### Community 95 - "passwords.py"
Cohesion: 0.19
Nodes (3): PasswordService, VerifyResult, WeakPassword

### Community 97 - "views.py"
Cohesion: 0.28
Nodes (8): achievements(), ProfileError, ranks(), rewards(), seasons(), set_looks(), titles_of(), xp_history()

### Community 114 - "test_devices.py"
Cohesion: 0.47
Nodes (9): new_user(), give_plan(), test_concurrent_registrations_respect_limit(), test_device_limit_without_and_with_plan(), test_duplicate_key_rejected_even_across_users(), test_invalid_public_keys_rejected(), test_register_device_allocates_addresses(), test_rename_revoke_and_isolation() (+1 more)

### Community 115 - "run"
Cohesion: 0.29
Nodes (10): miniapp, runs-on, steps, timeout-minutes, steps, steps, name, run (+2 more)

### Community 116 - "run"
Cohesion: 0.22
Nodes (9): defaults, defaults, run, telegram-bot, defaults, working-directory, defaults, runs-on (+1 more)

### Community 117 - "catalog.py"
Cohesion: 0.11
Nodes (17): list_plans(), PromoKind, PlanOut, PriceOut, RateLimiter, _already_redeemed(), apply_discount(), create_plan() (+9 more)

### Community 118 - "with"
Cohesion: 0.22
Nodes (9): runs-on, steps, timeout-minutes, admin-panel, with, cache, cache-dependency-path, node-version (+1 more)

### Community 119 - "KingKong VPN — notes for AI assistants"
Cohesion: 0.33
Nodes (5): Checks (run what you touched), Find your way with the code graph (do this first), KingKong VPN — notes for AI assistants, Layout, Rules that must not break

### Community 120 - "backend"
Cohesion: 0.22
Nodes (9): runs-on, services, steps, timeout-minutes, backend, image, options, ports (+1 more)

### Community 122 - "postgres"
Cohesion: 0.25
Nodes (8): POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER, env, image, options, ports, postgres

### Community 123 - "jobs"
Cohesion: 0.33
Nodes (6): jobs, node-agent-and-scripts, secret-scan, runs-on, timeout-minutes, runs-on

### Community 124 - "ADR-021: Blackjack progression — XP, levels, achievements, daily challenges, boards, seasons"
Cohesion: 0.40
Nodes (4): ADR-021: Blackjack progression — XP, levels, achievements, daily challenges, boards, seasons, Consequences, Context, Decisions

## Knowledge Gaps
- **7 isolated node(s):** `ADR-0021`, `globalvpn-backend`, `DEBIAN_FRONTEND`, `ADR-0021`, `ADR-0003` (+2 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 872 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **18 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `utcnow()` connect `utcnow` to `subscriptions/service.py`, `numpy`, `models/__init__.py`, `Principal`, `account.py`, `User`, `admin/progress.py`, `admin/games.py`, `AppContext`, `NotAuthenticated`, `routes.py`, `test_payments.py`, `test_telegram_vpn.py`, `payments/service.py`, `test_games.py`, `admin/vpn.py`, `payments.py`, `games/progress.py`, `AppError`, `test_progress.py`, `boards.py`, `_admin_user_out`, `vpn/service.py`, `devices.py`, `test_admin_vpn.py`, `room_updates`, `panel.py`, `tasks.py`, `test_admin_panel.py`, `views.py`, `catalog.py`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Are the 104 inferred relationships involving `AppContext` (e.g. with `get_ctx()` and `principal_from_token()`) actually correct?**
  _`AppContext` has 104 INFERRED edges - model-reasoned connections that need verification._
- **What connects `ADR-0021`, `globalvpn-backend`, `DEBIAN_FRONTEND` to the rest of the system?**
  _7 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `vpn/service.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10960960960960961 - nodes in this community are weakly interconnected._
- **Why does `AppContext` connect `AppContext` to `test_auth_api.py`, `subscriptions/service.py`, `numpy`, `typing`, `models/__init__.py`, `Settings`, `User`, `utcnow`, `tasks.py`, `test_platform.py`, `NotAuthenticated`, `backend/tests/conftest.py`, `test_payments.py`, `test_telegram_vpn.py`, `payments/service.py`, `test_games.py`, `CryptoBotClient`, `AppError`, `helpers.py`, `test_progress.py`, `boards.py`, `test_allocator.py`, `_admin_user_out`, `vpn/service.py`, `devices.py`, `test_admin_vpn.py`, `room_updates`, `tasks.py`, `passwords.py`, `test_devices.py`, `catalog.py`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Are the 28 inferred relationships involving `Settings` (e.g. with `AppContext` and `make_engine()`) actually correct?**
  _`Settings` has 28 INFERRED edges - model-reasoned connections that need verification._
- **Should `subscriptions/service.py` be split into smaller, more focused modules?**
  _Cohesion score 0.0721120984278879 - nodes in this community are weakly interconnected._