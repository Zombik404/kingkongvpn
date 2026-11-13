// Telegram Mini App. All user data is inserted with textContent (no innerHTML of API data).
import qrcode from "qrcode-generator";
import { makeT, pickLang } from "./i18n.js";
import { buildConfig, generateKeyPair, toFragment, tunnelName } from "./wg.js";

const API = "/api/v1";
const APP_NAME = document.documentElement.dataset.appName || "VPN";
const tg = window.Telegram && window.Telegram.WebApp;
const lang = pickLang(tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.language_code);
const t = makeT(lang);
const root = document.getElementById("app");

const APPS = [
  ["Android", "https://play.google.com/store/apps/details?id=com.wireguard.android"],
  ["iPhone / iPad", "https://apps.apple.com/app/wireguard/id1441195209"],
  ["Windows / macOS / Linux", "https://www.wireguard.com/install/"],
];
const PLATFORMS = [
  ["android", "Android"], ["ios", "iPhone / iPad"], ["windows", "Windows"],
  ["macos", "macOS"], ["linux", "Linux"], ["router", "Router"], ["other", "Other"],
];

let token = null;

// ---------------------------------------------------------------- helpers
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

const fmtDate = (iso) =>
  new Date(iso).toLocaleDateString(lang === "ru" ? "ru-RU" : "en-GB", { day: "numeric", month: "long", year: "numeric" });
const fmtPrice = (minor, cur) =>
  new Intl.NumberFormat(lang === "ru" ? "ru-RU" : "en-US", { style: "currency", currency: cur }).format(minor / 100);

function toast(msg) {
  if (tg && tg.showAlert) tg.showAlert(msg);
  else alert(msg); // eslint-disable-line no-alert
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
    headers: {
      Authorization: `Bearer ${token}`,
      "Accept-Language": lang,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401 && retry) {
    await login(); // access tokens are short-lived; initData is still valid
    return api(path, { method, body }, false);
  }
  if (r.status === 204) return null;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const msg = (data.error && data.error.message) || (Array.isArray(data.detail) && data.detail[0] && data.detail[0].msg) || `HTTP ${r.status}`;
    const err = new Error(msg);
    err.code = data.error && data.error.code;
    throw err;
  }
  return data;
}

// ---------------------------------------------------------------- screens
async function render() {
  root.replaceChildren(h("p", { class: "muted" }, t("loading")));
  const [sub, devices, plans] = await Promise.all([api("/subscription"), api("/devices"), api("/plans")]);
  const cards = [
    statusCard(sub),
    sub.entitled ? null : inviteCard(),
    plansCard(plans, sub.entitled),
    devicesCard(devices, sub.entitled),
    appsCard(),
  ];
  root.replaceChildren(...cards.filter(Boolean)); // replaceChildren would print "null"
}

function statusCard(sub) {
  const s = sub.subscription;
  const body = s
    ? [
        h("p", { class: "big ok" }, t("activeUntil", { date: fmtDate(s.current_period_end) })),
        h("p", { class: "muted" }, t("planLine", { plan: s.plan_name })),
        s.status === "grace" && s.grace_until ? h("p", { class: "warn" }, t("graceNote", { date: fmtDate(s.grace_until) })) : null,
      ]
    : [h("p", { class: "big" }, t("noAccess"))];
  return h("section", { class: "card" }, h("h2", {}, t("access")), ...body);
}

