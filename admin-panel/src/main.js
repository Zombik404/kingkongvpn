// KingKong VPN staff console: sign-in (password + 2FA), shell, hash router.
import qrcode from "qrcode-generator";
import { ApiError, api, logout, session } from "./api.js";
import { h, toast, errorText, ROLE_NAMES } from "./ui.js";
import { overviewPage } from "./pages/overview.js";
import { usersPage, userPage } from "./pages/users.js";
import { paymentsPage } from "./pages/payments.js";
import { plansPage, promoPage } from "./pages/catalog.js";
import { serversPage } from "./pages/servers.js";
import { gamesPage } from "./pages/games.js";
import { settingsPage } from "./pages/settings.js";
import { auditPage } from "./pages/audit.js";

const root = document.getElementById("root");
const IDLE_LIMIT_MS = 30 * 60 * 1000; // signed out after 30 minutes without activity
let me = null;
let lastActivity = Date.now();

const SECTIONS = [
  { id: "overview", label: "Обзор", perm: "users:read", page: overviewPage },
  { id: "users", label: "Пользователи", perm: "users:read", page: usersPage },
  { id: "payments", label: "Платежи", perm: "payments:read", page: paymentsPage },
  { id: "plans", label: "Тарифы и цены", perm: "plans:read", page: plansPage },
  { id: "promo", label: "Промокоды", perm: "plans:read", page: promoPage },
  { id: "servers", label: "Серверы", perm: "servers:read", page: serversPage },
  { id: "games", label: "Блэкджек", perm: "games:read", page: gamesPage },
  { id: "settings", label: "Настройки", perm: "settings:read", page: settingsPage },
  { id: "audit", label: "Журнал действий", perm: "audit:read", page: auditPage },
];
const MOBILE = ["overview", "users", "payments"];

const can = (perm) => Boolean(me?.permissions.includes(perm));
export const ctx = { can, go, get me() { return me; } };

function go(path) {
  if (location.hash === `#/${path}`) route();
  else location.hash = `#/${path}`;
}

// ------------------------------------------------------------------------- sign in
function brand(sub) {
  return h("div", { class: "auth-brand" },
    h("img", { src: "logo.png", alt: "" }),
    h("div", {}, h("h1", {}, "KingKong VPN"), h("p", {}, sub)));
}

function signIn(note) {
  const err = h("div", { class: "error-box", role: "alert" }, note || "");
  const email = h("input", { type: "email", name: "email", autocomplete: "username", required: true });
  const password = h("input", { type: "password", name: "password", autocomplete: "current-password", required: true });
  const btn = h("button", { class: "btn primary", type: "submit" }, "Войти");
  const form = h("form", {},
    h("label", { class: "field" }, "Почта", email),
    h("label", { class: "field" }, "Пароль", password),
    err, btn);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    btn.disabled = true;
    err.textContent = "";
    try {
      const r = await api("/auth/login", { method: "POST", body: { email: email.value.trim(), password: password.value }, auth: false });
      password.value = "";
      if (r.mfa_required) return codeStep(r.mfa_token);
      session.set(r);
      await enter();
    } catch (ex) {
      err.textContent = errorText(ex);
      btn.disabled = false;
    }
  });
  root.replaceChildren(h("div", { class: "auth" }, h("div", { class: "auth-box" }, brand("Вход для сотрудников"), form)));
  email.focus();
}

function codeInput() {
  return h("input", { name: "code", inputmode: "numeric", autocomplete: "one-time-code", pattern: "[0-9]{6}", maxlength: 6, required: true });
}

function codeStep(mfaToken) {
  const err = h("div", { class: "error-box", role: "alert" });
  const code = codeInput();
  const btn = h("button", { class: "btn primary", type: "submit" }, "Подтвердить");
  const form = h("form", {},
    h("p", { class: "muted" }, "Введите 6 цифр из приложения-аутентификатора."),
    h("label", { class: "field" }, "Код", code), err, btn,
    h("button", { class: "btn link", type: "button", onclick: () => signIn() }, "Войти под другим аккаунтом"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    btn.disabled = true;
    err.textContent = "";
    try {
      session.set(await api("/auth/mfa/verify", { method: "POST", body: { mfa_token: mfaToken, code: code.value.trim() }, auth: false }));
      await enter();
    } catch (ex) {
      err.textContent = errorText(ex);
      btn.disabled = false;
      code.value = "";
      code.focus();
    }
  });
  root.replaceChildren(h("div", { class: "auth" }, h("div", { class: "auth-box" }, brand("Двухфакторная проверка"), form)));
  code.focus();
}

