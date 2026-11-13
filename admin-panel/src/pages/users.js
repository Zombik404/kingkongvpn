import { api } from "../api.js";
import {
  h, table, pagedList, pill, dialog, reasonField, toast, copyButton, errorText,
  fmtDate, fmtDateTime, fmtMoney, shortId, ROLE_NAMES,
} from "../ui.js";

const who = (u) => u.email || (u.has_telegram ? `Telegram · …${shortId(u.id)}` : `…${shortId(u.id)}`);

function access(sub) {
  if (!sub) return h("span", { class: "muted" }, "нет");
  return h("span", {}, pill(sub.status), " ", sub.plan_name, " до ", fmtDate(sub.current_period_end));
}

export async function usersPage(ctx) {
  const q = h("input", { type: "search", name: "q", placeholder: "Почта, Telegram ID, код друга или ID", autocomplete: "off" });
  const status = h("select", { name: "status" },
    h("option", { value: "" }, "Любой статус"), h("option", { value: "active" }, "Активные"),
    h("option", { value: "suspended" }, "Заблокированные"), h("option", { value: "deleted" }, "Удалённые"));
  const staffOnly = h("input", { type: "checkbox", name: "staff" });
  const results = h("div", {});
  const run = () => {
    results.replaceChildren(pagedList(
      (offset, limit) => api("/admin/users", { query: { q: q.value.trim(), status: status.value, staff_only: staffOnly.checked || "", offset, limit } }),
      (rows) => table([
        { label: "Пользователь", cell: (u) => h("span", {}, who(u), u.roles.length ? [" ", ...u.roles.map((r) => h("span", { class: "pill role" }, ROLE_NAMES[r] || r))] : null) },
        { label: "Статус", cell: (u) => pill(u.status) },
        { label: "Доступ", cell: (u) => access(u.subscription) },
        { label: "Устройства", cell: (u) => String(u.active_devices), r: true },
        { label: "С нами с", cell: (u) => fmtDate(u.created_at) },
      ], rows, { onRow: (u) => ctx.go(`users/${u.id}`), empty: q.value ? "Никого не нашли. Telegram ID можно узнать у бота @userinfobot." : "Пользователей пока нет." }),
      { pageSize: 25 }));
  };
  const form = h("form", { class: "row" }, h("label", { class: "field" }, "Поиск", q), h("label", { class: "field shrink" }, "Статус", status),
    h("label", { class: "check shrink" }, staffOnly, "Только сотрудники"), h("button", { class: "btn primary shrink", type: "submit" }, "Найти"));
  form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
  run();
  return h("div", {}, h("div", { class: "page-head" }, h("h1", {}, "Пользователи")), h("section", { class: "panel" }, form), results);
}

