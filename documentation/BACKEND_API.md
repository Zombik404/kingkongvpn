# Backend API (v1)

Source of truth: [`shared/api-contracts/openapi.json`](../shared/api-contracts/openapi.json) (OpenAPI 3.1,
regenerated with `make openapi`; a test fails if it drifts from the code). Interactive docs at
`/api/docs` outside production. This page explains the conventions and lists the endpoints.

## Conventions

- **Base path** `/api/v1`. JSON in and out. Unknown request fields are rejected (`422`).
- **Auth**: `Authorization: Bearer <access_token>`. Access tokens are Ed25519-signed JWTs (15 min)
  with `sub`, `sid` (session), `roles`, `ver`, `amr`. Every request re-checks the user and session in
  the database, so logout, suspension and role changes take effect immediately.
- **Refresh**: `POST /auth/refresh` with the opaque refresh token. Each use returns a **new** refresh
  token; presenting an already-used one revokes the whole session (theft detection). Clients must
  serialise refreshes (one in flight per session).
- **Errors**: `{"error": {"code": "...", "message": "...", "details": {...}?}}` with a matching
  HTTP status. Validation errors use FastAPI's standard `422 {"detail": [...]}`.
- **Rate limits** return `429` with `Retry-After` (seconds). Limits are listed in
  `app/security/rate_limit.py` (login: 20/min per IP, 10 per 15 min per account; registration:
  5/h per IP; emails: 3/h per address).
- **No enumeration**: register, resend-verification and password-reset answer `202` identically
  whether or not the address has an account.
- **Money** is integer minor units + ISO-4217 currency. **Time** is UTC ISO-8601.
- **Locale**: `Accept-Language` (or an explicit `locale`) chooses email language; supported:
  `en`, `de`, `hu`, `uk`, `ru`.
- Responses under `/api/` carry `Cache-Control: no-store` and standard security headers.

## Typical flows

**Sign-up:** `POST /auth/register` → email link → `POST /auth/verify-email {token}` →
`POST /auth/login`. Login is refused (`403 email_not_verified`) until the email is confirmed.

**Login with 2FA:** `POST /auth/login` returns `{"mfa_required": true, "mfa_token": ...}` →
`POST /auth/mfa/verify {mfa_token, code}` → tokens. Enrol with `/auth/mfa/totp/setup` (returns the
secret and an `otpauth://` URI for a QR code) then `/auth/mfa/totp/enable {code}`.

**Device:** the app generates a WireGuard keypair locally and sends only the public key:
`POST /devices {name, platform, public_key}` → `{id, ipv4, ipv6, ...}`. The device limit comes from
the plan (or the `devices.limit_without_subscription` setting); exceeding it gives
`409 device_limit_reached` with `details.limit`.

**Access:** `GET /subscription` → `{entitled, subscription, trial_available}`.
`POST /subscription/trial` (once per account, if enabled), `/cancel` and `/resume`
(cancel = stop at period end). Free-days promo codes: `POST /promo/redeem`.
Discount codes: `POST /promo/validate` previews the price (applied at checkout, Phase 10).

## Payments (crypto via @CryptoBot)