function qrNode(text) {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const n = qr.getModuleCount();
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `-2 -2 ${n + 4} ${n + 4}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "QR-код для приложения-аутентификатора");
  const path = document.createElementNS(NS, "path");
  let d = "";
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if (qr.isDark(y, x)) d += `M${x} ${y}h1v1h-1z`;
  path.setAttribute("d", d);
  svg.append(path);
  return h("div", { class: "qr" }, svg);
}

async function setupMfa() {
  let setup;
  try {
    setup = await api("/auth/mfa/totp/setup", { method: "POST" });
  } catch (e) {
    return signIn(errorText(e));
  }
  const err = h("div", { class: "error-box", role: "alert" });
  const code = codeInput();
  const btn = h("button", { class: "btn primary", type: "submit" }, "Включить и войти");
  const form = h("form", {},
    h("p", {}, "Для админки обязательна двухфакторная защита. Отсканируйте код в Google Authenticator, Aegis или 1Password и введите 6 цифр."),
    qrNode(setup.otpauth_uri),
    h("details", {}, h("summary", { class: "muted small" }, "Не сканируется? Ключ для ручного ввода"), h("p", { class: "secret" }, setup.secret)),
    h("label", { class: "field" }, "Код из приложения", code), err, btn);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    btn.disabled = true;
    err.textContent = "";
    try {
      await api("/auth/mfa/totp/enable", { method: "POST", body: { code: code.value.trim() } });
      toast("Двухфакторная защита включена");
      await enter();
    } catch (ex) {
      err.textContent = errorText(ex);
      btn.disabled = false;
    }
  });
  root.replaceChildren(h("div", { class: "auth" }, h("div", { class: "auth-box" }, brand("Настройка 2FA"), form)));
  code.focus();
}

async function enter() {
  try {
    me = await api("/admin/me");
  } catch (e) {
    if (e instanceof ApiError && e.code === "mfa_required") return setupMfa();
    await logout();
    return signIn(e instanceof ApiError && e.status === 403 ? "У этого аккаунта нет прав сотрудника." : errorText(e));
  }
  lastActivity = Date.now();
  if (!location.hash || location.hash === "#/") location.hash = "#/overview";
  else route();
}

async function signOut(note) {
  me = null;
  await logout();
  history.replaceState(null, "", location.pathname);
  signIn(note);
}

// ------------------------------------------------------------------------- shell + router
function shell(active, content) {
  const visible = SECTIONS.filter((s) => can(s.perm));
  const link = (s, cls = "nav") => h("a", { href: `#/${s.id}`, class: `${cls}${s.id === active ? " on" : ""}`, "aria-current": s.id === active ? "page" : null }, s.label);
  const who = h("div", { class: "rail-foot" },
    h("div", { class: "who" }, me.email),
    h("div", {}, me.roles.map((r) => ROLE_NAMES[r] || r).join(", ")),
    h("button", { class: "btn", type: "button", onclick: () => signOut() }, "Выйти"));
  const more = () => {
    const list = h("div", { class: "grid" }, visible.filter((s) => !MOBILE.includes(s.id)).map((s) => h("a", { href: `#/${s.id}`, class: "nav", onclick: () => dlg.close() }, s.label)),
      h("button", { class: "btn", type: "button", onclick: () => { dlg.close(); signOut(); } }, "Выйти"),
      h("button", { class: "btn link", type: "button", onclick: () => dlg.close() }, "Закрыть"));
    const dlg = h("dialog", {}, h("h2", {}, "Разделы"), list);
    dlg.addEventListener("close", () => dlg.remove());
    document.body.append(dlg);
    dlg.showModal();
  };
  return h("div", { class: "shell" },
    h("nav", { class: "rail", "aria-label": "Разделы" },
      h("div", { class: "rail-brand" }, h("img", { src: "logo.png", alt: "" }), "KingKong VPN"),
      visible.map((s) => link(s)), who),
    h("main", {}, content),
    h("nav", { class: "mobile-bar", "aria-label": "Разделы" },
      visible.filter((s) => MOBILE.includes(s.id)).map((s) => link(s, "")),
      h("button", { type: "button", onclick: more }, "Ещё")));
}

let renderToken = 0;
async function route() {
  if (!me) return;
  const [section, ...rest] = location.hash.replace(/^#\//, "").split("/");
  const def = SECTIONS.find((s) => s.id === section && can(s.perm)) || SECTIONS.find((s) => can(s.perm));
  if (!def) return signOut("Нет доступных разделов.");
  const mine = ++renderToken;
  const content = h("div", {}, h("p", { class: "muted" }, "Загрузка…"));
  root.replaceChildren(shell(def.id, content));
  window.scrollTo(0, 0);
  try {
    const node = section === "users" && rest[0] ? await userPage(ctx, rest[0]) : await def.page(ctx, rest);
    if (mine === renderToken) content.replaceChildren(node);
  } catch (e) {
    if (mine === renderToken) content.replaceChildren(h("p", { class: "error-box" }, errorText(e)));
  }
}

window.addEventListener("hashchange", route);
for (const ev of ["pointerdown", "keydown"]) window.addEventListener(ev, () => { lastActivity = Date.now(); }, { passive: true });
setInterval(() => {
  if (me && Date.now() - lastActivity > IDLE_LIMIT_MS) signOut("Вы вышли автоматически после 30 минут без действий.");
}, 30_000);
session.onExpired(() => {
  if (me) {
    me = null;
    signIn("Сессия закончилась. Войдите снова.");
  }
});

signIn();
