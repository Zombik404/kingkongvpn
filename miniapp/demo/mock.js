// Clickable demo: stands in for Telegram and the backend with in-memory sample data.
// Bundled in front of src/app.js by demo/build.mjs. Nothing here ships in the real Mini App.
document.documentElement.dataset.appName = "KingKong VPN";

const params = new URLSearchParams(location.search);
const LANG = params.get("lang") === "en" ? "en" : "ru";
const DAY = 86400000;
const LEVELS = [
  { code: "fox", need: 3, days: 7, theme: "lava" },
  { code: "hacker", need: 5, days: 30, theme: "matrix" },
  { code: "ambassador", need: 10, days: 90, theme: "gold" },
  { code: "legend", need: 25, days: 365, theme: "cosmos" },
];
const PLAN = { id: "plan-standard", code: "standard", name: LANG === "ru" ? "Стандарт" : "Standard", device_limit: 5 };
const PRICES = [[1, 500], [3, 1300], [6, 2400], [12, 4200]].map(([m, c]) => ({ id: `price-${m}`, period_unit: "month", period_count: m, currency: "USD", amount_minor: c }));
const LOCATIONS = [
  { id: "loc-de", name: "Frankfurt, DE", country_code: "DE", city: "Frankfurt", servers: 2 },
  { id: "loc-nl", name: "Amsterdam, NL", country_code: "NL", city: "Amsterdam", servers: 1 },
  { id: "loc-fi", name: "Helsinki, FI", country_code: "FI", city: "Helsinki", servers: 1 },
  { id: "loc-pl", name: "Warsaw, PL", country_code: "PL", city: "Warsaw", servers: 1 },
];
const SERVER_KEYS = { "loc-de": "EUh9s5CfWCzvfYC3MBASrLVK2LTAhbZ93GigZtivFFE=", "loc-nl": "KE+pCg5h6U67cwK1K+G5r4GCfxSfSV2ZzI+NuBN29Dk=", "loc-fi": "dsuBH8kl9FCCMHyMD0VFYPL4AxY2JF81pYdiHBZq9I0=", "loc-pl": "Em3SLIioMf8Q/9KjzaAhnBRSfW7ZMM4VLJzh4zB71r8=" };
const SAMPLE_KEYS = ["4mdLx8/HWc6L9T/ihJrrMQ2ZGo/FS1TGVWBCbD5KC2Q=", "V0JFM+J4/Um1cDmg0O/+dC9mErMd49KypudzooekFZ8=", "nLjxOA0sZGV8KQmKqPc91di7Wdusr8B7sFYJQnk7vCE="];

let uid = 100;
const id = (p) => `${p}-${++uid}`;
const iso = (ms) => new Date(ms).toISOString();

function scenario(kind) {
  const now = Date.now();
  const base = {
    kind,
    sub: null,
    devices: [],
    paidFriends: 0,
    invited: 0,
    referredUnpaid: false,
    milestones: new Set(),
    payments: {},
    nextIndex: 20,
  };
  if (kind === "active") {
    base.sub = { start: now - 2 * DAY, end: now + 28 * DAY, provider: "cryptobot" };
    base.devices = [
      ["iPhone", "ios"], ["MacBook", "macos"], ["Pixel 8", "android"],
    ].map(([name, platform], i) => device(name, platform, SAMPLE_KEYS[i], now - (10 - i) * DAY, base));
    base.paidFriends = 9; // one more paying friend → "Gorilla" rank with confetti
    base.invited = 11;
    base.milestones = new Set(["fox", "hacker"]);
  }
  if (kind === "invited") {
    base.referredUnpaid = true;
    base.sub = { start: now - 1 * DAY, end: now + 6 * DAY, provider: "promo" }; // invite code
  }
  return base;
}

function device(name, platform, publicKey, created, st) {
  const n = st.nextIndex++;
  return { id: id("dev"), name, platform, public_key: publicKey, ipv4: `10.64.0.${n}`, ipv6: `fd00:6476:706e::${n.toString(16)}`,
    status: "active", last_handshake_at: null, created_at: iso(created), revoked_at: null };
}

let S = scenario(params.get("scenario") || "active");

// --- tiny deterministic noise for the traffic chart
function rnd(seed) { const x = Math.sin(seed * 12.9898) * 43758.5453; return x - Math.floor(x); }

