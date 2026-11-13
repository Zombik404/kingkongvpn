// Small DOM helpers. Everything from the API goes in as text (textContent), never as HTML.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "value" && "value" in el) el.value = v;
    else if (k === "checked") el.checked = Boolean(v);
    // CSSOM, not a style attribute: the CSP forbids inline style attributes.
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const dtf = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
const df = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
export const fmtDateTime = (iso) => (iso ? dtf.format(new Date(iso)) : "—");
export const fmtDate = (iso) => (iso ? df.format(new Date(iso)) : "—");
export const fmtInt = (n) => new Intl.NumberFormat("ru-RU").format(Number(n || 0));
export function fmtMoney(minor, currency) {
  try {
    return new Intl.NumberFormat("ru-RU", { style: "currency", currency, maximumFractionDigits: minor % 100 ? 2 : 0 }).format(minor / 100);
  } catch {
    return `${(minor / 100).toFixed(2)} ${currency}`;
  }
}
export const shortId = (id) => (id ? String(id).slice(-8) : "—");

const STATUS = {
  active: ["активен", "good"],
  trialing: ["пробный", "good"],
  grace: ["льготный период", "warn"],
  past_due: ["просрочен", "warn"],
  canceled: ["отменён", ""],
  expired: ["закончился", ""],
  refunded: ["возврат", "warn"],
  suspended: ["заблокирован", "bad"],
  deleted: ["удалён", ""],
  succeeded: ["оплачен", "good"],
  pending: ["ждёт оплаты", "warn"],
  failed: ["не прошёл", "bad"],
  draining: ["разгружается", "warn"],
  maintenance: ["обслуживание", "warn"],
  disabled: ["отключён", "bad"],
  provisioning: ["подготовка", ""],
  open: ["идёт", "good"],
  paused: ["на паузе", "warn"],
  closed: ["закрыт", ""],
  success: ["успех", "good"],
  failure: ["отказ", "bad"],
};
export function pill(status) {
  const [text, tone] = STATUS[status] || [status ?? "—", ""];
  return h("span", { class: `pill ${tone}` }, text);
}

export const ROLE_NAMES = { superadmin: "суперадмин", support: "поддержка", ops: "сервера", finance: "финансы" };

let toastTimer = null;
export function toast(text, bad = false) {
  document.querySelector(".toast")?.remove();
  const el = h("div", { class: `toast${bad ? " bad" : ""}`, role: "status" }, text);
  document.body.append(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), bad ? 6000 : 3000);
}

export function errorText(e) {
  return e?.message || "Что-то пошло не так.";
}

// Modal form. `fields`: [{name, label, type, value, options, required, min, max, placeholder, help}]
// Resolves with the values, or null when cancelled. `submit(values)` may throw to keep it open.
export function dialog({ title, text, fields = [], ok = "Сохранить", danger = false, submit }) {
  return new Promise((resolve) => {
    const err = h("div", { class: "error-box", role: "alert" });
    const inputs = {};
    const rows = fields.map((f) => {
      let input;
      if (f.type === "select") {
        input = h("select", { name: f.name }, f.options.map(([v, label]) => h("option", { value: v, selected: v === f.value }, label)));
      } else if (f.type === "checkbox") {
        input = h("input", { type: "checkbox", name: f.name, checked: f.value });
        inputs[f.name] = input;
        return h("label", { class: "check" }, input, f.label);
      } else if (f.type === "textarea") {
        input = h("textarea", { name: f.name, required: f.required, placeholder: f.placeholder }, f.value ?? "");
      } else {
        input = h("input", {
          name: f.name, type: f.type || "text", value: f.value ?? "", required: f.required, min: f.min, max: f.max,
          step: f.step, placeholder: f.placeholder, autocomplete: "off", minlength: f.minlength, maxlength: f.maxlength,
        });
      }
      inputs[f.name] = input;
      return h("label", { class: "field" }, f.label, input, f.help ? h("span", { class: "small" }, f.help) : null);
    });
    const okBtn = h("button", { class: `btn ${danger ? "danger" : "primary"}`, type: "submit" }, ok);
    const dlg = h("dialog", {},
      h("form", { method: "dialog" },
        h("h2", {}, title),
        text ? h("p", { class: "muted" }, text) : null,
        rows, err,
        h("div", { class: "actions" }, okBtn, h("button", { class: "btn", type: "button", onclick: () => close(null) }, "Отмена"))));
    const close = (v) => { dlg.close(); dlg.remove(); resolve(v); };
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(null); });
    dlg.querySelector("form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const values = {};
      for (const f of fields) {
        const el = inputs[f.name];
        values[f.name] = f.type === "checkbox" ? el.checked : f.type === "number" ? (el.value === "" ? null : Number(el.value)) : el.value.trim();
      }
      if (!submit) return close(values);
      okBtn.disabled = true;
      err.textContent = "";
      try {
        close((await submit(values)) ?? values);
      } catch (ex) {
        err.textContent = errorText(ex);
        okBtn.disabled = false;
      }
    });
    document.body.append(dlg);
    dlg.showModal();
    (dlg.querySelector("input, select, textarea") || okBtn).focus();
  });
}

