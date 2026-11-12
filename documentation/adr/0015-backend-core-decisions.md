# ADR-015 — Backend core decisions taken in Phase 2

Status: accepted (Phase 2, 2026-11-12). Refines ADR-007 (auth), ADR-008 (entitlements), ADR-010 (privacy).

| # | Decision | Why | Revisit when |
|---|---|---|---|
| 1 | **Login requires a verified email.** Registration never returns tokens. | Cheapest anti-abuse step; keeps registration enumeration-safe. | Telegram-only sign-up (Phase 5) uses its own path. |
| 2 | **Strict refresh rotation, no grace window.** Two concurrent refreshes with the same token revoke the session. | Simplest correct theft detection. | If apps show spurious logouts, add a short (≤ 10 s) grace that returns the already-issued successor. |
| 3 | **Rate limiter fails open** when Redis is down (logged). | A cache outage shouldn't lock everyone out; Argon2 cost still slows guessing. | If an attacker can force Redis outages. |
| 4 | **Any staff permission requires an MFA-verified session**; staff sessions last 12 h (sliding); role changes revoke the user's sessions. | Admin accounts are the highest-value target. `ADMIN_REQUIRE_MFA` can't be disabled outside dev/test. | WebAuthn arrives with the admin panel (Phase 9). |
| 5 | **TOTP seeds encrypted with AES-256-GCM** (`DATA_ENCRYPTION_KEY`), ciphertext bound to the user ID. | A DB dump alone doesn't yield second factors. | Key rotation tooling (Phase 11). |
| 6 | **Account deletion anonymises immediately**, purge after 30 days. | Stricter than ADR-010's "life + 30 days"; the email becomes reusable at once. | If fraud/chargeback handling needs the email kept — confirm with legal. |
| 7 | **No `server_metrics` table**; Prometheus holds time series, `servers.last_metrics` the latest snapshot. | Avoid duplicating a TSDB in Postgres. | — |
| 8 | **Terminal subscription states are never reactivated**; at most one live subscription per user (DB-enforced). | Clean history for billing and support. | Family plans (shared entitlement) in Phase 10. |
| 9 | **Free-days promo codes are redeemed directly; discount codes are only validated** until checkout exists (Phase 10). | No payment flow yet to apply a discount to. | Phase 10. |
| 10 | **Trial is off by default** (`trial.enabled=false`). | Free access is a commercial decision for the owner. | Owner enables it in admin settings. |
| 11 | **Backend email catalogs live in `backend/app/i18n/locales/`**, not `shared/locales/`. | The backend Docker build context is `backend/`. | Phase 5/8: a sync script copies shared catalogs into each consumer at build time. |
| 12 | **Web refresh-token cookie mode (HttpOnly + CSRF) deferred** to Phase 8; the API currently returns refresh tokens in the body (fine for apps/bot). | No web client exists yet to test it against. | Phase 8. |
