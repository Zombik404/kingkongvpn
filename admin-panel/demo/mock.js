// Clickable demo: the real admin panel on sample data. Replaces fetch() for /api/v1/* with an
// in-memory stand-in of the staff API; nothing leaves the browser. Any email/password works,
// the 2FA code is any 6 digits.
import SETTINGS from "./settings.json";
import { createAdminProgress } from "./progress-mock.js";

const DAY = 864e5;
const now = Date.now();
const iso = (t) => new Date(t).toISOString();
let seq = 1000;
const uid = () => `01a1d654-${(seq++).toString(16).padStart(4, "0")}-7${Math.floor(Math.random() * 4096).toString(16).padStart(3, "0")}-a000-${Math.random().toString(16).slice(2, 14).padEnd(12, "0")}`;
let rnd = 7;
const rand = () => { rnd = (rnd * 16807) % 2147483647; return rnd / 2147483647; };

const ME = { id: uid(), email: "owner@example.com", roles: ["superadmin"],
  permissions: ["audit:read", "games:read", "games:write", "payments:read", "plans:read", "plans:write", "promo:write", "roles:write", "servers:read", "servers:write", "settings:read", "settings:write", "subscriptions:grant", "users:read", "users:write"] };

const PLANS = [
  { id: uid(), code: "standard", names: { ru: "Стандарт", en: "Standard" }, features: {}, device_limit: 5, server_tiers: ["standard"], is_trial: false, active: true, sort_order: 10 },
  { id: uid(), code: "trial", names: { ru: "Пробный", en: "Trial" }, features: {}, device_limit: 2, server_tiers: ["standard"], is_trial: true, active: true, sort_order: 0 },
];
const PRICES = { [PLANS[0].id]: [[1, 500], [3, 1300], [6, 2400], [12, 4200]].map(([n, a]) => ({ id: uid(), plan_id: PLANS[0].id, period_unit: "month", period_count: n, currency: "USD", amount_minor: a, provider_ids: {}, active: true, valid_from: null, valid_until: null })), [PLANS[1].id]: [] };

function sub(plan, end, status = "active") {
  return { id: uid(), plan_code: plan.code, plan_name: plan.names.ru, status, provider: status === "trialing" ? "trial" : "cryptobot", auto_renew: false,
    current_period_start: iso(end - 30 * DAY), current_period_end: iso(end), cancel_at_period_end: false, grace_until: status === "grace" ? iso(end + 3 * DAY) : null, device_limit: plan.device_limit };
}
const USERS = [];
USERS.push({ ...ME, email_verified: true, status: "active", mfa_enabled: true, has_telegram: false, created_at: iso(now - 40 * DAY), last_login_at: iso(now - 600e3), active_devices: 0, subscription: null });
USERS.push({ id: uid(), email: "helper@example.com", email_verified: true, roles: ["support"], status: "active", mfa_enabled: true, has_telegram: false, created_at: iso(now - 20 * DAY), last_login_at: iso(now - 2 * DAY), active_devices: 0, subscription: null });
for (let i = 0; i < 46; i++) {
  const created = now - Math.floor(rand() * 30 * DAY);
  const r = rand();
  const s = r < 0.55 ? sub(PLANS[0], now + Math.floor(rand() * 80 * DAY)) : r < 0.65 ? sub(PLANS[1], now + 2 * DAY, "trialing") : r < 0.7 ? sub(PLANS[0], now - DAY, "grace") : null;
  USERS.push({ id: uid(), email: null, email_verified: false, roles: [], status: i === 7 ? "suspended" : "active", mfa_enabled: false, has_telegram: true,
    created_at: iso(created), last_login_at: iso(created + rand() * (now - created)), active_devices: s ? 1 + Math.floor(rand() * 3) : 0, subscription: s, tg: 700100 + i, ref: i === 3 ? "KONG2026" : null });
}
USERS.sort((a, b) => b.created_at.localeCompare(a.created_at));