export const reasonField = { name: "reason", label: "Причина (видна в журнале)", required: true, minlength: 3, maxlength: 200 };

// Table with labelled cells (stacks on phones). cols: [{label, cell(row) -> Node|string, r}]
export function table(cols, rows, { onRow, empty = "Пусто." } = {}) {
  if (!rows.length) return h("p", { class: "empty" }, empty);
  return h("div", { class: "table-wrap" },
    h("table", { class: "stack" },
      h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c.r ? "r" : null }, c.label)))),
      h("tbody", {}, rows.map((row) => h("tr", {
        class: onRow ? "click" : null,
        tabindex: onRow ? 0 : null,
        onclick: onRow ? () => onRow(row) : null,
        onkeydown: onRow ? (e) => { if (e.key === "Enter") onRow(row); } : null,
      }, cols.map((c) => h("td", { "data-label": c.label, class: c.r ? "r" : null }, c.cell(row))))))));
}

// A list that loads page by page ("Показать ещё").
export function pagedList(load, render, { pageSize = 50 } = {}) {
  const box = h("div", {});
  const more = h("button", { class: "btn more", type: "button" }, "Показать ещё");
  let offset = 0;
  let all = [];
  async function next() {
    more.disabled = true;
    try {
      const rows = await load(offset, pageSize);
      all = all.concat(rows);
      offset += rows.length;
      box.replaceChildren(render(all));
      if (rows.length === pageSize) box.append(more);
    } catch (e) {
      box.replaceChildren(h("p", { class: "error-box" }, errorText(e)));
    } finally {
      more.disabled = false;
    }
  }
  more.addEventListener("click", next);
  next();
  return box;
}

export function copyButton(text, label = "Скопировать") {
  return h("button", {
    class: "btn", type: "button",
    onclick: async () => {
      try { await navigator.clipboard.writeText(text); toast("Скопировано"); } catch { toast("Не удалось скопировать — выделите вручную", true); }
    },
  }, label);
}

export function bars(points, key) {
  const max = Math.max(1, ...points.map((p) => p[key]));
  return h("div", {},
    h("div", { class: "bars", role: "img", "aria-label": points.map((p) => `${p.day}: ${p[key]}`).join(", ") },
      points.map((p) => h("i", { class: p[key] ? null : "zero", style: { height: `${Math.max(2, Math.round((p[key] / max) * 100))}%` }, title: `${fmtDate(p.day)}: ${p[key]}` }))),
    h("div", { class: "bars-axis" }, h("span", {}, fmtDate(points[0]?.day)), h("span", {}, "сегодня")));
}