export async function userPage(ctx, id) {
  const u = await api(`/admin/users/${encodeURIComponent(id)}`);
  const reload = () => ctx.go(`users/${u.id}`);
  const sub = u.subscription;
  const actions = [];

  if (ctx.can("subscriptions:grant")) {
    actions.push(h("button", { class: "btn primary", type: "button", onclick: async () => {
      // paid plans first: a goodwill grant on the trial plan would give trial limits
      const plans = ctx.can("plans:read") ? (await api("/admin/plans")).filter((p) => p.active).sort((a, b) => Number(a.is_trial) - Number(b.is_trial)) : [];
      const options = plans.length ? plans.map((p) => [p.code, `${p.names.ru || p.names.en || p.code}${p.is_trial ? " (пробный)" : ""}`]) : [["standard", "standard"]];
      const done = await dialog({
        title: "Продлить доступ",
        text: "Дни добавятся к текущему сроку (или начнут новый).",
        fields: [
          { name: "plan_code", label: "Тариф", type: "select", options, value: sub?.plan_code || options[0][0] },
          { name: "days", label: "Дней", type: "number", min: 1, max: 3660, value: 30, required: true },
          reasonField,
        ],
        ok: "Продлить",
        submit: (v) => api(`/admin/users/${u.id}/subscription/grant`, { method: "POST", body: v }),
      });
      if (done) { toast("Доступ продлён"); reload(); }
    } }, "Продлить доступ"));
    if (sub) actions.push(h("button", { class: "btn danger", type: "button", onclick: async () => {
      const done = await dialog({
        title: "Отозвать доступ", text: "Доступ закончится сразу, устройства отключатся от серверов.", danger: true, ok: "Отозвать",
        fields: [reasonField],
        submit: (v) => api(`/admin/users/${u.id}/subscription/revoke`, { method: "POST", body: v }),
      });
      if (done) { toast("Доступ отозван"); reload(); }
    } }, "Отозвать доступ"));
  }
  if (ctx.can("users:write") && u.status !== "deleted" && u.id !== ctx.me.id) {
    const suspend = u.status === "active";
    actions.push(h("button", { class: suspend ? "btn danger" : "btn", type: "button", onclick: async () => {
      const done = await dialog({
        title: suspend ? "Заблокировать аккаунт" : "Разблокировать аккаунт",
        text: suspend ? "Человек выйдет на всех устройствах, VPN отключится." : "Аккаунт снова сможет входить.",
        danger: suspend, ok: suspend ? "Заблокировать" : "Разблокировать",
        fields: [reasonField],
        submit: (v) => api(`/admin/users/${u.id}/status`, { method: "POST", body: { status: suspend ? "suspended" : "active", reason: v.reason } }),
      });
      if (done) { toast(suspend ? "Заблокирован" : "Разблокирован"); reload(); }
    } }, suspend ? "Заблокировать" : "Разблокировать"));
  }
  if (ctx.can("roles:write") && u.status === "active" && u.email && u.id !== ctx.me.id) {
    actions.push(h("button", { class: "btn", type: "button", onclick: async () => {
      const done = await dialog({
        title: "Роли сотрудника",
        text: "Сотрудник входит в админку по почте и паролю с 2FA. Через Telegram сотрудники не входят.",
        fields: Object.entries(ROLE_NAMES).map(([r, label]) => ({ name: r, label, type: "checkbox", value: u.roles.includes(r) })),
        submit: (v) => api(`/admin/users/${u.id}/roles`, { method: "PUT", body: { roles: Object.keys(ROLE_NAMES).filter((r) => v[r]) } }),
      });
      if (done) { toast("Роли сохранены"); reload(); }
    } }, "Роли"));
  }
  if (ctx.can("games:write")) {
    actions.push(h("button", { class: "btn", type: "button", onclick: async () => {
      const done = await dialog({
        title: "Бонусные дни блэкджека",
        text: "Только игровой кошелёк, оплаченные дни не затрагиваются. Отрицательное число списывает (не ниже нуля).",
        fields: [{ name: "delta_days", label: "Дней (+/−)", type: "number", min: -365, max: 365, value: 1, required: true }, reasonField],
        submit: (v) => api(`/admin/games/players/${u.id}/bonus`, { method: "POST", body: v }),
      });
      if (done) { toast("Бонусный баланс изменён"); reload(); }
    } }, "Бонусные дни"));
  }

  const lists = [];
  if (ctx.can("payments:read")) {
    lists.push(h("section", { class: "panel" }, h("h2", {}, "Платежи"), pagedList(
      (offset, limit) => api("/admin/payments", { query: { user_id: u.id, offset, limit } }),
      (rows) => table([
        { label: "Дата", cell: (p) => fmtDateTime(p.created_at) },
        { label: "Сумма", cell: (p) => fmtMoney(p.amount_minor, p.currency), r: true },
        { label: "Тариф", cell: (p) => [p.plan_code, p.period].filter(Boolean).join(", ") || "—" },
        { label: "Статус", cell: (p) => pill(p.status) },
      ], rows, { empty: "Платежей нет." }), { pageSize: 10 })));
  }
  if (ctx.can("games:read")) {
    lists.push(h("section", { class: "panel" }, h("h2", {}, "Блэкджек"), await api("/admin/games/players", { query: { user_id: u.id } }).then((rows) => {
      const p = rows[0];
      if (!p) return h("p", { class: "empty" }, "Ещё не играл.");
      return h("div", {}, h("p", {}, `Ник «${p.nickname}», раундов ${p.rounds}, побед ${p.wins}, блэкджеков ${p.blackjacks}. Фишек ${p.chips}, лучший куш ${p.best_win}. Бонусных часов: ${p.balance_hours}.`),
        h("a", { href: `#/progress/player/${u.id}` }, "Уровень, достижения, сезоны и исключение из рейтингов"));
    }).catch((e) => h("p", { class: "error-box" }, errorText(e)))));
  }
  if (ctx.can("audit:read")) {
    lists.push(h("section", { class: "panel" }, h("h2", {}, "Журнал по этому пользователю"), pagedList(
      (offset, limit) => api("/admin/audit-logs", { query: { target_id: u.id, offset, limit } }),
      (rows) => table([
        { label: "Когда", cell: (a) => fmtDateTime(a.created_at) },
        { label: "Действие", cell: (a) => a.action },
        { label: "Кто", cell: (a) => (a.actor_id === u.id ? "сам" : a.actor_type === "admin" ? `сотрудник …${shortId(a.actor_id)}` : a.actor_type) },
        { label: "Подробности", cell: (a) => h("span", { class: "json" }, Object.keys(a.details || {}).length ? JSON.stringify(a.details) : "") },
      ], rows, { empty: "Записей нет." }), { pageSize: 10 })));
  }

  return h("div", {},
    h("p", {}, h("a", { href: "#/users" }, "‹ Пользователи")),
    h("div", { class: "page-head case-head" }, h("h1", {}, who(u)), pill(u.status), u.roles.map((r) => h("span", { class: "pill role" }, ROLE_NAMES[r] || r))),
    h("div", { class: "case" },
      h("div", {}, h("dl", {},
        h("dt", {}, "Доступ"), h("dd", { class: "big" }, sub ? `до ${fmtDate(sub.current_period_end)}` : "нет"),
        sub ? [h("dt", {}, "Тариф"), h("dd", {}, `${sub.plan_name}, `, pill(sub.status), sub.grace_until ? ` льгота до ${fmtDate(sub.grace_until)}` : "")] : null,
        sub ? [h("dt", {}, "Оплата"), h("dd", {}, sub.provider === "admin" ? "выдан вручную" : sub.provider)] : null)),
      h("div", {}, h("dl", {},
        h("dt", {}, "Устройства"), h("dd", { class: "big" }, sub ? `${u.active_devices} из ${sub.device_limit}` : String(u.active_devices)),
        h("dt", {}, "Вход"), h("dd", {}, u.has_telegram ? "через Telegram" : "почта и пароль", u.mfa_enabled ? ", 2FA включена" : ""))),
      h("div", {}, h("dl", {},
        h("dt", {}, "С нами с"), h("dd", {}, fmtDate(u.created_at)),
        h("dt", {}, "Последний вход"), h("dd", {}, fmtDateTime(u.last_login_at)),
        h("dt", {}, "ID"), h("dd", { class: "small" }, h("span", { class: "secret" }, u.id), " ", copyButton(u.id))))),
    actions.length ? h("div", { class: "actions panel flat" }, actions) : null,
    h("div", { class: "grid" }, lists));
}