const PAYMENTS = USERS.filter((u) => u.subscription?.provider === "cryptobot").map((u) => {
  const price = PRICES[PLANS[0].id][Math.floor(rand() * 4)];
  const paid = Date.parse(u.subscription.current_period_start);
  return { id: uid(), user_id: u.id, provider: "cryptobot", status: "succeeded", kind: "initial", amount_minor: price.amount_minor, currency: "USD",
    paid_asset: rand() < 0.6 ? "USDC" : "GRAM", paid_amount: (price.amount_minor / 100).toFixed(2), plan_code: "standard", period: `${price.period_count} month`,
    discount: rand() < 0.2 ? "referral" : null, failure_reason: null, created_at: iso(paid - 60e3), paid_at: iso(Math.max(paid, now - 29 * DAY)) };
});
PAYMENTS.push({ id: uid(), user_id: USERS[5].id, provider: "cryptobot", status: "pending", kind: "initial", amount_minor: 500, currency: "USD", paid_asset: null, paid_amount: null, plan_code: "standard", period: "1 month", discount: null, failure_reason: null, created_at: iso(now - 3600e3), paid_at: null });
PAYMENTS.sort((a, b) => b.created_at.localeCompare(a.created_at));

const PROMOS = [
  { id: uid(), code: "INV-KONG-2026", kind: "free_days", percent_off: null, amount_off_minor: null, currency: null, free_days: 30, plan_id: PLANS[0].id, max_redemptions: 1, redemption_count: 1, valid_from: null, valid_until: iso(now + 20 * DAY), active: true },
  { id: uid(), code: "JUNGLE20", kind: "percent_off", percent_off: 20, amount_off_minor: null, currency: null, free_days: null, plan_id: null, max_redemptions: 100, redemption_count: 14, valid_from: null, valid_until: null, active: true },
];

const LOCATIONS = [["DE", "Frankfurt", "Франкфурт"], ["NL", "Amsterdam", "Амстердам"], ["FI", "Helsinki", "Хельсинки"], ["PL", "Warsaw", "Варшава"]]
  .map(([cc, city, ru], i) => ({ id: uid(), country_code: cc, city, names: { en: city, ru }, sort_order: i, enabled: true }));
const SERVERS = [
  ["de-fra-1", 0, "203.0.113.5", 612, 1500, 0.2, "active"], ["de-fra-2", 0, "203.0.113.6", 1288, 1500, 0.2, "active"],
  ["nl-ams-1", 1, "198.51.100.7", 344, 1500, 0.3, "active"], ["fi-hel-1", 2, "192.0.2.9", 97, 1500, 0.2, "draining"],
  ["pl-waw-1", 3, "203.0.113.40", 0, 1500, 900, "active"],
].map(([hostname, li, ip, peers, max, beatMin, status]) => ({
  id: uid(), hostname, location_id: LOCATIONS[li].id, ipv4: ip, ipv6: null, endpoint_port: 51820, wg_public_key: "demo", tier: "standard", status, max_peers: max, peers,
  beat: now - beatMin * 60e3, revision: 40 + peers % 7, applied: hostname === "nl-ams-1" ? 38 + peers % 7 : 40 + peers % 7, agent_version: "0.3.0", agent_errors: hostname === "pl-waw-1" ? ["wg: interface wg0 not found"] : [], created_at: iso(now - 30 * DAY),
}));

const AUDIT = [];
function audit(action, target_type, target_id, details = {}, actor = ME.id) {
  AUDIT.unshift({ id: uid(), created_at: iso(Date.now()), actor_id: actor, actor_type: actor ? "admin" : "system", action, target_type, target_id: target_id ? String(target_id) : null, result: "success", ip_prefix: "198.51.100.0/24", details });
}
[["auth.login_telegram", "user", USERS[4].id, {}], ["game.redeem", "user", USERS[6].id, { days: 1 }], ["admin.setting_changed", "setting", "access.invite_only", { before: false, after: true }], ["subscription.granted", "user", USERS[9].id, { days: 30, plan: "standard", reason: "инвайт" }]]
  .forEach(([a, t, id, d], i) => { audit(a, t, id, d, i === 0 ? USERS[4].id : ME.id); AUDIT[0].created_at = iso(now - (i + 1) * 3 * 3600e3); });