Prices are in fiat (USD by default); the customer pays in the accepted crypto assets
(`CRYPTOBOT_ACCEPTED_ASSETS`, default `GRAM,USDC`; GRAM falls back to the API's `TON` code). Crypto doesn't auto-renew: each period is a new
checkout, and the existing "access ends in N days" reminders prompt renewal.

1. `POST /payments/checkout {price_id, promo_code?}` → `{id, status: "pending", checkout_url,
   amount_minor, expires_at, ...}`. The bot shows `checkout_url` as a "Pay" button (opens the
   @CryptoBot invoice inside Telegram).
2. Access is granted **only** when the provider confirms: a signed webhook
   (`POST /webhooks/cryptobot`, HMAC-SHA256 with SHA256(token), `request_date` ≤ 10 min old)
   or our own `getInvoices` call (beat job every 60 s, or `GET /payments/{id}?refresh=true`
   for an "I've paid" button). The invoice amount, currency and payload must match ours.
3. The period comes from our price (calendar months), added to the current period end for
   renewals. Processing is idempotent (row lock + events keyed by invoice and status).

Limits: 10 checkouts per hour and at most 5 unpaid invoices per account; discount codes are
applied at checkout (100 % codes are refused — use free-days codes instead).

CLI: `python -m app.cli bootstrap-catalog` (creates plans + launch prices $5/$13/$24/$42,
idempotent); `python -m app.cli set-price standard month 3 USD 12.99` (replaces the active price for
that period, keeps history); `python -m app.cli cryptobot-check` (verifies the token, lists
asset codes).

## Staff API and permissions

All `/admin/*` routes need a staff role **and** a session that passed TOTP (`403 mfa_required`
otherwise). Roles are read from the database on every request. Every mutation is audit-logged.

| Permission | support | ops | finance | superadmin |
|---|:-:|:-:|:-:|:-:|
| `users:read` — search/view users | ✓ | ✓ | ✓ | ✓ |
| `users:write` — suspend/reactivate (non-staff only unless superadmin) | ✓ | | | ✓ |
| `subscriptions:grant` — grant/extend/revoke access | ✓ | | | ✓ |
| `plans:read` | ✓ | ✓ | ✓ | ✓ |
| `plans:write` — plans and prices | | | ✓ | ✓ |
| `promo:write` | | | ✓ | ✓ |
| `settings:read` | ✓ | ✓ | ✓ | ✓ |
| `settings:write` | | ✓ | | ✓ |
| `audit:read` | | ✓ | | ✓ |
| `roles:write` | | | | ✓ |

The first superadmin is created from the command line on the server:
`python -m app.cli grant-role you@example.com superadmin` (the account must exist and be verified),
then sign in again and enable 2FA.

## Global settings (`/admin/settings`)

| Key | Default | Meaning |
|---|---|---|
| `trial.enabled` | `false` | Offer a free trial (off until the owner decides) |
| `trial.days` | `3` | Trial length (1–30) |
| `trial.plan_code` | `trial` | Plan whose limits a trial grants |
| `subscription.grace_days` | `3` | Access kept after an unpaid period ends (0–30) |
| `devices.limit_without_subscription` | `1` | Devices before subscribing (0–10) |
| `reminders.days_before` | `[3]` | Reminder emails before non-renewing access ends |
| `peers.idle_ttl_hours` | `24` | Idle peer removal on nodes (used from Phase 4) |

## Background jobs (Celery beat)

| Task | Schedule | Does |
|---|---|---|
| `subscriptions.process_due` | every 5 min | period end → grace / canceled / expired; grace end → expired; marks node peers for removal; emails |
| `subscriptions.send_reminders` | hourly | one email per configured threshold for non-renewing access |
| `users.purge_deleted` | daily | hard-deletes accounts anonymised more than 30 days ago |
| `auth.cleanup_tokens` | daily | removes sessions/tokens expired or revoked more than 7 days ago |
| `payments.poll_pending` | every 60 s | re-checks unpaid @CryptoBot invoices (lost webhooks, no-webhook setups) |
| `email.send` | on demand | SMTP delivery with exponential back-off (8 retries) |

## Health

`/health/live` (process up), `/health/ready` (DB + Redis; `503` when degraded), `/metrics`
(Prometheus; **must not** be exposed publicly — restrict in Nginx).

## Endpoints

### auth

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/api/v1/auth/login` | public | Returns tokens, or `mfa_required` + a short-lived `mfa_token` for `/auth/mfa/verify`. |
| POST | `/api/v1/auth/logout` | bearer | Logout |
| POST | `/api/v1/auth/logout-all` | bearer | Logout All |
| POST | `/api/v1/auth/mfa/totp/disable` | bearer | Totp Disable |
| POST | `/api/v1/auth/mfa/totp/enable` | bearer | Totp Enable |
| POST | `/api/v1/auth/mfa/totp/setup` | bearer | Totp Setup |
| POST | `/api/v1/auth/mfa/verify` | public | Mfa Verify |
| POST | `/api/v1/auth/password-reset/confirm` | public | Sets the new password and signs out every session. |
| POST | `/api/v1/auth/password-reset/request` | public | Password Reset Request |
| POST | `/api/v1/auth/password/change` | bearer | Keeps the current session, signs out all others. |
| POST | `/api/v1/auth/refresh` | public | Rotate the refresh token. Reusing a rotated token revokes the whole session. |
| POST | `/api/v1/auth/register` | public | Create an account and email a verification link. Same answer for existing emails. |
| POST | `/api/v1/auth/resend-verification` | public | Resend Verification |
| POST | `/api/v1/auth/verify-email` | public | Verify Email |

### account

| Method | Path | Auth | Notes |
|---|---|---|---|
| DELETE | `/api/v1/users/me` | bearer | Irreversible: anonymises the account, revokes devices, ends access. |
| GET | `/api/v1/users/me` | bearer | Me |
| PATCH | `/api/v1/users/me` | bearer | Update Me |
| GET | `/api/v1/users/me/export` | bearer | All personal data we hold, as JSON. |
| GET | `/api/v1/users/me/sessions` | bearer | List Sessions |
| DELETE | `/api/v1/users/me/sessions/{session_id}` | bearer | Revoke Session |

### devices

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/devices` | bearer | List Devices |
| POST | `/api/v1/devices` | bearer | Register a device by its WireGuard **public** key; returns its tunnel addresses. |
| DELETE | `/api/v1/devices/{device_id}` | bearer | Revoke: the key stops working on every node and can't be registered again. |
| PATCH | `/api/v1/devices/{device_id}` | bearer | Rename Device |

### plans

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/plans` | public | Purchasable plans with their currently valid prices (public). |

### subscription

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/subscription` | bearer | Get Subscription |
| POST | `/api/v1/subscription/cancel` | bearer | Stop at the end of the current period (access continues until then). |
| POST | `/api/v1/subscription/resume` | bearer | Resume |
| POST | `/api/v1/subscription/trial` | bearer | Start Trial |

### promo

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/api/v1/promo/redeem` | bearer | Redeem a free-days code: extends current access or starts it. |
| POST | `/api/v1/promo/validate` | bearer | Preview a discount code against a price; it's applied at checkout. |

### admin

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/admin/audit-logs` | staff | Audit Logs |
| GET | `/api/v1/admin/plans` | staff | List Plans |
| POST | `/api/v1/admin/plans` | staff | Create Plan |
| PATCH | `/api/v1/admin/plans/{plan_id}` | staff | Update Plan |
| GET | `/api/v1/admin/plans/{plan_id}/prices` | staff | List Prices |
| POST | `/api/v1/admin/plans/{plan_id}/prices` | staff | Prices are append-only in practice: deactivate and add a new one instead of editing |
| PATCH | `/api/v1/admin/prices/{price_id}` | staff | Update Price |
| GET | `/api/v1/admin/promo-codes` | staff | List Promo |
| POST | `/api/v1/admin/promo-codes` | staff | Create Promo |
| PATCH | `/api/v1/admin/promo-codes/{promo_id}` | staff | Update Promo |
| GET | `/api/v1/admin/settings` | staff | List Settings |
| PUT | `/api/v1/admin/settings/{key}` | staff | Put Setting |
| GET | `/api/v1/admin/users` | staff | Search by exact user ID or email prefix. |
| GET | `/api/v1/admin/users/{user_id}` | staff | Get User |
| PUT | `/api/v1/admin/users/{user_id}/roles` | staff | Set Roles |
| POST | `/api/v1/admin/users/{user_id}/status` | staff | Suspend (signs out everywhere) or reactivate an account. |
| POST | `/api/v1/admin/users/{user_id}/subscription/grant` | staff | Goodwill / support: extend (or start) access by N days on a plan. |
| POST | `/api/v1/admin/users/{user_id}/subscription/revoke` | staff | Revoke Subscription |
