// KingKong VPN — Telegram Mini App. User data is inserted with textContent only.
import qrcode from "qrcode-generator";
import { areaChart, formatBytes, progressRing, ringsChart, RING_COLORS } from "./charts.js";
import { initGames } from "./games.js";
import { enter, mountJungle, setOvergrowth, swing, wreath } from "./jungle.js";
import { makeT, pickLang } from "./i18n.js";
import { buildConfig, generateKeyPair, toFragment, tunnelName } from "./wg.js";

const API = "/api/v1";
const APP_NAME = document.documentElement.dataset.appName || "KingKong VPN"; // brand: one place (index.html)
const tg = window.Telegram && window.Telegram.WebApp;
const lang = pickLang(tg?.initDataUnsafe?.user?.language_code);
const t = makeT(lang);
const root = document.getElementById("app");
const NS = "http://www.w3.org/2000/svg";

const APPS = [
  ["Android", "https://play.google.com/store/apps/details?id=com.wireguard.android"],
  ["iPhone / iPad", "https://apps.apple.com/app/wireguard/id1441195209"],
  ["Windows / macOS / Linux", "https://www.wireguard.com/install/"],
];
const PLATFORMS = [
  ["android", "Android"], ["ios", "iPhone / iPad"], ["windows", "Windows"],
  ["macos", "macOS"], ["linux", "Linux"], ["router", "Router"], ["other", "Other"],
];
// 24×24 stroke icons (own drawings)
const ICONS = {
  globe: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18Z M3.5 9h17 M3.5 15h17 M12 3c2.4 2.6 3.6 5.6 3.6 9s-1.2 6.4-3.6 9 M12 3c-2.4 2.6-3.6 5.6-3.6 9s1.2 6.4 3.6 9",
  card: "M3 6.5h18v11H3z M3 10.5h18 M7 14.5h4",
  upgrade: "M12 18V6 M6.5 11.5 12 6l5.5 5.5 M6 21h12",
  friends: "M9 11a3.5 3.5 0 1 0 0-7a3.5 3.5 0 0 0 0 7Z M2.5 20c.8-3.4 3.4-5.5 6.5-5.5s5.7 2.1 6.5 5.5 M16 4.6a3.3 3.3 0 0 1 0 6.2 M17.6 14.8c2 .7 3.4 2.5 3.9 5.2",
  devices: "M8 3h6.5a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z M10.5 18h1.5 M18.5 8h2a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1h-2",
  help: "M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18Z M9.6 9.4a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.5v.7 M12 17h.01",
  ticket: "M3 8.5a2 2 0 0 0 2-2h14a2 2 0 0 0 2 2v2a1.5 1.5 0 0 0 0 3v2a2 2 0 0 0-2 2H5a2 2 0 0 0-2-2v-2a1.5 1.5 0 0 0 0-3Z M14 6.5v11",
  copy: "M9 9h10v11H9z M5 15V4h10",
  share: "M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7 M12 3v12 M7.5 7.5 12 3l4.5 4.5",
  trash: "M4 7h16 M9 7V4h6v3 M6.5 7l1 13h9l1-13",
  cards: "M5 7.5h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1Z M9 4.5h9.5a1 1 0 0 1 1 1V17 M7.5 14l2 2.6 2-2.6-2-2.6Z",
};

let token = null;
let state = { sub: null, devices: null, plans: null, ref: null, usage: null, days: 7 };
let backHandler = null;

// ------------------------------------------------------------------ helpers
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

function icon(name, cls = "ic") {
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(NS, "path");
  p.setAttribute("d", ICONS[name]);
  svg.append(p);
  return svg;
}

function logo() {
  return h("img", { class: "logo-mark", src: "assets/logo.png", alt: "", width: 44, height: 44 });
}

function brand() {
  // "KingKong VPN" → "KINGKONG" + accent "VPN"
  const [first, ...rest] = APP_NAME.split(" ");
  return h("header", { class: "brand" }, logo(),
    h("span", { class: "word" }, first, rest.length ? h("span", { class: "word-accent" }, ` ${rest.join(" ")}`) : null));
}

const locale = lang === "ru" ? "ru-RU" : "en-GB";
const fmtDate = (iso) => new Date(iso).toLocaleDateString(locale, { day: "numeric", month: "long" });
const fmtShort = (iso) => new Date(iso).toLocaleDateString(locale, { day: "2-digit", month: "2-digit" });
const fmtPrice = (minor, cur) =>
  new Intl.NumberFormat(lang === "ru" ? "ru-RU" : "en-US", { style: "currency", currency: cur, maximumFractionDigits: minor % 100 ? 2 : 0 }).format(minor / 100);