AUDIT.sort((a, b) => b.created_at.localeCompare(a.created_at));

const ROOMS = [{ id: uid(), code: null, visibility: "private", max_players: 1, players: 1, status: "open", phase: "betting", round_no: 12 }];
const GAMEPROFILES = { [USERS[6].id]: { nickname: "BananaKing", rounds: 214, wins: 97, blackjacks: 11, chips: 2310, best_win: 500, balance_hours: 24 } };

// ------------------------------------------------------------------------------- routing
const json = (body, status = 200) => new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const fail = (status, code, message) => json({ error: { code, message } }, status);
const page = (rows, q) => rows.slice(Number(q.get("offset") || 0), Number(q.get("offset") || 0) + Number(q.get("limit") || 50));
const userOut = ({ tg, ref, ...u }) => u;
const serverOut = (s) => {
  const fresh = now - s.beat < 300e3 || Date.now() - s.beat < 300e3;
  return { id: s.id, hostname: s.hostname, location_id: s.location_id, ipv4: s.ipv4, ipv6: s.ipv6, endpoint_port: s.endpoint_port, wg_public_key: s.wg_public_key, tier: s.tier,
    status: s.status, max_peers: s.max_peers, peers: s.status === "disabled" ? 0 : s.peers, load: Math.round((s.peers / s.max_peers) * 1000) / 1000, heartbeat_fresh: fresh,
    accepting: s.status === "active" && fresh, last_heartbeat_at: iso(s.beat), revision: s.revision, applied_revision: s.applied, in_sync: s.applied === s.revision,
    agent_version: s.agent_version, agent_errors: s.agent_errors, has_token: true, created_at: s.created_at };
};
const days = (n, f) => Array.from({ length: n }, (_, i) => { const d = new Date(now - (n - 1 - i) * DAY).toISOString().slice(0, 10); return { day: d, ...f(d) }; });
const reasonOk = (b) => b?.reason && b.reason.length >= 3;
const needReason = () => fail(422, "validation_error", "reason: напишите причину (от 3 символов)");
const progressRoute = createAdminProgress({ audit, users: USERS, reasonOk, needReason, json, fail, page });

