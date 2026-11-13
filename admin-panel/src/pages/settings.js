import { api } from "../api.js";
import { h, toast, errorText } from "../ui.js";

const GROUPS = [
  ["access.", "Доступ к сервису"],
  ["trial.", "Пробный период"],
  ["subscription.", "Подписка"],
  ["reminders.", "Напоминания"],
  ["devices.", "Устройства"],
  ["peers.", "VPN-серверы"],
  ["referrals.", "Друзья и рефералы"],
  ["games.", "Блэкджек"],
];

export function editor(key, def, write) {
  const kind = typeof def.default === "boolean" ? "bool" : typeof def.default === "number" ? "number" : "json";
  const err = h("span", { class: "error-box small" });
  let input;
  if (kind === "bool") input = h("input", { type: "checkbox", checked: def.value, disabled: !write, "aria-label": key });
  else if (kind === "number") input = h("input", { type: "number", value: String(def.value), disabled: !write, "aria-label": key });
  else input = h("textarea", { disabled: !write, "aria-label": key, rows: 1 }, JSON.stringify(def.value));
  const save = h("button", { class: "btn", type: "button", disabled: true }, "Сохранить");
  const mark = () => { save.disabled = false; };
  input.addEventListener(kind === "bool" ? "change" : "input", mark);
  save.addEventListener("click", async () => {
    let value;
    try {
      value = kind === "bool" ? input.checked : kind === "number" ? Number(input.value) : JSON.parse(input.value);
    } catch {
      err.textContent = "Это не похоже на JSON: например [3] или \"text\".";
      return;
    }
    save.disabled = true;
    err.textContent = "";
    try {
      const r = await api(`/admin/settings/${encodeURIComponent(key)}`, { method: "PUT", body: { value } });
      def.value = r.value ?? value;
      toast("Настройка сохранена");
    } catch (e) {
      err.textContent = errorText(e);
      save.disabled = false;
    }
  });
  const changed = JSON.stringify(def.value) !== JSON.stringify(def.default);
  return h("div", { class: "panel" },
    h("div", { class: "page-head" }, h("h2", {}, key), changed ? h("span", { class: "pill role" }, "изменено") : h("span", { class: "muted small" }, "по умолчанию")),
    h("p", { class: "muted small" }, def.description, " По умолчанию: ", JSON.stringify(def.default), "."),
    h("div", { class: "row" }, kind === "bool" ? h("label", { class: "check" }, input, def.value ? "включено" : "выключено") : input, write ? h("div", { class: "shrink" }, save) : null),
    err);
}

export async function settingsPage(ctx) {
  const all = await api("/admin/settings");
  const write = ctx.can("settings:write");
  const keys = Object.keys(all).sort();
  const used = new Set();
  const sections = GROUPS.map(([prefix, title]) => {
    const mine = keys.filter((k) => k.startsWith(prefix));
    mine.forEach((k) => used.add(k));
    return mine.length ? h("section", {}, h("h2", {}, title), mine.map((k) => editor(k, all[k], write))) : null;
  });
  const rest = keys.filter((k) => !used.has(k));
  return h("div", {},
    h("div", { class: "page-head" }, h("h1", {}, "Настройки")),
    write ? h("p", { class: "muted small" }, "Каждое изменение сразу действует для всех и пишется в журнал.") : h("p", { class: "muted small" }, "Только просмотр: менять настройки может роль «сервера» или суперадмин."),
    sections, rest.length ? h("section", {}, h("h2", {}, "Прочее"), rest.map((k) => editor(k, all[k], write))) : null);
}
