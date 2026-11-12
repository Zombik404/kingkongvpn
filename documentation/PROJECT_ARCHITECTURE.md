# Project Architecture

Status: **Draft v1 (Phase 1)** — decisions here are binding until superseded by an ADR in `documentation/adr/`.
Working name: `global-vpn` (brand name not yet chosen — see open decisions in `PROJECT_STATUS.md`).

---

## 1. System overview

```
                         ┌──────────────────────────── Clients ────────────────────────────┐
                         │ Android (Flutter + VpnService)   iOS (Flutter + NEPacketTunnel)  │
                         │ Windows (Flutter + WireGuardNT)  macOS (Flutter + NetworkExt.)   │
                         │ Web app (Next.js)   Admin panel (Next.js)   Telegram bot (aiogram)│
                         └───────────────┬───────────────────────────────┬──────────────────┘
                                         │ HTTPS (REST /api/v1, WS)      │ Telegram webhook
                                         ▼                               ▼
   Stripe / Apple / Google ──webhooks──► ┌──────────────────────────────────────────────┐
   Telegram Stars                        │ Nginx (TLS, rate limits, security headers)    │
                                         └──────────────────┬───────────────────────────┘
                                                            ▼
                        ┌──────────────── Control plane (stateless, horizontally scalable) ─────────────┐
                        │ FastAPI backend  ──►  PostgreSQL (source of truth)                            │
                        │       │          ──►  Redis (rate limits, cache, Celery broker, pub/sub)      │
                        │       ▼                                                                        │
                        │ Celery workers + beat (expiry, renewals, reconciliation, notifications, emails)│
                        └───────────────────────────▲───────────────────────────────────────────────────┘
                                                    │ mTLS: agent pulls desired peer state,
                                                    │ pushes health + aggregate counters
                        ┌───────────────────────────┴──────── Data plane (one per VPN server) ──────────┐
                        │ Ubuntu LTS · WireGuard (kernel) · nftables (NAT, isolation, anti-leak)          │
                        │ unbound (local resolver) · node-agent (reconciler) · node_exporter              │
                        └───────────────────────────────────────────────────────────────────────────────┘
         Observability: Prometheus + Alertmanager · Grafana · Loki (+ Promtail/Alloy) · backups to object storage
```

**Principles**

1. **The backend is the only writer of business state.** Bot, apps, web and admin are API clients. The bot never touches the database.
2. **Control plane and data plane are separated.** A backend outage must not drop existing VPN tunnels; nodes keep their last-known peer set.
3. **Client private keys never leave the device that generated them.** The platform stores public keys only.
4. **Everything commercial is data, not code** — countries, servers, plans, prices, currencies, device limits, trial length, grace periods.
5. **No fabricated numbers.** Any metric shown to a user or admin (load, latency, availability, revenue) comes from a real measurement or is hidden.

---

## 2. Components

| Component | Tech | Responsibility | Directory |
|---|---|---|---|
| Backend API | Python 3.12+, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2 | Auth, users, devices, subscriptions, payments, server registry, peer assignment, support, admin, analytics | `backend/` |
| Background jobs | Celery + Redis broker, Celery beat | Expiry/revocation, renewal reminders, webhook post-processing, reconciliation, email/Telegram delivery, metric rollups | `backend/app/workers/` |
| Node agent | Python (stdlib + `pyroute2`/`wg` CLI), systemd service | Runs on each VPN server; reconciles WireGuard peers to backend's desired state; reports health and aggregate counters | `node-agent/` (added to the suggested layout — see ADR-002) |
| VPN infrastructure | WireGuard, nftables, unbound, Ansible, Terraform | Server hardening, provisioning, firewall, DNS, monitoring exporters | `vpn-infrastructure/` |
| Telegram bot | aiogram 3, webhook mode | Onboarding, account linking, plans, Stars payments, notifications, admin commands | `telegram-bot/` |
| Mobile app | Flutter; Kotlin (VpnService + wireguard-android `tunnel` lib); Swift (NEPacketTunnelProvider + WireGuardKit) | Android & iOS clients | `mobile-app/` |
| Desktop app | Flutter desktop; Windows: wireguard-nt via embeddable tunnel service; macOS: Network Extension + WireGuardKit | Windows & macOS clients | `desktop-app/` |
| Web app | Next.js (App Router), TypeScript, Tailwind | Marketing site, pricing, legal pages, account dashboard, browser-side config generator | `web-app/` |
| Admin panel | Next.js, TypeScript, Tailwind | Separate deployment on separate subdomain, admin-only | `admin-panel/` |
| Shared contracts | OpenAPI 3.1 (generated from FastAPI), JSON locale catalogs | Single source for TS and Dart API clients, shared message catalogs | `shared/` |
| Platform infra | Docker, Compose, Nginx, GitHub Actions, Prometheus, Grafana, Loki | Deployment, CI/CD, monitoring, backups | `infrastructure/`, `.github/` |

