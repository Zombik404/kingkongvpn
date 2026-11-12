# Database schema

PostgreSQL 16. Defined by SQLAlchemy models in `backend/app/models/` and the Alembic migration
`backend/migrations/versions/` (`0001_initial_schema`, `0002_cryptobot_payments`) (a test fails if the two drift apart, and the
migration is tested up → down → up on a fresh database).

**Conventions:** UUIDv7 primary keys (time-ordered), `created_at`/`updated_at` in UTC
(`timestamptz`), enums stored as `varchar` + `CHECK` (easier migrations than native enums), money
as integer minor units + ISO-4217 `char(3)`, emails as `citext` (case-insensitive unique).
Constraint names follow a fixed convention (`uq_<table>_<col>`, `ck_<table>_<name>`, …) so
migrations are deterministic.

Run migrations: `make migrate` (Docker) or `cd backend && alembic upgrade head`.

## Accounts and auth

| Table | Purpose | Key rules |
|---|---|---|
| `users` | Account | `email` citext unique nullable (Telegram-only accounts), `telegram_id` unique, `status ∈ active/suspended/deleted`, `roles varchar[]` (staff roles only), `token_version` (bump = invalidate all access tokens), `totp_secret_encrypted` (AES-256-GCM, bound to the user ID), `totp_last_counter` (replay protection), `trial_used_at` |
| `auth_sessions` | A login = a refresh-token family | `revoked_at` + `revoke_reason`, `mfa_verified`, sliding `expires_at` (30 days; 12 h for staff), `ip_prefix` (/24 or /48 only) |
| `refresh_tokens` | Opaque tokens, **HMAC-SHA256 with a server pepper**, never stored raw | `token_hash` unique, `used_at` + `replaced_by_id` (rotation chain; reuse ⇒ session revoked) |
| `user_action_tokens` | Email verification / password reset links | hashed, single-use (`used_at`), expiring; issuing a new one invalidates older ones of the same purpose |

## VPN

| Table | Purpose | Key rules |
|---|---|---|
| `devices` | A client device | `public_key` 44-char base64, **unique forever** (a revoked key can't come back); `address_index` unique → `ipv4`/`ipv6` (both unique) = pool network + index (ADR-004); `status ∈ active/revoked` |
| `locations` | Country/city | `country_code ~ '^[A-Z]{2}$'`, unique (country, city), i18n `names` |
| `servers` | VPN nodes | unique `hostname`, `wg_public_key`, `agent_cert_fingerprint`; `status ∈ provisioning/active/draining/maintenance/disabled`; `revision` bumps when its peer set changes; `last_metrics` = latest snapshot only (time series live in Prometheus — no `server_metrics` table) |
| `peer_assignments` | Device ↔ node | unique (device, server); `state ∈ pending/active/removing` |

Sequence `tunnel_address_seq` feeds address allocation; when it passes the end of the pool the
allocator reuses indices freed by purged devices. The unique constraint on `address_index` is what
guarantees no two devices ever share an address, even under concurrency (tested).

## Billing

| Table | Purpose | Key rules |
|---|---|---|
| `plans` | Product | `code` unique (`^[a-z0-9][a-z0-9_-]{1,31}$`), i18n `names`, `features` JSON, `device_limit` 1–100, `server_tiers`, `is_trial`, `active` |
| `plan_prices` | Price points | `period_unit ∈ day/month/year` × `period_count` 1–36, `amount_minor ≥ 0`, `provider_ids` JSON (Stripe/Apple/Google IDs), validity window |
| `subscriptions` | Entitlement (provider-agnostic) | `status ∈ trialing/active/past_due/grace/canceled/expired/refunded`; **partial unique index: one live (trialing/active/past_due/grace) row per user**; unique (provider, provider_subscription_id); `reminder_sent_for` + `reminder_threshold_days` make reminders idempotent |
| `family_members` | Shared plans (future) | unique (subscription, user) |
| `payments` | Charges/refunds — no card data | unique (provider, provider_payment_id) = (cryptobot, invoice_id); `status ∈ pending/succeeded/failed/refunded`; `plan_price_id` (what was bought — the granted period comes from here), `promo_code_id`, `checkout_url`, `expires_at`, `paid_at`, `paid_asset`/`paid_amount` (crypto actually received), `failure_reason` (`expired`, `amount_mismatch`, `needs_manual_review`); `user_id ON DELETE SET NULL` (accounting records outlive accounts) |
| `payment_events` | Provider events (webhook or poll), minimal fields only | unique (provider, event_id); for @CryptoBot `event_id = invoice:<id>:<status>` because its `update_id` is not unique |
| `campaigns`, `promo_codes`, `promo_redemptions` | Promotions | code citext unique; `CHECK` that fields match the kind (percent 1–100 / amount + currency / free days + plan); one redemption per user per code; `redemption_count` updated under a row lock so `max_redemptions` holds under concurrency |

Subscription transitions are implemented once, in `app/subscriptions/state_machine.py`
(pure functions, exhaustively unit-tested). Terminal states never reactivate — a new purchase
creates a new row.

## Operations

| Table | Purpose |
|---|---|
| `audit_logs` | Append-only: actor, action, target, result, `ip_prefix`, `details` (secrets scrubbed by key name before insert) |
| `settings` | Typed global policy values (schema + defaults in `app/services/settings.py`) |
| `support_tickets`, `ticket_messages` | Support inbox (API in Phase 9) |
| `notifications`, `notification_preferences` | Delivery log and per-user channel preferences (Phase 5+) |

## Retention (as implemented)

| Data | Rule |
|---|---|
| Deleted account | Anonymised immediately (email, password hash, Telegram ID, TOTP cleared; devices revoked; access ended); row hard-deleted after 30 days, cascading to devices and sessions |
| Sessions / tokens | Deleted 7 days after expiry or revocation |
| Payments | Kept (legal retention period to be confirmed by an accountant) |
