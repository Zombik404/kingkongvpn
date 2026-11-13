# ADR-020: Admin panel (Phase 9) and user-data protection

Status: accepted · 2026-11-13

## Context

The owner asked for everything that doesn't need a server: protection of user data, data
leaks, and the admin panel with its features. The staff API existed; there was no UI, no way to
create a staff account without email delivery (the Telegram version sends no mail), and a
review found the issues listed in `documentation/SECURITY_PRIVACY.md`.

## Decisions

1. **Panel = static vanilla JS** in `admin-panel/` (esbuild, committed `dist/`, like the Mini
   App), served by Caddy at `/admin/`. No framework, no third-party assets: the CSP is
   `default-src 'none'; script-src 'self'; style-src 'self'; …`, so styles are set through
   CSSOM and the TOTP QR code is drawn as SVG paths (no `innerHTML`).
2. **Tokens in memory only.** No localStorage, no cookies: a reload or 30 idle minutes means
   signing in again with 2FA. Refreshes are serialised (the backend treats a reused refresh
   token as theft).
3. **2FA is the gate.** A staff session without TOTP gets `403 mfa_required` everywhere; the
   panel turns that into the TOTP setup screen on first sign-in.
4. **`create-staff` CLI** makes or resets a verified email account with a one-time password
   (validated with the same email rules as the login form); `install.sh` creates the first
   superadmin from the owner's email. Telegram accounts can't become staff.
5. **Server-side support for the panel:** `GET /admin/me` (permissions), `GET /admin/overview`
   (money only with `payments:read`), `GET /admin/payments`, user search by Telegram ID and
   referral code (the Telegram ID is searchable but never returned). New permission
   `payments:read` for support, finance, superadmin.
6. **Optional network allowlist** for `/admin` and `/api/v1/admin/*` in Caddy
   (`ADMIN_ALLOWED_IPS`), on top of password + TOTP.
7. **Caddy rules in one `route`** so they run in written order (fixes public API docs).
   Backend docs only in development/testing.
8. **Data protection fixes** (deletion for Telegram users via fresh `initData`, full export,
   nickname removal, abuse limits, address release, encrypted backups) as listed in
   `SECURITY_PRIVACY.md`.

## Consequences

- Staff must re-enter 2FA after a reload — acceptable for a rarely used, high-value console.
- The panel is Russian only for now; strings are in the page modules.
- A clickable demo (`admin-panel/demo/`, sample data, fake fetch) lets the owner try it without
  a server.