function usage(days) {
  const now = Date.now();
  const active = S.devices.filter((d) => d.status === "active");
  const series = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now - i * DAY);
    const k = d.getUTCDate() + d.getUTCMonth() * 31;
    const wave = 0.6 + 0.4 * Math.sin(k / 2.3) + rnd(k) * 0.5;
    const has = active.length > 0;
    series.push({ date: d.toISOString().slice(0, 10), download: has ? Math.round(wave * 2.6e9 * active.length) : 0, upload: has ? Math.round(wave * 3.1e8 * active.length) : 0 });
  }
  const totalDown = series.reduce((s, p) => s + p.download, 0), totalUp = series.reduce((s, p) => s + p.upload, 0);
  const weights = [0.47, 0.27, 0.15, 0.07, 0.04];
  const top = active.slice(0, 5).map((d, i) => ({ device_id: d.id, name: d.name, platform: d.platform, status: d.status,
    download: Math.round(totalDown * weights[i]), upload: Math.round(totalUp * weights[i]) }));
  return { days, series, total_download: totalDown, total_upload: totalUp, top_devices: top };
}

function subscriptionOut() {
  const s = S.sub;
  const live = s && s.end > Date.now();
  return {
    entitled: !!live,
    subscription: live ? { id: "sub-1", plan_code: PLAN.code, plan_name: PLAN.name, status: "active", provider: s.provider, auto_renew: false,
      current_period_start: iso(s.start), current_period_end: iso(s.end), cancel_at_period_end: false, grace_until: null, device_limit: PLAN.device_limit } : null,
    trial_available: false,
  };
}

function addDays(days, provider = "promo") {
  const now = Date.now();
  if (S.sub && S.sub.end > now) S.sub.end += days * DAY;
  else S.sub = { start: now, end: now + days * DAY, provider };
}

function referralsOut() {
  const reached = (lv) => S.milestones.has(lv.code);
  const levels = LEVELS.map((lv) => ({ ...lv, reached: reached(lv) }));
  const top = [...levels].reverse().find((lv) => lv.reached);
  return {
    enabled: true, code: "KONG2026", link: "https://t.me/kingkongvpn_bot?start=ref_KONG2026",
    percent_off: 30, bonus_days: 14, invited: S.invited, paid: S.paidFriends,
    my_discount: S.referredUnpaid ? 30 : 0,
    ranks_enabled: true, rank: top ? top.code : "chick", levels,
    next_level: levels.find((lv) => !lv.reached) || null,
    themes: levels.filter((lv) => lv.reached).map((lv) => lv.theme),
  };
}

function friendPaid() {
  S.invited += 1;
  S.paidFriends += 1;
  addDays(14);
  for (const lv of LEVELS) {
    if (S.paidFriends >= lv.need && !S.milestones.has(lv.code)) { S.milestones.add(lv.code); addDays(lv.days); }
  }
}

