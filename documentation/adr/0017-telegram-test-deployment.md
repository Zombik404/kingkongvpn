# ADR-017 — Telegram test version: single server, Mini App, node token auth

Status: accepted for the closed test (2026-11-13). Revisit before public launch.

| # | Decision | Why | Production path |
|---|---|---|---|
| 1 | **Everything on one VPS** (API, workers, bot, DB, Caddy, WireGuard node + agent) | Cheapest way to a real test with EU testers | Separate control-plane host; nodes per country (Phase 4/12) |
| 2 | **Plain WireGuard**, no obfuscation | Testers are in the EU | AmneziaWG / other `VpnProtocol` if a market needs it (ADR-014) |
| 3 | **Telegram Mini App generates the keypair** (X25519 via audited `@noble/curves`), only the public key reaches the API (ADR-003). The config is offered as QR, file download, "open in browser" (config in the URL *fragment*, never sent to a server, wiped from history on load) and copy | No private keys on our side; works without native apps | Native apps (Phases 6–7) |
| 4 | **Mini App sign-in with signed `initData`** (HMAC per Telegram spec, max age 24 h), Telegram-only accounts without email; staff accounts can't use it (they need TOTP) | Telegram already authenticated the user | — |
| 5 | **Closed test via `access.invite_only`**: trial/checkout require a redeemed invite (single-use free-days codes, deep links `t.me/<bot>?start=INV-…`) | Controlled tester group | Turn the setting off |
| 6 | **Node ↔ backend auth = per-node bearer token** (HMAC-stored, rotated on re-register), API on 127.0.0.1 only; `/internal/*` never proxied | Agent and API share the host | mTLS with the node CA over the public endpoint (ADR-002) before a second server |
| 7 | **Long-poll by DB revision check every 1 s** (≤25 s) | Simple and enough for one node | Redis pub/sub wake-up |
| 8 | **Client DNS = 1.1.1.1 / 2606:4700:4700::1111 through the tunnel** | No resolver to operate in the test; queries still go via the tunnel | Node-local unbound without query logs (ADR-005/010) |
| 9 | **Firewall = own nftables table** (no `flush ruleset`, Docker keeps working) + DOCKER-USER exemption for wg0; client-to-client, LAN/metadata ranges and SMTP blocked; IPv6 rejected inside the tunnel if the host has none | Verified with real tunnels (wireguard-go in network namespaces) | Same rules via Ansible role |
| 10 | **Notifications to Telegram users go from the backend** (Bot API `sendMessage` via Celery), the bot process only handles /start, /help and the menu button | Keeps the bot stateless | — |
