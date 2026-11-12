# Implementation Roadmap

Every phase ends with: tests run and reported, docs updated, `PROJECT_STATUS.md` updated, commit tagged `phase-N`.
"Exit criteria" are what must be **demonstrated**, not merely written. Where a phase needs something this
development environment can't provide (a real VPS, a Mac, store accounts), that is listed under **Needs**.

Legend for where work can happen: **[S]** sandbox/CI, **[V]** real VPS (staging), **[M]** a Mac with Xcode, **[W]** a Windows machine, **[A]** Android device/emulator, **[X]** external account/approval.

---

## Phase 1 — Project initialization  ✅ (this commit)
- Environment inspection, repo layout, Git, architecture + ADR summary, roadmap, external requirements, status tracker, `.env.example`, dev Compose, backend Dockerfile, Makefile.
- **Exit:** compose file validates; no secrets in repo; docs reviewed.

## Phase 2 — Database and backend core  [S]  ✅ (2026-11-12)
1. `backend/pyproject.toml` with pinned deps; ruff, mypy (strict on `app/`), pytest + pytest-asyncio + httpx.
2. Settings via `pydantic-settings` (fails fast on missing required secrets outside `development`).
3. SQLAlchemy 2 async models for all tables in Architecture §4; Alembic initial migration; UUIDv7 keys.
4. Auth module: register, verify email, login, refresh rotation with reuse detection, logout, logout-all, password reset, rate limiting (Redis), Argon2id.
5. Users: profile, locale, delete-account (GDPR-style export/delete endpoints designed, legal review later).
6. Devices: register (public key validation: 32-byte base64 X25519), list, rename, revoke, device limit from plan/settings, tunnel IP allocator (concurrency-safe, unique constraints).
7. Plans/prices/settings CRUD (admin), subscriptions state machine (trial, activate, renew, cancel-at-period-end, grace, expire, refund), promo codes.
8. RBAC dependencies; audit log writer with scrubbing.
9. Celery app, beat schedule: expiry, reminders.
10. Email service (SMTP; mailpit in dev) with i18n templates.
11. OpenAPI export to `shared/api-contracts/`; `BACKEND_API.md`, `DATABASE_SCHEMA.md`.
- **Tests:** unit (state machine, allocator, token rotation), API (auth flows, permissions matrix, device limits), migration up/down on real Postgres.
- **Exit:** ≥ 85 % line coverage on `auth`, `subscriptions`, `devices`; CI green; migrations reversible.
- **Done:** all items above; results in `PROJECT_STATUS.md`. Deferred by decision: web cookie refresh mode → Phase 8, WebAuthn → Phase 9 (ADR-015).

## Phase 3 — VPN infrastructure  [S]+[V]
1. Ansible roles: `base` (unattended-upgrades, SSH hardening, fail2ban, time sync), `wireguard`, `nftables` (ADR-005), `unbound` (no query logging, DNSSEC), `node_exporter`, `node_agent`.
2. Node enrollment: one-time token → agent CSR → backend-signed client cert (internal CA via `cryptography`, CA key in secret store).
3. `node-agent`: desired-state long-poll, diff/apply via `wg set`, full reconcile, heartbeat, counters; runs as root-limited systemd unit with `CapabilityBoundingSet=CAP_NET_ADMIN`.
4. Terraform modules for at least one provider (Hetzner Cloud is cheap and covers DE/FI; second provider for countries Hetzner lacks — e.g. Vultr or similar) — **plans only; apply requires authorization**.
- **Tests:** agent unit tests with fake `wg` driver [S]; network-namespace integration test (two netns + WireGuard) where kernel allows [S/V]; Molecule/ansible-lint [S]; real client → node handshake, DNS/IPv6 leak checks [V].
- **Exit:** a real staging node accepts a real client; revocation removes access within 5 s; client-to-client traffic blocked; no DNS/IPv6 leak.
- **Needs:** 1 staging VPS + SSH key; DNS name for the node (optional).

