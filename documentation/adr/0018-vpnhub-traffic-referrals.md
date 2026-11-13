# ADR-018 — VpnHub UI: traffic dashboard, referrals, country switch

Status: accepted (2026-11-13).

1. **Traffic accounting = aggregate bytes per device per UTC day** (`device_usage_daily`), computed
   from WireGuard's cumulative per-peer counters the agent reports in each heartbeat. Counter resets
   (peer re-added) are handled; rows are purged after 90 days (ADR-010). No destinations, no DNS.
2. **No "top apps" in the Telegram Mini App.** The server sees only encrypted packets per device and
   by policy records no destinations; neither Telegram nor a web page can see which app on the phone
   produced traffic. The dashboard shows the top 5 *devices*. Per-app usage is planned for the
   native Android app (on-device `NetworkStatsManager`, data stays on the device); iOS offers no
   such API to third-party apps.
3. **Referral program (v2, migration 0006):** personal link `t.me/<bot>?start=ref_<code>`; the
   referrer is attached only before the invitee's first payment.
   - The **invited user** gets `referrals.percent_off` (default 30 %) off their **first** payment,
     applied automatically at checkout (`payments.referral_percent_off`); not combined with a promo
     code. If the invoice expires the discount stays available until they actually pay once.
   - The **referrer** gets `referrals.bonus_days` (default 14, 0 = off) free days per invitee whose
     first payment succeeds: the live subscription is extended on its current plan; a referrer on
     a trial or with no subscription gets the plan the invitee bought. Suspended/deleted referrers
     get nothing. No discount for the referrer.
   - One credit per invitee (`referral_rewards`, unique `referred_id`) — a repeated webhook/poll
     can't add days twice. Toggle the whole program with `referrals.enabled`.
   - Known edge: an invitee with two unpaid discounted invoices open at once could pay both at
     the discount (bounded by `payment_pending_limit_per_user`).
4. **Country switch keeps the device key:** the Mini App stores each private key it generated in
   the device's own `localStorage` (never sent anywhere) so a device can be moved to another
   country and its config re-issued; devices created elsewhere get a new connection instead.
   Removing a device wipes its stored key.
5. **Brand "VpnHub" is a working name.** An existing VPN product "VPNhub" (com.appatomic.vpnhub)
   uses the same name with a black/orange scheme and there are "VPNHUB"/"VPN HUB" trademark
   filings. Before public launch the owner should clear the name with a trademark lawyer; the name
   is set in one place per component (`APP_NAME` env, `miniapp/src/index.html` data-app-name) and
   the logo is an original mark, not derived from any existing brand.