---

## 3. Architectural decisions (ADR summary)

Each decision gets a full ADR file in `documentation/adr/` when its phase starts. Summary:

### ADR-001 — Modular monolith backend, not microservices
One FastAPI service with strict internal modules (`auth`, `billing`, `vpn`, `support`, …) behind service interfaces, plus Celery workers from the same codebase. Stateless API instances scale horizontally behind Nginx; PostgreSQL scales vertically then with read replicas. Tens of thousands of users is well within this envelope; splitting into services later is possible along module boundaries. *Rejected:* microservices (operational cost with no benefit at this scale).

### ADR-002 — Pull-based node agent for VPN servers (control/data plane split)
Each VPN server runs `node-agent`, which authenticates to the backend with **mTLS** (per-node client certificate issued at provisioning) and:
- long-polls `GET /internal/v1/nodes/{id}/desired-state?since=<revision>` (returns immediately when the peer set changes; Redis pub/sub wakes the poll),
- applies the diff with `wg set` (add/remove peers) — never by rewriting and restarting the interface,
- runs a full reconcile every 60 s as a safety net,
- posts heartbeats: CPU, RAM, bandwidth, active peers (handshake < 3 min), interface counters.

*Why not push over SSH from the backend:* the backend would need root SSH to every node (high-value credential), pushes fail silently when nodes are unreachable, and reconciliation is harder. With pull, a compromised backend still cannot run arbitrary commands on nodes; the agent only accepts a constrained peer list. Ansible over SSH is used only for provisioning/upgrades by an operator or the CI deploy job.

### ADR-003 — Client-side key generation; no private keys on the platform
- **Apps (Android/iOS/Windows/macOS):** keypair generated on device via WireGuard's own implementation; private key in Android Keystore-wrapped storage / iOS Keychain (shared with the tunnel extension via App Group keychain access) / Windows DPAPI / macOS Keychain. Only the public key is sent to `POST /api/v1/devices`.
- **Users of the official WireGuard apps (no custom app, e.g. Linux/routers):** the web app generates the X25519 keypair **in the browser** (WebCrypto X25519, with an audited JS fallback such as `@noble/curves`), registers the public key, and renders the `.conf`/QR locally. The private key never touches our servers.
- **Telegram:** the bot never sends configs or keys. "Connect VPN" returns a one-time, short-lived (10 min), single-use deep link that opens the app or the web config page and is bound to the user's account.
- **Server keys:** generated on the node during provisioning; private key stays on the node (`/etc/wireguard`, mode 0600, root-only). Only the public key is registered.
- Consequence: we can't "resend" a lost config — the user generates a new device key (revoking the old one). This is intended.

### ADR-004 — One tunnel address per device, valid on any server
Each device gets a stable IPv4 from `10.64.0.0/10` (~4M addresses) and IPv6 from a ULA `/48`, allocated once at registration. Nodes NAT (IPv4 masquerade, IPv6 NAT66/masquerade) to their public addresses. Switching country therefore needs only a peer **assignment** on the target node, not readdressing.
Peers are **assigned on demand**: when a device requests a connection to a location, the backend picks a node (ADR-006), records the assignment, and the agent installs the peer within ~1–2 s. Idle assignments (no handshake for N hours, configurable) are removed so nodes don't accumulate every user's peer.
*Rejected:* push all peers to all nodes (O(users × nodes) and leaks the full user key set to every node).

