import { api } from "../api.js";
import { h, table, pagedList, dialog, toast, errorText, fmtDate, fmtMoney } from "../ui.js";

const UNIT = { day: "дн.", month: "мес.", year: "г." };
const planName = (p) => p.names.ru || p.names.en || p.code;

// --- plans and prices ----------------------------------------------------------------------
export async function plansPage(ctx) {
  const plans = await api("/admin/plans");
  const write = ctx.can("plans:write");
  const blocks = await Promise.all(plans.map(async (p) => {
    const prices = await api(`/admin/plans/${p.id}/prices`).catch((e) => e);
    const head = h("div", { class: "page-head" },
      h("h2", {}, planName(p), " ", h("span", { class: "muted small" }, `(${p.code}${p.is_trial ? ", пробный" : ""})`)),
      write ? h("div", { class: "actions" },
        h("button", { class: "btn", type: "button", onclick: async () => {
          const done = await dialog({
            title: `Тариф «${planName(p)}»`,
            fields: [
              { name: "name_ru", label: "Название (рус.)", value: p.names.ru || "", required: true, maxlength: 200 },
              { name: "name_en", label: "Название (англ.)", value: p.names.en || "", required: true, maxlength: 200 },
              { name: "device_limit", label: "Устройств", type: "number", min: 1, max: 100, value: p.device_limit, required: true },
              { name: "sort_order", label: "Порядок в списке", type: "number", value: p.sort_order, required: true },
              { name: "active", label: "Продаётся", type: "checkbox", value: p.active },
            ],
            submit: (v) => api(`/admin/plans/${p.id}`, { method: "PATCH", body: {
              names: { ...p.names, ru: v.name_ru, en: v.name_en }, device_limit: v.device_limit, sort_order: v.sort_order, active: v.active,
            } }),
          });
          if (done) { toast("Тариф сохранён"); ctx.go("plans"); }
        } }, "Изменить"),
        h("button", { class: "btn primary", type: "button", onclick: async () => {
          const done = await dialog({
            title: "Новая цена",
            text: "Цены не редактируются: чтобы поменять цену, добавьте новую и выключите старую. Так оплаченные счета остаются честными.",
            fields: [
              { name: "period_count", label: "Срок", type: "number", min: 1, max: 36, value: 1, required: true },
              { name: "period_unit", label: "Единица", type: "select", options: [["month", "месяцы"], ["year", "годы"], ["day", "дни"]], value: "month" },
              { name: "amount", label: "Цена", type: "number", min: 0, step: "0.01", required: true, placeholder: "5.00" },
              { name: "currency", label: "Валюта", value: "USD", required: true, maxlength: 3 },
            ],
            ok: "Добавить",
            submit: (v) => api(`/admin/plans/${p.id}/prices`, { method: "POST", body: {
              period_unit: v.period_unit, period_count: v.period_count, currency: v.currency.toUpperCase(), amount_minor: Math.round(v.amount * 100),
            } }),
          });
          if (done) { toast("Цена добавлена"); ctx.go("plans"); }
        } }, "Добавить цену")) : null);
    const body = prices instanceof Error ? h("p", { class: "error-box" }, errorText(prices)) : table([
      { label: "Срок", cell: (x) => `${x.period_count} ${UNIT[x.period_unit] || x.period_unit}` },
      { label: "Цена", cell: (x) => fmtMoney(x.amount_minor, x.currency), r: true },
      { label: "Действует", cell: (x) => (x.valid_until ? `до ${fmtDate(x.valid_until)}` : "без срока") },
      { label: "В продаже", cell: (x) => (write
        ? h("label", { class: "check" }, h("input", { type: "checkbox", checked: x.active, onchange: async (e) => {
          try {
            await api(`/admin/prices/${x.id}`, { method: "PATCH", body: { active: e.target.checked } });
            toast(e.target.checked ? "Цена включена" : "Цена снята с продажи");
          } catch (ex) { e.target.checked = !e.target.checked; toast(errorText(ex), true); }
        } }), x.active ? "да" : "нет")
        : (x.active ? "да" : "нет")) },
    ], prices, { empty: "Цен нет — тариф нельзя купить." });
    return h("section", { class: "panel" }, head,
      h("p", { class: "muted small" }, `До ${p.device_limit} устройств, серверы: ${p.server_tiers.join(", ")}. ${p.active ? "Продаётся." : "Не продаётся."}`),
      body);
  }));
  return h("div", {}, h("div", { class: "page-head" }, h("h1", {}, "Тарифы и цены")), blocks.length ? blocks : h("p", { class: "empty" }, "Тарифов нет. На сервере: python -m app.cli bootstrap-catalog"));
}

