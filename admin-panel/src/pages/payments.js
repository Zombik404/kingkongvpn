import { api } from "../api.js";
import { h, table, pagedList, pill, fmtDateTime, fmtMoney, shortId } from "../ui.js";

export async function paymentsPage(ctx) {
  const status = h("select", { name: "status" },
    h("option", { value: "" }, "Все"), h("option", { value: "succeeded" }, "Оплачены"),
    h("option", { value: "pending" }, "Ждут оплаты"), h("option", { value: "failed" }, "Не прошли"), h("option", { value: "refunded" }, "Возвраты"));
  const results = h("div", {});
  const run = () => results.replaceChildren(pagedList(
    (offset, limit) => api("/admin/payments", { query: { status: status.value, offset, limit } }),
    (rows) => table([
      { label: "Дата", cell: (p) => fmtDateTime(p.paid_at || p.created_at) },
      { label: "Сумма", cell: (p) => h("span", { class: "num" }, fmtMoney(p.amount_minor, p.currency)), r: true },
      { label: "Оплачено", cell: (p) => (p.paid_amount ? `${p.paid_amount} ${p.paid_asset}` : "—") },
      { label: "Тариф", cell: (p) => [p.plan_code, p.period].filter(Boolean).join(", ") || "—" },
      { label: "Скидка", cell: (p) => ({ promo: "промокод", referral: "от друга" })[p.discount] || "—" },
      { label: "Статус", cell: (p) => pill(p.status) },
      { label: "Пользователь", cell: (p) => (p.user_id ? h("a", { href: `#/users/${p.user_id}`, onclick: (e) => e.stopPropagation() }, `…${shortId(p.user_id)}`) : "удалён") },
    ], rows, { empty: "Платежей нет." })));
  status.addEventListener("change", run);
  run();
  return h("div", {},
    h("div", { class: "page-head" }, h("h1", {}, "Платежи"), h("label", { class: "field" }, "Статус", status)),
    h("p", { class: "muted small" }, "Данные кошельков и карт у нас не хранятся — их видит только @CryptoBot."),
    results);
}