### ADR-005 — Traffic isolation and anti-leak on nodes
nftables on every node:
- drop `wg0 → wg0` forwarding (clients can't reach each other),
- drop forwarding to RFC1918/ULA/link-local/metadata ranges (`169.254.169.254`, provider private networks),
- allow DNS from clients only to the node-local resolver (unbound) on the tunnel address; redirect/deny external DNS is a policy option,
- dual-stack: every node serves IPv6 or explicitly blocks it for tunnel clients so client IPv6 cannot bypass the tunnel (clients always route `::/0`),
- management ports (SSH, agent metrics) reachable only from an allowlisted admin/monitoring network.

### ADR-006 — Server selection
Inputs: location requested (or "fastest" chosen by the client from **its own** latency probes), plan entitlements (server tier), node status (`active` only), health freshness (heartbeat < 90 s), capacity (`active_peers / max_peers` and bandwidth utilisation). Pick the least-loaded eligible node in the location with a small random factor to avoid thundering herds. Latency shown in apps is measured by the client (ICMP/UDP probe to the node's public endpoint) — never computed server-side.

### ADR-007 — Authentication
- Passwords: **Argon2id** (`argon2-cffi`) with per-hash parameters stored in the hash string.
- Access token: JWT (EdDSA/Ed25519 signing, 15 min), contains `sub`, `sid`, `roles`, `ver`.
- Refresh token: opaque 256-bit random, stored **hashed**, **rotated on every use**, grouped in a session "family"; reuse of a rotated token revokes the whole family (theft detection).
- Web: refresh token in `HttpOnly; Secure; SameSite=Strict` cookie + CSRF double-submit token on cookie-authenticated mutations. Apps: refresh token in secure storage, bearer access token.
- Brute force: Redis sliding-window limits per IP and per account; progressive delay; account lock notification. Generic error messages (no account enumeration).
- Email verification and password reset: single-use, hashed, expiring tokens.
- Telegram: the bot authenticates to the backend with a **service credential**; the backend trusts `telegram_id` only from that channel or from a verified Telegram Login Widget/Mini App `initData` signature. Linking an existing account uses a short one-time code generated in the logged-in app/web and entered in the bot (or vice versa). Telegram is always optional.
- Admins: separate role set (`support`, `ops`, `finance`, `superadmin`), **mandatory TOTP/WebAuthn**, shorter sessions, separate admin origin, every mutation audit-logged.

### ADR-008 — Payments: one entitlement model, several stores
The `Subscription` (entitlement) is provider-agnostic; each provider writes to it only via verified server-side events.

| Channel | Provider | Verification |
|---|---|---|
| Website | Stripe Checkout (hosted) + Stripe Billing for recurring; PayPal later | Signed webhooks (`Stripe-Signature`), then re-fetch object from API |
| iOS app | Apple In-App Purchase (StoreKit 2) auto-renewable subscriptions | App Store Server API + App Store Server Notifications V2 (JWS verified against Apple root) |
| Android app | Google Play Billing subscriptions | Play Developer API purchase verification + Real-time Developer Notifications (Pub/Sub) |
| Telegram | Telegram Stars (XTR) for digital goods | `pre_checkout_query` + `successful_payment`, recorded by charge ID, idempotent |

All webhook handlers: verify signature → store raw event with unique `(provider, event_id)` constraint (idempotency) → process in a transaction → acknowledge. Frontend "success" pages only poll status; they never grant access.
**App-store rules change and differ by region** (e.g. external purchase links/alternative billing in the US and EU). Exact allowed flows per store/region are verified against current official policy in Phase 10 and recorded in `PAYMENT_INTEGRATION.md`; until then the apps assume in-app purchase is required for purchases started inside the app, and accounts paid elsewhere can sign in and use their entitlement.

### ADR-009 — Kill switch per platform (no false promises)
| Platform | Mechanism |
|---|---|
| Android | OS "Always-on VPN" + "Block connections without VPN" (app deep-links the user there and detects state); in-app: keep the VpnService interface up during reconnects so traffic is blackholed, not leaked |
| iOS | `includeAllNetworks` / `enforceRoutes` on the tunnel provider configuration (with documented Apple caveats), on-demand rules for auto-connect |
| Windows | WireGuardNT tunnel service with full-route config enables WFP block of untunneled traffic |
| macOS | Network Extension with `includeAllNetworks`; documented limitations |
Each is verified by automated + manual leak tests (Phase 11) before the feature is advertised.

### ADR-010 — Privacy and logging
We **do not** claim "no logs" until Phase 11 verifies it. Planned data inventory:

| Data | Where | Why | Retention |
|---|---|---|---|
| Email, password hash, Telegram ID (optional), language | Postgres | Account | Life of account + 30 days |
| Device name, platform, **public** key, tunnel IPs | Postgres | Access control | Until device revoked + 30 days |
| Last handshake time per device (coarse, 1 h resolution) | Postgres | "Last connected" UI, idle peer cleanup | Overwritten |
| Aggregate bytes per device per day | Postgres | Usage statistics, abuse limits | 90 days |
| Payment records (provider IDs, amounts, status — never card data) | Postgres | Billing, tax, refunds | As required by accounting law (verify) |
| Client real IP at API level | Nginx/app logs | Security, rate limits | Short (e.g. 7 days) — truncated in app logs |
| Client real IP / endpoint on VPN nodes | Kernel memory only | WireGuard protocol requires it while active | Not exported, not logged |
| Visited destinations, DNS queries | — | — | **Not collected**; unbound query logging off |

### ADR-011 — Background jobs
Celery with Redis broker (spec default; mature, beat scheduler, retries). Jobs are idempotent and keyed (e.g. `expire-subscription:<id>`). Long-term option: move broker to RabbitMQ if delivery guarantees become insufficient.

### ADR-012 — API contract and clients
FastAPI generates OpenAPI 3.1 → committed to `shared/api-contracts/openapi.json` by CI (drift check fails the build). TypeScript client generated for web/admin; Dart client for Flutter. Versioning: URI prefix `/api/v1`; breaking changes go to `/api/v2` with a deprecation window. Apps send `X-Client-Version`; backend can return `426 Upgrade Required` for unsupported versions.

### ADR-013 — Internationalisation
ICU MessageFormat catalogs (`en`, `de`, `hu`, `uk`, `ru`) in `shared/locales/<lang>/*.json`, consumed by backend (emails, notifications), bot, web, admin; Flutter uses ARB generated from the same source. Language negotiation: user setting → `Accept-Language` / Telegram `language_code` → `en`. Amounts stored as integer minor units + ISO-4217 currency; formatting via CLDR per locale. All timestamps stored in UTC.

### ADR-014 — Protocol extensibility
`vpn` module defines a `VpnProtocol` interface (`provision_device`, `assign`, `revoke`, `client_config`, `node_desired_state`). WireGuard is the first implementation; OpenVPN/IKEv2 can be added as new implementations with their own node-agent drivers without changing billing/device logic.

---

## 4. Core data model (outline)

Full schema in `DATABASE_SCHEMA.md` (Phase 2). All tables have UUIDv7 primary keys, `created_at`, `updated_at`.

- **users** — email (citext, unique, nullable), email_verified_at, password_hash (nullable for Telegram-only), telegram_id (unique, nullable), locale, status (`active|suspended|deleted`), roles.
- **sessions / refresh_tokens** — family_id, token_hash, expires_at, revoked_at, replaced_by, user_agent, ip_prefix.
- **devices** — user_id, name, platform, public_key (unique), ipv4, ipv6, status (`active|revoked`), last_handshake_at, created_at, revoked_at.
- **locations** — country_code (ISO-3166), city, display names (i18n), sort order, enabled.
- **servers (nodes)** — location_id, hostname, public IPv4/IPv6, endpoint port, wg public key, tier, status (`provisioning|active|draining|maintenance|disabled`), max_peers, bandwidth_capacity_mbps, agent cert fingerprint, last_heartbeat_at.
- **server_metrics** — time-series rollups (or Prometheus only; DB keeps last snapshot).
- **peer_assignments** — device_id, server_id, state (`pending|active|removing`), assigned_at, last_seen_at, revision.
- **plans** — code, i18n name/features, tier access, device_limit, trial flag, active flag.
- **plan_prices** — plan_id, duration (months/days), currency, amount_minor, provider product/price IDs per store, active window.
- **subscriptions** — user_id (or family owner), plan_id, status (`trialing|active|past_due|grace|canceled|expired|refunded`), current_period_start/end, cancel_at_period_end, provider, provider_subscription_id.
- **family_members** — subscription_id, user_id, role.
- **payments** — user_id, provider, provider_payment_id (unique), amount_minor, currency, status, kind (`initial|renewal|refund`).
- **payment_events** — provider, event_id (unique), payload (redacted), received_at, processed_at, result — idempotency + audit.
- **promo_codes / campaigns / promo_redemptions**.
- **support_tickets / ticket_messages** — category, priority, status, assignee.
- **notifications / notification_preferences**.
- **audit_logs** — actor_id, actor_type, action, target_type, target_id, result, ip_prefix, metadata (secrets scrubbed).
- **settings** — typed key/value for global policy (grace period days, idle peer TTL, trial servers, auto-scaling policy, spending limit).

---

## 5. Key flows

**Device onboarding (app):** sign in → app generates keypair → `POST /api/v1/devices {name, platform, public_key}` → backend checks device limit for plan → allocates tunnel IPs → returns device id + addresses (no keys).

**Connect:** app `POST /api/v1/vpn/connect {device_id, location|server_id}` → entitlement check → server selection → `peer_assignments` row + revision bump → Redis publish → node agent long-poll returns → `wg set` → backend returns `{endpoint, server_public_key, allowed_ips, dns, addresses}` → app builds config locally with its private key → tunnel up → app shows CONNECTED only after the platform reports the tunnel up **and** a first handshake / reachability probe through the tunnel succeeds.

**Expiry:** beat job finds subscriptions past `period_end + grace` → status `expired` → assignments set `removing` → agents remove peers → user notified (email/Telegram/push per preferences).

**Telegram purchase (Stars):** bot sends invoice → `pre_checkout_query` validated with backend (plan still sold, user allowed) → `successful_payment` → bot forwards charge ID to backend via service API → backend records payment idempotently → activates subscription → notification.

**Auto-scaling:** beat job computes capacity per location → over threshold → alert admins → if `autoscale.enabled` **and** projected monthly spend ≤ configured limit → Terraform-driven provisioning job → Ansible role → agent registers with one-time enrollment token → health + connectivity tests → `active`. Otherwise a "provision recommended" task waits for admin approval.

---

## 6. Environments

| Env | Purpose | Data | Payments |
|---|---|---|---|
| development | Local Docker Compose; mailpit for email | Seed data | Stripe test mode / mocks in unit tests only |
| testing | CI ephemeral containers | Fixtures | Mocks |
| staging | Real cloud, at least 1–2 real VPN nodes | Synthetic | Stripe test mode, App Store sandbox, Play test tracks |
| production | Real | Real | Live |

Destructive tests (provisioning, firewall changes, leak tests) run only against staging nodes.

---

## 7. Security baseline (expanded in `SECURITY_POLICY.md`)

TLS everywhere (HSTS, TLS 1.2+), strict CSP and security headers on web/admin, parameterised SQL only (SQLAlchemy), Pydantic validation on every input, RBAC enforced at the route-dependency layer and re-checked in services, secrets via environment injected from a secrets manager (SOPS+age in repo-encrypted form or the cloud provider's secret store — never plaintext in Git), encrypted backups, Dependabot + `pip-audit` + `npm audit` + Trivy in CI, non-root distroless/slim containers, read-only root filesystems where possible, audit logging with secret scrubbing, minimum data in admin views.

---

## 8. Scalability envelope (initial targets)

- API: stateless; 2+ instances behind Nginx; PgBouncer in front of Postgres when connections exceed ~200.
- VPN nodes: WireGuard handles thousands of peers per interface; we cap per node by `max_peers` (default 1500, tune from load tests) and bandwidth.
- 50k users ≈ 15–25 nodes depending on concurrency and bandwidth — validated by load tests in Phase 11, not assumed.