// --- fake backend --------------------------------------------------------------------
const json = (data, status = 200) => new Response(status === 204 ? null : JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const fail = (status, code, message) => json({ error: { code, message } }, status);
const T = (ru, en) => (LANG === "ru" ? ru : en);

async function backend(method, path, body) {
  const [p, qs] = path.split("?");
  const q = new URLSearchParams(qs || "");
  await new Promise((r) => setTimeout(r, 120)); // feel of a network
  if (p === "/auth/telegram/webapp") return json({ token_type: "bearer", access_token: "demo", expires_in: 900 });
  if (p === "/subscription") return json(subscriptionOut());
  if (p === "/plans") return json([{ ...PLAN, features: {}, server_tiers: ["standard"], prices: PRICES }]);
  if (p === "/referrals") return json(referralsOut());
  if (p === "/referrals/claim") return json(null, 204);
  if (p === "/vpn/usage") return json(usage(Math.min(90, Math.max(1, Number(q.get("days")) || 7))));
  if (p === "/vpn/status") {
    const d = S.devices.find((x) => x.status === "active");
    return json(S.vpnOn ? { protected: true, via: "tunnel", device_id: d?.id ?? null, device_name: d?.name ?? null } : { protected: false, via: null, device_id: null, device_name: null });
  }
  if (p === "/vpn/locations") return S.sub && S.sub.end > Date.now() ? json(LOCATIONS) : fail(403, "no_access", T("Нет активной подписки.", "No active subscription."));
  if (p === "/devices" && method === "GET") {
    const active = S.devices.filter((d) => d.status === "active");
    return json({ devices: active, limit: PLAN.device_limit, active_count: active.length });
  }
  if (p === "/devices" && method === "POST") {
    const active = S.devices.filter((d) => d.status === "active");
    if (active.length >= PLAN.device_limit) return fail(409, "device_limit", T("Достигнут лимит устройств.", "Device limit reached."));
    const d = device(body.name, body.platform, body.public_key, Date.now(), S);
    S.devices.push(d);
    return json(d, 201);
  }
  if (p.startsWith("/devices/") && method === "DELETE") {
    const d = S.devices.find((x) => x.id === p.split("/")[2]);
    if (d) { d.status = "revoked"; d.revoked_at = iso(Date.now()); }
    return json(null, 204);
  }
  if (p === "/vpn/connect") {
    const d = S.devices.find((x) => x.id === body.device_id);
    const loc = LOCATIONS.find((l) => l.id === body.location_id) || LOCATIONS[0];
    if (!d) return fail(404, "not_found", T("Устройство не найдено.", "Device not found."));
    const host = { DE: "203.0.113.10", NL: "203.0.113.20", FI: "203.0.113.30", PL: "203.0.113.40" }[loc.country_code];
    return json({ server_id: `srv-${loc.id}`, location_id: loc.id, server_public_key: SERVER_KEYS[loc.id], endpoint: `${host}:51820`,
      addresses: [`${d.ipv4}/32`, `${d.ipv6}/128`], allowed_ips: ["0.0.0.0/0", "::/0"], dns: ["10.64.0.1"], persistent_keepalive: 25 });
  }
  if (p === "/promo/redeem") {
    const code = String(body.code || "").trim().toUpperCase();
    if (!/^INV-[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(code)) return fail(404, "invalid_code", T("Код не найден. В демо подойдёт любой вида INV-XXXX-XXXX, например INV-KONG-2026.", "Code not found. In the demo any INV-XXXX-XXXX works, e.g. INV-KONG-2026."));
    addDays(30);
    return json(subscriptionOut());
  }
  if (p === "/payments/checkout") {
    const price = PRICES.find((x) => x.id === body.price_id);
    const pct = S.referredUnpaid ? 30 : 0;
    const pay = { id: id("pay"), provider: "cryptobot", status: "pending", amount_minor: price.amount_minor - Math.floor((price.amount_minor * pct) / 100),
      currency: "USD", discount: pct ? "referral" : null, checkout_url: "https://t.me/CryptoBot?start=demo-invoice", plan_code: PLAN.code,
      period_unit: "month", period_count: price.period_count, created_at: iso(Date.now()), expires_at: iso(Date.now() + 3600e3), paid_at: null, failure_reason: null };
    S.payments[pay.id] = pay;
    S.lastPayment = pay.id;
    return json(pay);
  }
  if (p.startsWith("/payments/")) {
    const pay = S.payments[p.split("/")[2]];
    return pay ? json(pay) : fail(404, "not_found", "Not found");
  }
  return fail(404, "not_found", `Demo: no route for ${method} ${p}`);
}

const realFetch = window.fetch.bind(window);
window.fetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  const m = url.match(/\/api\/v1(\/[^#]*)$/);
  if (!m) return realFetch(input, init);
  const body = init.body ? JSON.parse(init.body) : undefined;
  return backend((init.method || "GET").toUpperCase(), m[1], body);
};

// --- fake Telegram ---------------------------------------------------------------------
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

function sheet(title, text, buttons) {
  const wrap = el("div", "demo-sheet-wrap");
  const box = el("div", "demo-sheet card");
  box.append(el("div", "card-title", title), el("p", "muted", text));
  for (const [label, cls, fn] of buttons) {
    const b = el("button", `${cls} wide`, label);
    b.addEventListener("click", () => { wrap.remove(); fn?.(); });
    box.append(b);
  }
  wrap.append(box);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) wrap.remove(); });
  document.body.append(wrap);
}

function toast(msg) {
  const t = el("div", "demo-toast", msg);
  document.body.append(t);
  setTimeout(() => t.classList.add("out"), 2600);
  setTimeout(() => t.remove(), 3100);
}

let mainBar = null;
const MainButton = {
  _text: "",
  setText(t) { this._text = t; if (mainBar) mainBar.textContent = t; },
  show() { if (!mainBar) { mainBar = el("div", "demo-mainbar", this._text); document.body.append(mainBar); } },
  hide() { mainBar?.remove(); mainBar = null; },
  showProgress() {}, hideProgress() {},
};

function openTelegramLink(url) {
  if (url.includes("CryptoBot")) {
    const pay = S.payments[S.lastPayment];
    const sum = pay ? `${(pay.amount_minor / 100).toFixed(2)} $` : "";
    sheet("@CryptoBot", T(`Здесь в Telegram откроется счёт на ${sum} — оплата в Gram или USDC. В демо деньги не списываются.`, `Telegram opens a ${sum} invoice here — pay in Gram or USDC. No money moves in the demo.`), [
      [T("Оплатить (демо)", "Pay (demo)"), "primary", () => {
        if (!pay) return;
        pay.status = "succeeded"; pay.paid_at = iso(Date.now());
        addDays(pay.period_count * 30, "cryptobot");
        S.referredUnpaid = false;
        toast(T("Оплата прошла. Приложение заметит её за несколько секунд.", "Paid. The app picks it up within a few seconds."));
      }],
      [T("Отменить счёт", "Cancel invoice"), "ghost", () => { if (pay) { pay.status = "failed"; pay.failure_reason = "expired"; } }],
    ]);
    return;
  }
  if (url.includes("/share/url")) {
    toast(T("Здесь Telegram предложит выбрать чат, куда отправить ссылку.", "Telegram asks which chat to send the link to."));
    return;
  }
  openLink(url);
}

function openLink(url) {
  const a = document.createElement("a");
  a.href = url; a.target = "_blank"; a.rel = "noopener";
  document.body.append(a); a.click(); a.remove();
}

window.Telegram = {
  WebApp: {
    initData: "demo",
    initDataUnsafe: { user: { id: 1, first_name: "Demo", language_code: LANG } },
    ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {},
    showAlert(msg) { toast(msg); },
    showConfirm(msg, cb) { sheet(T("Подтвердите", "Confirm"), msg, [[T("Да", "Yes"), "primary", () => cb(true)], [T("Отмена", "Cancel"), "ghost", () => cb(false)]]); },
    openLink, openTelegramLink,
    BackButton: { show() {}, hide() {}, onClick() {} },
    MainButton,
  },
};

// Start each visit at the "Jaguar" rank already celebrated, so the first "+1 friend paid" shows
// the next rank's confetti instead of covering the app on load.
function resetLocal() {
  try {
    localStorage.setItem("vpnhub.rank.seen", "hacker");
    localStorage.removeItem("vpnhub.theme");
  } catch { /* storage unavailable: confetti may show once on load */ }
}
resetLocal();

// Downloads are blocked inside the demo frame; say so instead of doing nothing.
const nativeClick = HTMLAnchorElement.prototype.click;
HTMLAnchorElement.prototype.click = function click() {
  if (this.hasAttribute("download")) {
    toast(T("В демо браузер не даёт скачать файл. В Telegram здесь сохранится .conf — пока используйте QR-код или «Скопировать текст».", "The demo frame blocks downloads. In Telegram this saves the .conf file — use the QR code or “Copy text” here."));
    return;
  }
  nativeClick.call(this);
};

// --- demo panel -----------------------------------------------------------------------
const refresh = () => window.dispatchEvent(new Event("app:refresh"));
function panel() {
  const bar = el("div", "demo-bar");
  const label = el("span", "demo-label", T("Демо", "Demo"));
  const choose = (kind) => () => { S = scenario(kind); resetLocal(); refresh(); highlight(); vpnLabel(); window.dispatchEvent(new Event("app:vpn-check")); };
  const btns = [
    [T("С подпиской", "Subscribed"), "active"],
    [T("Новичок", "Newcomer"), "new"],
    [T("По ссылке друга", "Invited"), "invited"],
  ].map(([text, kind]) => { const b = el("button", "demo-chip", text); b.dataset.kind = kind; b.addEventListener("click", choose(kind)); return b; });
  const friend = el("button", "demo-chip hot", T("+1 друг оплатил", "+1 friend paid"));
  friend.addEventListener("click", () => { friendPaid(); toast(T(`Друг оплатил подписку: вам +14 дней. Оплативших друзей: ${S.paidFriends}.`, `A friend paid: +14 days for you. Paying friends: ${S.paidFriends}.`)); refresh(); });
  const vpn = el("button", "demo-chip vpn", "");
  const vpnLabel = () => { vpn.textContent = S.vpnOn ? T("VPN: вкл", "VPN: on") : T("VPN: выкл", "VPN: off"); vpn.classList.toggle("on", !!S.vpnOn); };
  vpn.addEventListener("click", () => {
    if (!S.sub || S.sub.end < Date.now()) { toast(T("Сначала активируйте доступ — у новичка нет подписки.", "Activate access first — the newcomer has no subscription.")); return; }
    S.vpnOn = !S.vpnOn; vpnLabel();
    window.dispatchEvent(new Event("app:vpn-check"));
  });
  vpnLabel();
  const lang = el("a", "demo-chip", LANG === "ru" ? "EN" : "RU");
  lang.href = `?lang=${LANG === "ru" ? "en" : "ru"}`;
  function highlight() { for (const b of btns) b.classList.toggle("on", b.dataset.kind === S.kind); }
  const row1 = el("div", "demo-row"), row2 = el("div", "demo-row");
  row1.append(label, ...btns);
  row2.append(vpn, friend, lang);
  bar.append(row1, row2);
  highlight();
  document.body.append(bar);
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", panel); else panel();
