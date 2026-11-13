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
3. **Referral program:** personal link `t.me/<bot>?start=ref_<code>`; the referrer is attached only
   before the invitee's first payment; on that first payment the referrer earns a one-time
   discount (`referrals.percent_off`, default 30 %) applied automatically to their next checkout
   (available → reserved by a pending invoice → used; released if the invoice fails/expires).
   One reward per invitee; not combined with a promo code. Toggle: `referrals.enabled`.
4. **Country switch keeps the device key:** the Mini App stores each private key it generated in
   the device's own `localStorage` (never sent anywhere) so a device can be moved to another
   country and its config re-issued; devices created elsewhere get a new connection instead.
   Removing a device wipes its stored key.
5. **Brand "VpnHub" is a working name.** An existing VPN product "VPNhub" (com.appatomic.vpnhub)
   uses the same name with a black/orange scheme and there are "VPNHUB"/"VPN HUB" trademark
   filings. Before public launch the owner should clear the name with a trademark lawyer; the name
   is set in one place per component (`APP_NAME` env, `miniapp/src/index.html` data-app-name) and
   the logo is an original mark, not derived from any existing brand.