function inviteCard() {
  const input = h("input", { type: "text", placeholder: t("invitePlaceholder"), autocomplete: "off", maxlength: 40, autocapitalize: "characters" });
  // Invite links t.me/<bot>?start=INV-… open the app with ?invite=… (set by the bot).
  const fromLink = new URLSearchParams(location.search).get("invite");
  if (fromLink && /^INV-[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(fromLink)) input.value = fromLink;
  const btn = h("button", {
    onclick: async () => {
      const code = input.value.trim();
      if (!code) return;
      btn.disabled = true;
      try {
        await api("/promo/redeem", { method: "POST", body: { code } });
        toast(t("redeemed"));
        await render();
      } catch (e) {
        toast(t("error", { msg: e.message }));
        btn.disabled = false;
      }
    },
  }, t("redeem"));
  return h("section", { class: "card" }, h("h2", {}, t("invite")), h("p", { class: "muted" }, t("inviteHelp")), h("div", { class: "row" }, input, btn));
}

function plansCard(plans, entitled) {
  const buttons = [];
  for (const plan of plans) {
    for (const price of plan.prices) {
      const label = `${t("months")(price.period_count)} — ${fmtPrice(price.amount_minor, price.currency)}`;
      buttons.push(h("button", { class: "secondary wide", onclick: (ev) => startPayment(price, ev.currentTarget) }, label));
    }
  }
  if (!buttons.length) return null;
  return h("section", { class: "card" }, h("h2", {}, entitled ? t("renew") : t("plans")), ...buttons, h("p", { class: "muted small" }, t("payHint")));
}

async function startPayment(price, btn) {
  btn.disabled = true;
  try {
    const p = await api("/payments/checkout", { method: "POST", body: { price_id: price.id } });
    if (p.checkout_url && p.checkout_url.startsWith("https://t.me/") && tg.openTelegramLink) tg.openTelegramLink(p.checkout_url);
    else tg.openLink(p.checkout_url);
    await waitForPayment(p.id);
  } catch (e) {
    toast(t("error", { msg: e.message }));
  } finally {
    btn.disabled = false;
  }
}

async function waitForPayment(id) {
  if (tg.MainButton) {
    tg.MainButton.setText(t("waitingPayment"));
    tg.MainButton.showProgress();
    tg.MainButton.show();
  }
  try {
    const until = Date.now() + 15 * 60 * 1000;
    while (Date.now() < until) {
      await new Promise((r) => setTimeout(r, 5000));
      const p = await api(`/payments/${id}?refresh=true`);
      if (p.status === "succeeded") {
        toast(t("paid"));
        await render();
        return;
      }
      if (p.status === "failed") {
        toast(t("paymentFailed"));
        return;
      }
    }
  } finally {
    if (tg.MainButton) {
      tg.MainButton.hideProgress();
      tg.MainButton.hide();
    }
  }
}

function devicesCard(list, entitled) {
  const items = list.devices.map((d) =>
    h("li", { class: "device" },
      h("div", {},
        h("strong", {}, d.name),
        h("div", { class: "muted small" }, `${d.platform} · ${d.ipv4 || ""}`),
        h("div", { class: "muted small" }, d.last_handshake_at ? t("lastSeen", { date: fmtDate(d.last_handshake_at) }) : t("never"))),
      h("button", { class: "danger small", onclick: () => removeDevice(d) }, t("remove"))));
  const add = h("button", { class: "wide", disabled: list.active_count >= list.limit || undefined, onclick: () => addDeviceForm(entitled) }, t("addDevice"));
  return h("section", { class: "card" },
    h("h2", {}, t("devices"), " ", h("span", { class: "muted small" }, t("deviceLimit", { n: list.active_count, limit: list.limit }))),
    items.length ? h("ul", { class: "list" }, items) : h("p", { class: "muted" }, t("noDevices")),
    add);
}

function removeDevice(d) {
  const go = async (ok) => {
    if (!ok) return;
    try {
      await api(`/devices/${d.id}`, { method: "DELETE" });
      await render();
    } catch (e) {
      toast(t("error", { msg: e.message }));
    }
  };
  const msg = t("removeConfirm", { name: d.name });
  if (tg.showConfirm) tg.showConfirm(msg, go);
  else go(confirm(msg)); // eslint-disable-line no-alert
}

async function addDeviceForm(entitled) {
  if (!entitled) return toast(t("needAccess"));
  const locations = await api("/vpn/locations");
  if (!locations.length) return toast(t("noLocations"));
  const name = h("input", { type: "text", maxlength: 64, placeholder: t("deviceNamePh") });
  const platform = h("select", {}, PLATFORMS.map(([v, l]) => h("option", { value: v }, l)));
  const ua = navigator.userAgent;
  platform.value = /iPhone|iPad/.test(ua) ? "ios" : /Android/.test(ua) ? "android" : /Windows/.test(ua) ? "windows" : /Mac/.test(ua) ? "macos" : "other";
  const loc = h("select", {}, locations.map((l) => h("option", { value: l.id }, `${l.name}`)));
  const status = h("p", { class: "muted" });
  const submit = h("button", {
    class: "wide",
    onclick: async () => {
      submit.disabled = true;
      status.textContent = t("creating");
      try {
        const keys = generateKeyPair();
        const dev = await api("/devices", { method: "POST", body: { name: name.value.trim() || t("deviceNamePh"), platform: platform.value, public_key: keys.publicKey } });
        const info = await api("/vpn/connect", { method: "POST", body: { device_id: dev.id, location_id: loc.value } });
        const country = (locations.find((l) => l.id === loc.value) || {}).country_code;
        showResult(buildConfig(keys.privateKey, info), tunnelName(APP_NAME, country));
      } catch (e) {
        status.textContent = t("error", { msg: e.message });
        submit.disabled = false;
      }
    },
  }, t("create"));
  root.replaceChildren(h("section", { class: "card" },
    h("h2", {}, t("addDevice")),
    h("label", {}, t("deviceName"), name),
    h("label", {}, t("platform"), platform),
    h("label", {}, t("location"), loc),
    submit, status,
    h("button", { class: "secondary wide", onclick: () => render() }, "←")));
}

function qrSvg(text) {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const wrap = h("div", { class: "qr" });
  wrap.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 4, scalable: true }); // generated locally, no user HTML
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
  const copyBtn = h("button", {
    class: "secondary wide",
    onclick: async () => {
      try {
        await navigator.clipboard.writeText(config);
        copyBtn.textContent = t("copied");
      } catch {
        toast(config);
      }
    },
  }, t("copy"));
  root.replaceChildren(h("section", { class: "card" },
    h("h2", {}, t("resultTitle")),
    h("p", { class: "warn" }, t("resultWarn")),
    h("p", { class: "muted" }, t("scanHint")),
    qrSvg(config),
    h("button", { class: "wide", onclick: () => download(config, `${name}.conf`) }, t("download")),
    // The fragment (#...) never leaves the device: browsers don't send it to the server.
    h("button", { class: "secondary wide", onclick: () => tg.openLink(`${location.origin}/app/conf.html#n=${encodeURIComponent(name)}&c=${toFragment(config)}`) }, t("openBrowser")),
    copyBtn,
    h("button", { class: "wide", onclick: () => render() }, t("done"))),
  appsCard());
}

function appsCard() {
  return h("section", { class: "card" }, h("p", { class: "muted small" }, t("getApp")),
    h("ul", { class: "links" }, APPS.map(([label, url]) => h("li", {}, h("a", { href: url, onclick: (e) => { e.preventDefault(); tg.openLink(url); } }, label)))));
}

// ---------------------------------------------------------------- boot
(async () => {
  if (!tg || !tg.initData) {
    root.replaceChildren(h("p", {}, t("openInTelegram")));
    return;
  }
  tg.ready();
  tg.expand();
  try {
    await login();
    await render();
  } catch (e) {
    root.replaceChildren(h("p", { class: "warn" }, e.message || t("loginFailed")));
  }
})();