function route(method, path, q, b) {
  if (path === "/auth/login") return json({ mfa_required: true, mfa_token: "demo-mfa-token-0000" });
  if (path === "/auth/mfa/verify") return /^\d{6}$/.test(b.code || "") ? json({ token_type: "bearer", access_token: "demo", refresh_token: "demo-refresh-0000", expires_in: 900, session_id: uid() }) : fail(401, "invalid_mfa_code", "Нужно 6 цифр (в демо подойдут любые).");
  if (path === "/auth/logout") return json(null, 204);
  if (path === "/admin/me") return json(ME);
  if (path === "/admin/overview") {
    const live = USERS.filter((u) => u.status === "active");
    const usd = PAYMENTS.filter((p) => p.status === "succeeded");
    return json({ generated_at: iso(Date.now()),
      users: { total: live.length, new_7d: live.filter((u) => Date.parse(u.created_at) > now - 7 * DAY).length, telegram: live.filter((u) => u.has_telegram).length },
      subscriptions: { active: live.filter((u) => u.subscription?.status === "active").length, trialing: live.filter((u) => u.subscription?.status === "trialing").length, grace: live.filter((u) => u.subscription?.status === "grace").length },
      devices_active: live.reduce((s, u) => s + u.active_devices, 0),
      servers: { total: SERVERS.length, accepting: SERVERS.map(serverOut).filter((s) => s.accepting).length },
      games: { rounds_24h: 318, players_24h: 41 }, referral_rewards_30d: 9,
      signups_30d: days(30, (d) => ({ count: USERS.filter((u) => u.created_at.slice(0, 10) === d).length })),
      revenue_30d: { by_currency: { USD: { count: usd.length, amount_minor: usd.reduce((s, p) => s + p.amount_minor, 0) } },
        usd_daily: days(30, (d) => ({ amount_minor: usd.filter((p) => p.paid_at.slice(0, 10) === d).reduce((s, p) => s + p.amount_minor, 0) })) } });
  }
  if (path === "/admin/users" && method === "GET") {
    const term = (q.get("q") || "").trim();
    let rows = USERS;
    if (q.get("status")) rows = rows.filter((u) => u.status === q.get("status"));
    if (q.get("staff_only")) rows = rows.filter((u) => u.roles.length);
    if (term) rows = rows.filter((u) => u.id === term || String(u.tg) === term || u.ref === term || (u.email || "").startsWith(term.toLowerCase()));
    return json(page(rows, q).map(userOut));
  }
  let m = path.match(/^\/admin\/users\/([^/]+)(\/.*)?$/);
  if (m) {
    const u = USERS.find((x) => x.id === m[1]);
    if (!u) return fail(404, "not_found", "Пользователь не найден.");
    if (!m[2]) return json(userOut(u));
    if (!reasonOk(b) && m[2] !== "/roles") return needReason();
    if (m[2] === "/subscription/grant") {
      const plan = PLANS.find((p) => p.code === b.plan_code) || PLANS[0];
      const base = u.subscription && Date.parse(u.subscription.current_period_end) > Date.now() ? Date.parse(u.subscription.current_period_end) : Date.now();
      u.subscription = { ...sub(plan, base + b.days * DAY), provider: "admin" };
      audit("subscription.granted", "user", u.id, { days: b.days, plan: plan.code, reason: b.reason, provider: "admin" });
      return json(u.subscription);
    }
    if (m[2] === "/subscription/revoke") { u.subscription = null; u.active_devices = 0; audit("subscription.revoked", "user", u.id, { reason: b.reason }); return json(null, 204); }
    if (m[2] === "/status") { u.status = b.status; audit(`admin.user_${b.status}`, "user", u.id, { reason: b.reason }); return json(userOut(u)); }
    if (m[2] === "/roles") { u.roles = b.roles; audit("admin.roles_changed", "user", u.id, { roles: b.roles }); return json(userOut(u)); }
  }
  if (path === "/admin/payments") {
    let rows = PAYMENTS;
    if (q.get("status")) rows = rows.filter((p) => p.status === q.get("status"));
    if (q.get("user_id")) rows = rows.filter((p) => p.user_id === q.get("user_id"));
    return json(page(rows, q));
  }
  if (path === "/admin/plans") return json(PLANS);
  m = path.match(/^\/admin\/plans\/([^/]+)(\/prices)?$/);
  if (m) {
    const plan = PLANS.find((p) => p.id === m[1]);
    if (!m[2]) { Object.assign(plan, b); audit("admin.plan_updated", "plan", plan.id, { fields: Object.keys(b) }); return json(plan); }
    if (method === "GET") return json(PRICES[plan.id] || []);
    const price = { id: uid(), plan_id: plan.id, provider_ids: {}, active: true, valid_from: null, valid_until: null, ...b };
    (PRICES[plan.id] ||= []).push(price);
    audit("admin.price_created", "plan_price", price.id, { amount_minor: b.amount_minor, currency: b.currency });
    return json(price, 201);
  }
  m = path.match(/^\/admin\/prices\/([^/]+)$/);
  if (m) { const p = Object.values(PRICES).flat().find((x) => x.id === m[1]); Object.assign(p, b); audit("admin.price_updated", "plan_price", p.id, b); return json(p); }
  if (path === "/admin/promo-codes" && method === "GET") return json(page(PROMOS, q));
  if (path === "/admin/promo-codes") {
    if (PROMOS.some((p) => p.code.toUpperCase() === b.code.toUpperCase())) return fail(409, "promo_exists", "Такой код уже есть.");
    const p = { id: uid(), percent_off: null, amount_off_minor: null, currency: null, free_days: null, plan_id: null, redemption_count: 0, valid_from: null, active: true, ...b };
    PROMOS.unshift(p); audit("admin.promo_created", "promo_code", p.id, { kind: b.kind }); return json(p, 201);
  }
  m = path.match(/^\/admin\/promo-codes\/([^/]+)$/);
  if (m) { const p = PROMOS.find((x) => x.id === m[1]); Object.assign(p, b); audit("admin.promo_updated", "promo_code", p.id, { fields: Object.keys(b) }); return json(p); }
  if (path === "/admin/vpn/locations" && method === "GET") {
    return json(LOCATIONS.map((l) => {
      const mine = SERVERS.filter((s) => s.location_id === l.id).map(serverOut);
      const healthy = mine.filter((s) => s.accepting).length;
      return { ...l, servers: mine.length, healthy_servers: healthy, visible_to_users: l.enabled && healthy > 0 };
    }));
  }
  if (path === "/admin/vpn/locations") {
    const cc = String(b.country_code || "").toUpperCase();
    if (!/^[A-Z]{2}$/.test(cc)) return fail(422, "validation_error", "country_code: две латинские буквы");
    if (LOCATIONS.some((l) => l.country_code === cc && l.city === b.city)) return fail(409, "location_exists", "This location already exists.");
    const l = { id: uid(), country_code: cc, city: b.city, names: Object.keys(b.names || {}).length ? b.names : { en: b.city || cc }, sort_order: 0, enabled: true };
    LOCATIONS.push(l); audit("admin.location_created", "location", l.id, { country: cc, city: b.city }); return json(l, 201);
  }
  m = path.match(/^\/admin\/vpn\/locations\/([^/]+)$/);
  if (m) { const l = LOCATIONS.find((x) => x.id === m[1]); Object.assign(l, b); audit("admin.location_updated", "location", l.id, b); return json(l); }
  if (path === "/admin/vpn/servers" && method === "GET") return json(SERVERS.map(serverOut));
  if (path === "/admin/vpn/servers") {
    if (!b.ipv4 && !b.ipv6) return fail(422, "validation_error", "give ipv4 and/or ipv6");
    if (SERVERS.some((s) => s.hostname === b.hostname.toLowerCase())) return fail(409, "server_exists", "A server with this hostname already exists.");
    const s = { id: uid(), hostname: b.hostname.toLowerCase(), location_id: b.location_id, ipv4: b.ipv4, ipv6: b.ipv6, endpoint_port: b.endpoint_port, wg_public_key: null, tier: "standard",
      status: "active", max_peers: b.max_peers, peers: 0, beat: 0, revision: 0, applied: null, agent_version: null, agent_errors: [], created_at: iso(Date.now()) };
    SERVERS.push(s); audit("admin.server_created", "server", s.id, { hostname: s.hostname });
    return json({ server: serverOut(s), token: `demo-${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}` }, 201);
  }
  m = path.match(/^\/admin\/vpn\/servers\/([^/]+)(\/rotate-token)?$/);
  if (m) {
    const s = SERVERS.find((x) => x.id === m[1]);
    if (!reasonOk(b)) return needReason();
    if (m[2]) { audit("admin.server_token_rotated", "server", s.id, { reason: b.reason }); return json({ server_id: s.id, token: `demo-${Math.random().toString(36).slice(2)}` }); }
    const before = s.status;
    Object.assign(s, { status: b.status ?? s.status, max_peers: b.max_peers ?? s.max_peers, location_id: b.location_id ?? s.location_id });
    if (s.status === "disabled" && before !== "disabled") s.peers = 0;
    audit("admin.server_updated", "server", s.id, { reason: b.reason, status: [before, s.status] }); return json(serverOut(s));
  }
  if (path === "/admin/games/overview") return json({ enabled: SETTINGS["games.enabled"].value, stakes_enabled: SETTINGS["games.blackjack.stakes_enabled"].value, multiplayer_enabled: SETTINGS["games.multiplayer_enabled"].value, open_rooms: ROOMS.filter((r) => r.status === "open").length, seated_players: 1, rounds_today: 318, bonus_hours_today: { redeem: -24 }, bonus_hours_outstanding: 24 * 17 });
  if (path === "/admin/games/suspicious") return json([{ user_id: USERS[6].id, rounds: 214, wins: 97, win_rate: 0.453, net_hours: 820 }]);
  if (path === "/admin/games/rooms") return json(page(ROOMS, q));
  m = path.match(/^\/admin\/games\/rooms\/([^/]+)\/(pause|resume|close)$/);
  if (m) { const r = ROOMS.find((x) => x.id === m[1]); r.status = { pause: "paused", resume: "open", close: "closed" }[m[2]]; audit(`game.room_${m[2]}`, "game_room", r.id, { reason: b.reason }); return json(r); }
  if (path === "/admin/games/events") return json(page(AUDIT.filter((a) => a.action.startsWith("game.")).map((a) => ({ at: a.created_at, action: a.action, actor_id: a.actor_id, target_id: a.target_id, details: a.details })), q));
  if (path === "/admin/games/players") { const p = GAMEPROFILES[q.get("user_id")]; return json(p ? [{ user_id: q.get("user_id"), pushes: 0, losses: 0, ...p }] : []); }
  m = path.match(/^\/admin\/games\/players\/([^/]+)\/bonus$/);
  if (m) {
    if (!reasonOk(b)) return needReason();
    const p = (GAMEPROFILES[m[1]] ||= { nickname: "Player", rounds: 0, wins: 0, blackjacks: 0, chips: 1000, best_win: 0, balance_hours: 0 });
    p.balance_hours = Math.max(0, p.balance_hours + b.delta_days * 24); audit("game.bonus_admin_adjust", "user", m[1], { delta_days: b.delta_days, reason: b.reason });
    return json({ user_id: m[1], balance_hours: p.balance_hours });
  }
  if (path === "/admin/settings") return json(SETTINGS);
  m = path.match(/^\/admin\/settings\/(.+)$/);
  if (m) { const key = decodeURIComponent(m[1]); const before = SETTINGS[key].value; SETTINGS[key].value = b.value; audit("admin.setting_changed", "setting", key, { before, after: b.value }); return json({ key, value: b.value }); }
  if (path === "/admin/audit-logs") {
    let rows = AUDIT;
    if (q.get("action")) rows = rows.filter((a) => a.action === q.get("action") || a.action.startsWith(`${q.get("action")}.`));
    if (q.get("target_id")) rows = rows.filter((a) => a.target_id === q.get("target_id"));
    return json(page(rows, q));
  }
  const prog = progressRoute(method, path, q, b || {});
  if (prog) return prog;
  return fail(404, "not_found", `Демо: нет ответа для ${method} ${path}`);
}

const realFetch = window.fetch.bind(window);
window.fetch = async (input, init = {}) => {
  const url = new URL(typeof input === "string" ? input : input.url, location.href);
  if (!url.pathname.startsWith("/api/v1/")) return realFetch(input, init);
  await new Promise((r) => setTimeout(r, 90));
  const body = init.body ? JSON.parse(init.body) : undefined;
  try {
    return route(init.method || "GET", url.pathname.slice("/api/v1".length), url.searchParams, body);
  } catch (e) {
    return fail(500, "demo_error", String(e));
  }
};

// a strip that says what this is
const bar = document.createElement("div");
bar.className = "demo-note";
bar.textContent = "Демо на примерных данных: войдите с любой почтой и паролем, код 2FA — любые 6 цифр. Ничего не отправляется на сервер.";
document.body.prepend(bar);