const flag = (cc) => String(cc || "").toUpperCase().replace(/[A-Z]/g, (c) => String.fromCodePoint(127397 + c.charCodeAt(0)));

function toast(msg) {
  if (tg?.showAlert) tg.showAlert(msg);
  else alert(msg); // eslint-disable-line no-alert
}

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* storage unavailable */ } },
};
// Private keys stay on this device only (never sent anywhere); used to re-issue a config
// when moving a device to another country.
const keyStore = {
  get: (id) => store.get(`vpnhub.key.${id}`),
  set: (id, k) => store.set(`vpnhub.key.${id}`, k),
  del: (id) => store.del(`vpnhub.key.${id}`),
};

// ------------------------------------------------------------------ themes & ranks
const THEME_BG = { default: "#040805", lava: "#0d0504", matrix: "#000000", gold: "#0a0904", cosmos: "#07051a" };
const RANK_EMOJI = { chick: "🐒", fox: "🦜", hacker: "🐆", ambassador: "🦍", legend: "👑" };

function applyTheme(name) {
  const theme = THEME_BG[name] ? name : "default";
  if (theme === "default") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
  try { tg?.setHeaderColor?.(THEME_BG[theme]); tg?.setBackgroundColor?.(THEME_BG[theme]); } catch { /* older clients */ }
}
// A theme is cosmetic and stored on this device; the server says which ones are unlocked.
const unlockedThemes = () => ["default", ...(state.ref?.themes || [])];
function syncTheme() {
  const want = store.get("vpnhub.theme") || "default";
  applyTheme(unlockedThemes().includes(want) ? want : "default");
}
function chooseTheme(name) {
  store.set("vpnhub.theme", name);
  applyTheme(name);
}

function celebrate(level) {
  const colors = ["var(--r0)", "var(--r1)", "var(--r2)", "var(--r3)", "var(--r4)", "#ffffff"];
  const bits = Array.from({ length: 70 }, (_, i) => {
    const b = h("span", { class: "bit" });
    b.style.setProperty("--x", `${Math.random() * 100}%`);
    b.style.setProperty("--col", colors[i % colors.length]);
    b.style.setProperty("--rot", `${Math.round(Math.random() * 360)}deg`);
    b.style.setProperty("--dur", `${(2.2 + Math.random() * 2).toFixed(2)}s`);
    b.style.setProperty("--delay", `${(Math.random() * 0.8).toFixed(2)}s`);
    return b;
  });
  const close = () => overlay.remove();
  const overlay = h("div", { class: "party", role: "dialog", "aria-label": t("newRank") },
    ...bits,
    h("section", { class: "card glow" },
      h("span", { class: "rank-emoji" }, RANK_EMOJI[level.code] || "🎉"),
      h("div", { class: "lbl" }, t("newRank")),
      h("div", { class: "rank-name" }, t("ranks")[level.code] || level.code),
      h("p", {}, t("newRankGift", { d: level.days, theme: t("themes")[level.theme] })),
      h("button", { class: "primary wide", onclick: () => { chooseTheme(level.theme); close(); } }, t("useTheme")),
      h("button", { class: "ghost wide", onclick: close }, t("cool"))));
  document.body.append(overlay);
}

// Celebrate each newly reached rank once per device.
function maybeCelebrate() {
  const r = state.ref;
  if (!r?.ranks_enabled || !r.rank || r.rank === "chick") return;
  if (store.get("vpnhub.rank.seen") === r.rank) return;
  store.set("vpnhub.rank.seen", r.rank);
  const level = r.levels.find((lv) => lv.code === r.rank);
  if (level) celebrate(level);
}

async function login() {
  const r = await fetch(`${API}/auth/telegram/webapp`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ init_data: tg.initData }),
  });
  if (!r.ok) throw new Error(t("loginFailed"));
  token = (await r.json()).access_token;
}