## Phase 4 — VPN management engine  [S]+[V]
Server registry API, selection (ADR-006), on-demand assignment, idle peer GC, capacity monitoring, health-based draining, failure handling (node down → assignments marked, clients told to reconnect elsewhere), auto-scaling policy engine with approval workflow and spend limit.
- **Exit:** kill a staging node → admin alerted, location marked degraded, new connects routed elsewhere.

## Phase 5 — Telegram bot  [S]+[X]
aiogram 3 webhook app; service-credential client for the backend; i18n; onboarding; link/unlink with one-time codes; country list from live registry; deep-link "Connect" (no configs/keys in chat); subscription view/renew/cancel; Stars invoices; notification consumer; admin commands gated by backend roles; FSM in Redis.
- **Tests:** handler unit tests with aiogram test utilities + mocked backend; authorization tests for every admin command.
- **Needs:** bot token from @BotFather (staging + prod bots).

## Phase 6 — Mobile apps  [A]+[M]+[X]
Flutter app (Riverpod, go_router, dio generated client, flutter_secure_storage, local_auth). Android: Kotlin plugin over `com.wireguard.android:tunnel`, foreground service, always-on detection. iOS: Swift plugin + Packet Tunnel extension with WireGuardKit, App Group keychain. Accurate state machine (`disconnected → connecting → handshaking → connected → reconnecting`). IAP via `in_app_purchase` with server verification.
- **Exit:** real tunnel on physical Android and iOS devices, leak tests pass, network switch (Wi-Fi↔cellular) recovers.
- **Needs:** Flutter SDK, Android Studio, Mac + Xcode, Apple Developer **Organization** account (VPN apps require an organization account), Google Play Console.

## Phase 7 — Desktop apps  [W]+[M]+[X]
Flutter desktop shell. Windows: privileged service wrapping `tunnel.dll`/`wireguard.dll` (wireguard-windows embeddable service), named-pipe IPC, MSIX/MSI installer, code signing. macOS: system/app Network Extension, Developer ID signing + notarization. Auto-update (Sparkle on macOS, WinSparkle/MSIX on Windows).
- **Needs:** Windows machine, Windows code-signing certificate, Mac + Developer ID.

## Phase 8 — Web app  [S]
Next.js + Tailwind; pages per spec; i18n routing; account dashboard; browser-side config generator (ADR-003); SEO (metadata, sitemap, hreflang, structured data); Lighthouse ≥ 90; Playwright e2e.
- **Needs:** domain + DNS (for production only).

## Phase 9 — Admin panel  [S]
Separate Next.js app; TOTP/WebAuthn; dashboard from real aggregates; users, servers, plans/prices, promo codes, payments (read-only + refund action), support inbox, analytics (growth, MRR, churn, conversion, utilisation), audit log viewer.

## Phase 10 — Payments  [S]+[X]
Stripe Checkout + Billing + Customer Portal, webhooks, refunds, reconciliation job; Apple App Store Server API + notifications; Google Play RTDN; Telegram Stars; PayPal optional. **Policy verification** per store and region documented in `PAYMENT_INTEGRATION.md`.
- **Needs:** Stripe account (business verification), Apple/Google merchant setup, tax decision (Stripe Tax / merchant-of-record).

## Phase 11 — Security & optimization  [S]+[V]
Threat model review, dependency + container scans, permission matrix test, DAST (OWASP ZAP) on staging, leak/kill-switch test matrix per platform, load tests (k6 for API; iperf3 + many-peer test for nodes), backup restore drill, privacy inventory verification (ADR-010).

## Phase 12 — Production launch  [V]+[X]
Production infra, domains, TLS, monitoring/alerts on-call, deploy pipeline with approvals, store submissions, legal docs prepared for lawyer review, final acceptance checklist (`PRODUCTION_CHECKLIST.md`).

---

## Suggested sequencing to save time
Phases 2 → 3 → 4 are the critical path. Phases 8 and 9 (web/admin) can run in parallel with 5 once Phase 2's API contract is stable. Store account approval (Apple organization enrolment needs a D-U-N-S number) takes weeks — **start it now** in parallel.