// --- promo codes ---------------------------------------------------------------------------
function promoValue(p) {
  if (p.kind === "percent_off") return `−${p.percent_off}%`;
  if (p.kind === "amount_off") return `−${fmtMoney(p.amount_off_minor, p.currency)}`;
  return `${p.free_days} дн. бесплатно`;
}

export async function promoPage(ctx) {
  const write = ctx.can("promo:write");
  const list = pagedList(
    (offset, limit) => api("/admin/promo-codes", { query: { offset, limit } }),
    (rows) => table([
      { label: "Код", cell: (p) => h("b", {}, p.code) },
      { label: "Что даёт", cell: promoValue },
      { label: "Использован", cell: (p) => `${p.redemption_count}${p.max_redemptions ? ` из ${p.max_redemptions}` : ""}`, r: true },
      { label: "Действует до", cell: (p) => (p.valid_until ? fmtDate(p.valid_until) : "без срока") },
      { label: "Включён", cell: (p) => (write
        ? h("label", { class: "check" }, h("input", { type: "checkbox", checked: p.active, onchange: async (e) => {
          try {
            await api(`/admin/promo-codes/${p.id}`, { method: "PATCH", body: { active: e.target.checked } });
            toast(e.target.checked ? "Промокод включён" : "Промокод выключен");
          } catch (ex) { e.target.checked = !e.target.checked; toast(errorText(ex), true); }
        } }), p.active ? "да" : "нет")
        : (p.active ? "да" : "нет")) },
    ], rows, { empty: "Промокодов пока нет." }));
  const create = write ? h("button", { class: "btn primary", type: "button", onclick: async () => {
    const plans = await api("/admin/plans");
    const done = await dialog({
      title: "Новый промокод",
      text: "Процент или сумма — скидка при оплате. Бесплатные дни — сразу дают доступ (так работают инвайты).",
      fields: [
        { name: "code", label: "Код (латиница, цифры, - и _)", required: true, minlength: 3, maxlength: 40, placeholder: "KONG30" },
        { name: "kind", label: "Тип", type: "select", options: [["percent_off", "Скидка в процентах"], ["amount_off", "Скидка суммой"], ["free_days", "Бесплатные дни"]], value: "percent_off" },
        { name: "value", label: "Процент, сумма или дней", type: "number", min: 1, step: "0.01", required: true },
        { name: "currency", label: "Валюта (для суммы)", value: "USD", maxlength: 3 },
        { name: "plan_code", label: "Тариф (для бесплатных дней)", type: "select", options: plans.map((p) => [p.code, planName(p)]), value: plans[0]?.code },
        { name: "max_redemptions", label: "Сколько раз можно использовать (пусто — без ограничения)", type: "number", min: 1 },
        { name: "valid_until", label: "Действует до (необязательно)", type: "date" },
      ],
      ok: "Создать",
      submit: (v) => {
        const body = { code: v.code, kind: v.kind, max_redemptions: v.max_redemptions || null, valid_until: v.valid_until ? `${v.valid_until}T23:59:59Z` : null };
        if (v.kind === "percent_off") body.percent_off = Math.round(v.value);
        if (v.kind === "amount_off") Object.assign(body, { amount_off_minor: Math.round(v.value * 100), currency: v.currency.toUpperCase() });
        if (v.kind === "free_days") Object.assign(body, { free_days: Math.round(v.value), plan_code: v.plan_code });
        return api("/admin/promo-codes", { method: "POST", body });
      },
    });
    if (done) { toast("Промокод создан"); ctx.go("promo"); }
  } }, "Создать промокод") : null;
  return h("div", {}, h("div", { class: "page-head" }, h("h1", {}, "Промокоды"), create), list);
}