async function api(path, { method = "GET", body } = {}, retry = true) {
  const r = await fetch(API + path, {
    method,
    headers: { Authorization: `Bearer ${token}`, "Accept-Language": lang, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401 && retry) {
    await login();
    return api(path, { method, body }, false);
  }
  if (r.status === 204) return null;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const msg = data.error?.message || (Array.isArray(data.detail) && data.detail[0]?.msg) || `HTTP ${r.status}`;
    const err = new Error(msg);
    err.code = data.error?.code;
    throw err;
  }
  return data;
}

function setBack(fn) {
  backHandler = fn;
  if (!tg?.BackButton) return;
  if (fn) tg.BackButton.show();
  else tg.BackButton.hide();
}

let screen = null; // "home" | "page" — decides which way the monkey swings

function page(title, ...content) {
  window.scrollTo(0, 0);
  swing("fwd", root);
  screen = "page";
  root.replaceChildren(
    h("header", { class: "bar" },
      h("button", { class: "ghost back", onclick: () => goHome(), "aria-label": t("back") }, "‹"),
      h("h1", {}, title)),
    ...content.filter(Boolean));
  setBack(goHome);
}

// ------------------------------------------------------------------ VPN on → overgrowth
// The VPN is switched on in the WireGuard app; we notice it because this app's own requests
// then arrive through our server (GET /vpn/status). Checked on open, every few seconds while
// visible, and right away when the user comes back from the WireGuard app.
async function checkVpn() {
  try {
    const s = await api("/vpn/status");
    setOvergrowth(s.protected, { title: t("ogTitle"), sub: s.device_name ? t("ogVia", { name: s.device_name }) : t("ogOn") });
  } catch { /* offline or logged out: leave the screen as it is */ }
}
let vpnTimer = null;
function watchVpn() {
  if (vpnTimer) return;
  const tick = () => { if (document.visibilityState === "visible") checkVpn(); };
  vpnTimer = setInterval(tick, 6000);
  document.addEventListener("visibilitychange", tick);
  window.addEventListener("app:vpn-check", checkVpn); // the demo's VPN switch
  checkVpn();
}

// ------------------------------------------------------------------ data
async function loadAll() {
  const [sub, devices, plans, ref, usage] = await Promise.all([
    api("/subscription"), api("/devices"), api("/plans"),
    api("/referrals").catch(() => null), api(`/vpn/usage?days=${state.days}`),
  ]);
  Object.assign(state, { sub, devices, plans, ref, usage });
  syncTheme();
}

// ------------------------------------------------------------------ home
async function goHome() {
  games.closeTable();
  setBack(null);
  const back = screen === "page"; // coming back from a page: the monkey flies the other way
  if (back) swing("back", null);
  screen = "home";
  if (!root.children.length) root.replaceChildren(h("p", { class: "muted center pad" }, t("loading")));
  await loadAll();
  window.scrollTo(0, 0);
  root.replaceChildren(...[
    brand(),
    wheel(),
    state.sub.entitled ? null : inviteCard(),
    dashboard(),
  ].filter(Boolean));
  if (back) enter("back", root);
  maybeCelebrate();
}

function periodInfo() {
  const s = state.sub.subscription;
  if (!s) return { days: 0, frac: 0 };
  const end = new Date(s.status === "grace" && s.grace_until ? s.grace_until : s.current_period_end);
  const start = new Date(s.current_period_start);
  const now = Date.now();
  const days = Math.max(0, Math.ceil((end - now) / 86400000));
  const frac = Math.min(1, Math.max(0, (end - now) / Math.max(1, end - start)));
  return { days, frac, end };
}

function wheel() {
  const s = state.sub.subscription;
  const { days, frac } = periodInfo();
  const center = h("div", { class: "hub" },
    progressRing(frac),
    h("div", { class: "hub-text" },
      s ? [h("div", { class: "hub-kicker" }, t("left")),
           h("div", { class: "hub-num" }, String(days)),
           h("div", { class: "hub-unit" }, t("daysLeft")(days))]
        : [h("div", { class: "hub-kicker" }, "VPN"), h("div", { class: "hub-off" }, t("noAccess"))],
      s ? h("div", { class: "hub-sub" }, s.status === "grace" ? t("graceNote", { date: fmtDate(s.grace_until) }) : `${s.plan_name} · ${t("activeUntil", { date: fmtDate(s.current_period_end) })}`) : null));
  const items = [
    ["globe", t("wCountry"), countryScreen],
    ["card", t("wPay"), () => plansScreen(false)],
    ["upgrade", t("wUpgrade"), () => plansScreen(true)],
    ["friends", t("wReferral"), referralScreen],
    ["devices", t("wDevices"), devicesScreen],
    ["help", t("wHelp"), helpScreen],
    ["cards", t("wGames"), () => games.gamesScreen()],
  ];
  const spokes = items.map(([ic, label, fn], i) => {
    const angle = -90 + i * (360 / items.length);
    // came via a friend's link and hasn't paid yet → show the first-payment discount on "Pay"
    const rank = state.ref?.ranks_enabled && state.ref.rank !== "chick" ? state.ref.rank : null;
    const badge = ic === "card" && state.ref?.my_discount ? h("span", { class: "badge" }, `−${state.ref.my_discount}%`)
      : ic === "friends" && rank ? h("span", { class: "badge emoji", title: t("ranks")[rank] }, RANK_EMOJI[rank]) : null;
    return h("button", { class: "spoke", "data-angle": angle, onclick: fn, "aria-label": label },
      h("span", { class: "spoke-ic" }, icon(ic)), h("span", { class: "spoke-label" }, label), badge);
  });
  const w = h("section", { class: "wheel" }, wreath(), center, ...spokes);
  // place spokes on the circle (CSSOM custom properties — allowed by our strict CSP)
  for (const b of spokes) {
    const a = (Number(b.dataset.angle) * Math.PI) / 180;
    b.style.setProperty("--x", `${(50 + 40 * Math.cos(a)).toFixed(2)}%`);
    b.style.setProperty("--y", `${(50 + 40 * Math.sin(a)).toFixed(2)}%`);
  }
  return w;
}

function inviteCard() {
  const input = h("input", { type: "text", placeholder: t("invitePlaceholder"), autocomplete: "off", maxlength: 40, autocapitalize: "characters" });
  const fromLink = new URLSearchParams(location.search).get("invite");
  if (fromLink && /^INV-[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(fromLink)) input.value = fromLink;
  const btn = h("button", {
    class: "primary",
    onclick: async () => {
      const code = input.value.trim();
      if (!code) return;
      btn.disabled = true;
      try {
        await api("/promo/redeem", { method: "POST", body: { code } });
        toast(t("redeemed"));
        await goHome();
      } catch (e) {
        toast(t("error", { msg: e.message }));
        btn.disabled = false;
      }
    },
  }, t("redeem"));
  return h("section", { class: "card glow" },
    h("div", { class: "card-title" }, icon("ticket"), t("invite")),
    h("p", { class: "muted" }, t("inviteHelp")),
    h("div", { class: "row" }, input, btn));
}

function dashboard() {
  const u = state.usage;
  const total = u.total_download + u.total_upload;
  const seg = h("div", { class: "seg" }, [7, 30, 90].map((d) =>
    h("button", { class: d === state.days ? "on" : "", onclick: async () => { state.days = d; await goHome(); } }, t(`d${d}`))));
  const share = total ? u.total_download / total : 0;
  const top = u.top_devices;
  const legend = top.map((d, i) =>
    h("li", {}, h("i", { class: "dot", "data-c": i }),
      h("span", { class: "lg-name" }, d.name),
      h("span", { class: "lg-val" }, formatBytes(d.download + d.upload, lang))));
  const card = h("section", { class: "card dash" },
    h("div", { class: "card-title" }, t("traffic"), seg),
    h("div", { class: "split" },
      h("div", {}, h("div", { class: "lbl" }, t("download")), h("div", { class: "val hot" }, formatBytes(u.total_download, lang))),
      h("div", { class: "right" }, h("div", { class: "lbl" }, t("upload")), h("div", { class: "val warm" }, formatBytes(u.total_upload, lang)))),
    h("div", { class: "bar-track" }, h("div", { class: "bar-fill", "data-w": Math.round(share * 100) })),
    h("div", { class: "total" }, h("div", { class: "lbl center" }, t("totalTraffic")), h("div", { class: "big center" }, formatBytes(total, lang))),
    total ? areaChart(u.series, { labels: u.series.map((p) => fmtShort(p.date)) }) : h("p", { class: "muted center pad" }, t("noTraffic")),
    top.length ? h("div", { class: "card-sub" }, t("topDevices")) : null,
    top.length ? h("div", { class: "rings-wrap" }, ringsChart(top.map((d) => ({ value: d.download + d.upload }))), h("ul", { class: "legend" }, legend)) : null,
    h("p", { class: "muted small note" }, t("appsNote")));
  card.querySelectorAll(".bar-fill").forEach((b) => b.style.setProperty("--w", `${b.dataset.w}%`));
  card.querySelectorAll(".dot").forEach((d) => d.style.setProperty("--c", RING_COLORS[Number(d.dataset.c)]));
  return card;
}

// ------------------------------------------------------------------ plans & payment
function monthsOf(p) {
  return p.period_unit === "year" ? 12 * p.period_count : p.period_unit === "month" ? p.period_count : p.period_count / 30;
}

function plansScreen(upgrade) {
  const s = state.sub.subscription;
  const refPct = state.ref?.my_discount || 0;
  const rows = [];
  for (const plan of state.plans) {
    const base = plan.prices.find((p) => p.period_unit === "month" && p.period_count === 1);
    const perMonth = (p) => p.amount_minor / monthsOf(p);
    const best = [...plan.prices].sort((a, b) => perMonth(a) - perMonth(b))[0];
    for (const price of [...plan.prices].sort((a, b) => monthsOf(a) - monthsOf(b))) {
      const saving = base && price !== base ? Math.round((1 - perMonth(price) / base.amount_minor) * 100) : 0;
      const final = refPct ? price.amount_minor - Math.floor((price.amount_minor * refPct) / 100) : price.amount_minor;
      rows.push(h("button", { class: `plan ${upgrade && price === best ? "best" : ""}`, onclick: (ev) => startPayment(price, ev.currentTarget) },
        h("div", { class: "plan-main" },
          h("div", { class: "plan-period" }, t("months")(Math.round(monthsOf(price)))),
          h("div", { class: "plan-meta" }, `${plan.name} · ${t("devicesIncluded", { n: plan.device_limit })}`),
          upgrade ? h("div", { class: "plan-meta" }, t("perMonth", { price: fmtPrice(Math.round(perMonth(price)), price.currency) })) : null),
        h("div", { class: "plan-price" },
          refPct ? h("s", {}, fmtPrice(price.amount_minor, price.currency)) : null,
          h("strong", {}, fmtPrice(final, price.currency)),
          saving > 0 ? h("span", { class: "pill" }, t("save", { p: saving })) : null,
          upgrade && price === best ? h("span", { class: "pill solid" }, t("bestValue")) : null)));
    }
  }
  page(upgrade ? t("upgradeTitle") : t("payTitle"),
    s ? h("p", { class: "muted pad-x" }, t("currentPlan", { plan: s.plan_name, date: fmtDate(s.current_period_end) })) : null,
    refPct ? h("div", { class: "card glow small" }, t("refDiscount", { p: refPct })) : null,
    h("section", { class: "card" }, ...rows),
    h("p", { class: "muted small pad-x" }, t("payHint")));
}

async function startPayment(price, btn) {
  btn.disabled = true;
  try {
    const p = await api("/payments/checkout", { method: "POST", body: { price_id: price.id } });
    if (p.checkout_url?.startsWith("https://t.me/") && tg.openTelegramLink) tg.openTelegramLink(p.checkout_url);
    else tg.openLink(p.checkout_url);
    await waitForPayment(p.id);
  } catch (e) {
    toast(t("error", { msg: e.message }));
  } finally {
    btn.disabled = false;
  }
}

async function waitForPayment(id) {
  tg.MainButton?.setText(t("waitingPayment"));
  tg.MainButton?.showProgress();
  tg.MainButton?.show();
  try {
    const until = Date.now() + 15 * 60 * 1000;
    while (Date.now() < until) {
      await new Promise((r) => setTimeout(r, 5000));
      const p = await api(`/payments/${id}?refresh=true`);
      if (p.status === "succeeded") {
        toast(t("paid"));
        await goHome();
        return;
      }
      if (p.status === "failed") {
        toast(t("paymentFailed"));
        return;
      }
    }
  } finally {
    tg.MainButton?.hideProgress();
    tg.MainButton?.hide();
  }
}

// ------------------------------------------------------------------ referral
function referralScreen() {
  const r = state.ref;
  const link = r?.link;
  const copyBtn = h("button", { class: "primary wide", onclick: async () => {
    try { await navigator.clipboard.writeText(link); copyBtn.textContent = t("copied"); } catch { toast(link); }
  } }, icon("copy", "ic sm"), t("copyLink"));
  const shareBtn = h("button", { class: "secondary wide", onclick: () => {
    const url = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(t("shareText", { p: r?.percent_off ?? 30, app: APP_NAME }))}`;
    tg.openTelegramLink ? tg.openTelegramLink(url) : tg.openLink(url);
  } }, icon("share", "ic sm"), t("share"));
  const pct = r?.percent_off ?? 30;
  const days = r?.bonus_days ?? 0;
  page(t("refTitle"),
    h("section", { class: "card glow" },
      h("div", { class: "promo-num" }, days ? t("refBonus", { d: days }) : `−${pct}%`),
      h("p", {}, days ? t("refText", { p: pct, d: days }) : t("refTextNoDays", { p: pct }))),
    h("section", { class: "card ref-count" },
      h("div", { class: "lbl" }, t("refCount")),
      h("div", { class: "big" }, String(r?.invited ?? 0))),
    link
      ? h("section", { class: "card" }, h("div", { class: "linkbox" }, link), copyBtn, shareBtn)
      : h("p", { class: "muted pad-x" }, t("refNoBot")),
    r?.ranks_enabled ? rankCard(r) : null,
    r?.ranks_enabled ? ladderCard(r) : null,
    themesCard());
}

function rankCard(r) {
  const nxt = r.next_level;
  const prevNeed = [...r.levels].reverse().find((lv) => lv.reached)?.need || 0;
  const pct = nxt ? Math.round((100 * (r.paid - prevNeed)) / Math.max(1, nxt.need - prevNeed)) : 100;
  const card = h("section", { class: "card glow rank-card" },
    h("span", { class: "rank-emoji" }, RANK_EMOJI[r.rank] || "🐒"),
    h("div", { class: "lbl" }, t("rankTitle")),
    h("div", { class: "rank-name" }, t("ranks")[r.rank] || r.rank),
    h("div", { class: "rank-next" },
      h("p", { class: "small muted" }, t("rankPaid", { n: r.paid })),
      h("div", { class: "bar-track" }, h("div", { class: "bar-fill", "data-w": Math.max(0, Math.min(100, pct)) })),
      h("p", { class: "small" }, nxt
        ? t("rankNext", { left: t("friendsN")(nxt.need - r.paid), rank: t("ranks")[nxt.code], d: nxt.days, theme: t("themes")[nxt.theme] })
        : t("rankMax", { app: APP_NAME }))));
  card.querySelectorAll(".bar-fill").forEach((b) => b.style.setProperty("--w", `${b.dataset.w}%`));
  return card;
}

function ladderCard(r) {
  return h("section", { class: "card" },
    h("div", { class: "card-title" }, t("ladderTitle")),
    h("ul", { class: "list ladder" }, ...r.levels.map((lv) =>
      h("li", { class: lv.reached ? "done" : "locked" },
        h("span", { class: "lv-emoji" }, RANK_EMOJI[lv.code]),
        h("div", {},
          h("strong", {}, t("ranks")[lv.code]),
          h("div", { class: "small muted" }, t("ladderRow", { n: t("friendsN")(lv.need), d: lv.days, theme: t("themes")[lv.theme] }))),
        h("span", { class: "lv-state" }, lv.reached ? "✓" : "🔒")))));
}

function themesCard() {
  const box = h("div", { class: "chips" });
  const render = () => {
    const unlocked = unlockedThemes();
    const current = document.documentElement.getAttribute("data-theme") || "default";
    box.replaceChildren(...Object.keys(THEME_BG).map((name) => {
      const open = unlocked.includes(name);
      return h("button", { class: `chip ${name === current ? "on" : ""}`, disabled: !open, onclick: () => { chooseTheme(name); render(); } },
        h("span", { class: `sw sw-${name}` }), t("themes")[name], open ? null : " 🔒");
    }));
  };
  render();
  return h("section", { class: "card" },
    h("div", { class: "card-title" }, t("themesTitle")),
    box,
    h("p", { class: "small muted" }, t("themesHint")));
}

// ------------------------------------------------------------------ country
async function countryScreen() {
  if (!state.sub.entitled) return toast(t("needAccess"));
  const locations = await api("/vpn/locations");
  if (!locations.length) return toast(t("noLocations"));
  const chosen = store.get("vpnhub.location") || locations[0].id;
  const list = h("section", { class: "card" });
  const movable = state.devices.devices.filter((d) => keyStore.get(d.id));
  const render = (sel) => {
    list.replaceChildren(...locations.map((l) =>
      h("button", { class: `country ${l.id === sel ? "on" : ""}`, onclick: () => { store.set("vpnhub.location", l.id); render(l.id); } },
        h("span", { class: "flag" }, flag(l.country_code)), h("span", {}, l.name), l.id === sel ? h("span", { class: "check" }, "●") : null)),
    h("button", { class: "primary wide", onclick: () => addDeviceForm(sel) }, t("newHere", { c: (locations.find((l) => l.id === sel) || {}).name })),
    ...movable.map((d) => h("button", { class: "secondary wide", onclick: () => moveDevice(d, sel, locations) }, `${t("moveHere")}: ${d.name}`)));
  };
  render(chosen);
  page(t("countryTitle"), h("p", { class: "muted pad-x" }, t("countryHint")), list);
}

async function moveDevice(device, locationId, locations) {
  try {
    const info = await api("/vpn/connect", { method: "POST", body: { device_id: device.id, location_id: locationId } });
    const cc = (locations.find((l) => l.id === locationId) || {}).country_code;
    toast(t("moved"));
    showResult(buildConfig(keyStore.get(device.id), info), tunnelName(APP_NAME, cc));
  } catch (e) {
    toast(t("error", { msg: e.message }));
  }
}

// ------------------------------------------------------------------ devices
function devicesScreen() {
  const list = state.devices;
  const items = list.devices.map((d) =>
    h("li", { class: "device" },
      h("span", { class: "dev-ic" }, icon("devices")),
      h("div", { class: "dev-main" },
        h("strong", {}, d.name),
        h("div", { class: "muted small" }, `${d.platform} · ${d.ipv4 || ""}`),
        h("div", { class: "muted small" }, d.last_handshake_at ? t("lastSeen", { date: fmtDate(d.last_handshake_at) }) : t("never"))),
      h("button", { class: "ghost danger", "aria-label": t("remove"), onclick: () => removeDevice(d) }, icon("trash"))));
  page(t("devices"),
    h("section", { class: "card" },
      h("div", { class: "card-title" }, t("devices"), h("span", { class: "muted small" }, t("deviceLimit", { n: list.active_count, limit: list.limit }))),
      items.length ? h("ul", { class: "list" }, items) : h("p", { class: "muted" }, t("noDevices")),
      h("button", { class: "primary wide", disabled: list.active_count >= list.limit || undefined, onclick: () => addDeviceForm(store.get("vpnhub.location")) }, t("addDevice"))));
}

function removeDevice(d) {
  const go = async (ok) => {
    if (!ok) return;
    try {
      await api(`/devices/${d.id}`, { method: "DELETE" });
      keyStore.del(d.id);
      await loadAll();
      devicesScreen();
    } catch (e) {
      toast(t("error", { msg: e.message }));
    }
  };
  const msg = t("removeConfirm", { name: d.name });
  if (tg.showConfirm) tg.showConfirm(msg, go);
  else go(confirm(msg)); // eslint-disable-line no-alert
}

async function addDeviceForm(preferredLocation) {
  if (!state.sub.entitled) return toast(t("needAccess"));
  const locations = await api("/vpn/locations");
  if (!locations.length) return toast(t("noLocations"));
  const name = h("input", { type: "text", maxlength: 64, placeholder: t("deviceNamePh") });
  const platform = h("select", {}, PLATFORMS.map(([v, l]) => h("option", { value: v }, l)));
  const ua = navigator.userAgent;
  platform.value = /iPhone|iPad/.test(ua) ? "ios" : /Android/.test(ua) ? "android" : /Windows/.test(ua) ? "windows" : /Mac/.test(ua) ? "macos" : "other";
  const loc = h("select", {}, locations.map((l) => h("option", { value: l.id }, `${flag(l.country_code)} ${l.name}`)));
  if (preferredLocation && locations.some((l) => l.id === preferredLocation)) loc.value = preferredLocation;
  const status = h("p", { class: "muted" });
  const submit = h("button", {
    class: "primary wide",
    onclick: async () => {
      submit.disabled = true;
      status.textContent = t("creating");
      try {
        const keys = generateKeyPair();
        const dev = await api("/devices", { method: "POST", body: { name: name.value.trim() || t("deviceNamePh"), platform: platform.value, public_key: keys.publicKey } });
        keyStore.set(dev.id, keys.privateKey);
        const info = await api("/vpn/connect", { method: "POST", body: { device_id: dev.id, location_id: loc.value } });
        const cc = (locations.find((l) => l.id === loc.value) || {}).country_code;
        showResult(buildConfig(keys.privateKey, info), tunnelName(APP_NAME, cc));
      } catch (e) {
        status.textContent = t("error", { msg: e.message });
        submit.disabled = false;
      }
    },
  }, t("create"));
  page(t("addDevice"), h("section", { class: "card" },
    h("label", {}, t("deviceName"), name),
    h("label", {}, t("platform"), platform),
    h("label", {}, t("location"), loc),
    submit, status));
}

function qrSvg(text) {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const wrap = h("div", { class: "qr" });
  wrap.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 4, scalable: true }); // generated locally
  return wrap;
}

function download(text, filename) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/octet-stream" }));
  const a = h("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function showResult(config, name) {
  const copyBtn = h("button", { class: "secondary wide", onclick: async () => {
    try { await navigator.clipboard.writeText(config); copyBtn.textContent = t("copied"); } catch { toast(config); }
  } }, t("copy"));
  page(t("resultTitle"),
    h("section", { class: "card" },
      h("p", { class: "warn" }, t("resultWarn")),
      h("p", { class: "muted" }, t("scanHint")),
      qrSvg(config),
      h("button", { class: "primary wide", onclick: () => download(config, `${name}.conf`) }, t("downloadConf")),
      // The fragment (#...) never leaves the device: browsers don't send it to the server.
      h("button", { class: "secondary wide", onclick: () => tg.openLink(`${location.origin}/app/conf.html#n=${encodeURIComponent(name)}&c=${toFragment(config)}`) }, t("openBrowser")),
      copyBtn,
      h("button", { class: "ghost wide", onclick: () => goHome() }, t("done"))));
}

// ------------------------------------------------------------------ help
function helpScreen() {
  page(t("helpTitle"),
    h("section", { class: "card" },
      h("ol", { class: "steps" }, h("li", {}, t("help1")), h("li", {}, t("help2")), h("li", {}, t("help3")))),
    h("section", { class: "card" }, h("div", { class: "card-sub" }, t("getApp")),
      h("ul", { class: "links" }, APPS.map(([label, url]) =>
        h("li", {}, h("a", { href: url, onclick: (e) => { e.preventDefault(); tg.openLink(url); } }, label))))),
    h("section", { class: "card privacy" },
      h("div", { class: "card-sub" }, t("privacyTitle")),
      h("p", { class: "muted" }, t("privacyStored")),
      h("p", { class: "muted" }, t("privacyNot")),
      h("button", { class: "secondary wide", onclick: exportMyData }, t("privacyExport")),
      h("button", { class: "ghost wide danger", onclick: deleteAccount }, t("privacyDelete"))));
}

async function exportMyData() {
  try {
    const data = await api("/users/me/export");
    download(JSON.stringify(data, null, 2), `${APP_NAME.replace(/\W+/g, "-").toLowerCase()}-my-data.json`);
  } catch (e) {
    toast(t("error", { msg: e.message }));
  }
}

function ask(msg) {
  return new Promise((resolve) => {
    if (tg.showConfirm) tg.showConfirm(msg, (ok) => resolve(Boolean(ok)));
    else resolve(confirm(msg)); // eslint-disable-line no-alert
  });
}

async function deleteAccount() {
  if (!(await ask(t("deleteConfirm1"))) || !(await ask(t("deleteConfirm2")))) return;
  try {
    // A Telegram account has no password: fresh signed initData proves it's really you.
    await api("/users/me", { method: "DELETE", body: { confirm: "DELETE", telegram_init_data: tg.initData } }, false);
  } catch (e) {
    toast(e.code === "invalid_credentials" ? t("deleteReopen") : t("error", { msg: e.message }));
    return;
  }
  try {
    for (const k of Object.keys(localStorage)) if (k.startsWith("vpnhub.")) localStorage.removeItem(k);
  } catch { /* storage unavailable */ }
  token = null;
  setBack(null);
  root.replaceChildren(h("section", { class: "card pad" }, h("p", {}, t("deletedBye"))));
  if (tg.close) setTimeout(() => tg.close(), 4000);
}

// ------------------------------------------------------------------ mini games
const games = initGames({
  h, api, t, toast, store, root, setBack, page, tg, lang,
  goHome: () => goHome(),
  getToken: () => token,
  appName: APP_NAME,
  botLink: () => (state.ref?.link ? state.ref.link.split("?")[0] : null), // https://t.me/<bot>
});

// ------------------------------------------------------------------ boot
(async () => {
  if (!tg || !tg.initData) {
    root.replaceChildren(h("p", { class: "pad" }, t("openInTelegram")));
    return;
  }
  tg.ready();
  tg.expand();
  mountJungle();
  applyTheme(store.get("vpnhub.theme") || "default"); // validated against unlocked themes after load
  tg.BackButton?.onClick(() => backHandler && backHandler());
  window.addEventListener("app:refresh", () => goHome()); // used by the clickable demo
  try {
    await login();
    const ref = new URLSearchParams(location.search).get("ref");
    if (ref && /^[A-Z0-9]{8}$/.test(ref)) {
      await api("/referrals/claim", { method: "POST", body: { code: ref } }).catch(() => null);
    }
    await goHome();
    watchVpn();
    if (new URLSearchParams(location.search).get("screen") === "games") await games.gamesScreen(); // from the bot's /games
  } catch (e) {
    root.replaceChildren(h("p", { class: "warn pad" }, e.message || t("loginFailed")));
  }
})();
