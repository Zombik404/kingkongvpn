import { api } from "../api.js";
import { h, table, pagedList, pill, fmtDateTime, shortId } from "../ui.js";

export async function auditPage() {
  const action = h("input", { name: "action", placeholder: "например admin или auth.login", autocomplete: "off" });
  const target = h("input", { name: "target", placeholder: "ID пользователя, сервера…", autocomplete: "off" });
  const results = h("div", {});
  const run = () => results.replaceChildren(pagedList(
    (offset, limit) => api("/admin/audit-logs", { query: { action: action.value.trim(), target_id: target.value.trim(), offset, limit } }),
    (rows) => table([
      { label: "Когда", cell: (a) => fmtDateTime(a.created_at) },
      { label: "Действие", cell: (a) => h("b", {}, a.action) },
      { label: "Кто", cell: (a) => (a.actor_id ? h("a", { href: `#/users/${a.actor_id}` }, `${a.actor_type} …${shortId(a.actor_id)}`) : a.actor_type) },
      { label: "Над чем", cell: (a) => (a.target_type ? `${a.target_type} …${shortId(a.target_id)}` : "—") },
      { label: "Итог", cell: (a) => pill(a.result) },
      { label: "Сеть", cell: (a) => a.ip_prefix || "—" },
      { label: "Подробности", cell: (a) => h("span", { class: "json" }, Object.keys(a.details || {}).length ? JSON.stringify(a.details) : "") },
    ], rows, { empty: "Записей нет." })));
  const form = h("form", { class: "row" },
    h("label", { class: "field" }, "Действие", action), h("label", { class: "field" }, "Объект", target),
    h("button", { class: "btn primary shrink", type: "submit" }, "Показать"));
  form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
  run();
  return h("div", {},
    h("div", { class: "page-head" }, h("h1", {}, "Журнал действий")),
    h("p", { class: "muted small" }, "Все изменения сотрудников и важные события аккаунтов. IP хранится сокращённым, секреты вырезаются."),
    h("section", { class: "panel" }, form), results);
}
