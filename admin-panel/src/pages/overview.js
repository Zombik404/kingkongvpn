import { api } from "../api.js";
import { h, bars, fmtInt, fmtMoney, fmtDateTime } from "../ui.js";

const stat = (value, label, warn = false) => h("div", { class: `stat${warn ? " warn" : ""}` }, h("b", {}, value), h("span", {}, label));

export async function overviewPage(ctx) {
  const o = await api("/admin/overview");
  const money = o.revenue_30d;
  const usd = money?.by_currency?.USD;
  const serversDown = o.servers.total - o.servers.accepting;
  return h("div", {},
    h("div", { class: "page-head" }, h("h1", {}, "Обзор"), h("span", { class: "muted small" }, `обновлено ${fmtDateTime(o.generated_at)}`)),
    h("div", { class: "stats" },
      stat(fmtInt(o.users.total), `пользователей, +${fmtInt(o.users.new_7d)} за неделю`),
      stat(fmtInt(o.subscriptions.active + o.subscriptions.trialing), "с доступом сейчас"),
      stat(fmtInt(o.subscriptions.grace), "в льготном периоде", o.subscriptions.grace > 0),
      stat(fmtInt(o.devices_active), "активных устройств"),
      stat(`${o.servers.accepting} из ${o.servers.total}`, "серверов принимают подключения", serversDown > 0),
      money ? stat(usd ? fmtMoney(usd.amount_minor, "USD") : "0 $", `выручка за 30 дней, ${fmtInt(usd?.count || 0)} оплат`) : null),
    h("div", { class: "grid two" },
      h("section", { class: "panel" }, h("h2", {}, "Новые пользователи за 30 дней"), bars(o.signups_30d, "count")),
      money
        ? h("section", { class: "panel" }, h("h2", {}, "Оплаты в USD за 30 дней"), bars(money.usd_daily, "amount_minor"),
          Object.keys(money.by_currency).filter((c) => c !== "USD").length
            ? h("p", { class: "muted small" }, "Другие валюты: ", Object.entries(money.by_currency).filter(([c]) => c !== "USD").map(([c, v]) => `${fmtMoney(v.amount_minor, c)} (${v.count})`).join(", "))
            : null)
        : null,
      h("section", { class: "panel" }, h("h2", {}, "Сегодня в игре"),
        h("p", {}, `${fmtInt(o.games.rounds_24h)} раундов блэкджека, ${fmtInt(o.games.players_24h)} игроков за сутки.`),
        h("p", {}, `${fmtInt(o.referral_rewards_30d)} наград за приглашённых друзей за 30 дней.`),
        h("p", { class: "muted small" }, `Из ${fmtInt(o.users.total)} пользователей ${fmtInt(o.users.telegram)} пришли через Telegram.`)),
      serversDown > 0 && ctx.can("servers:read")
        ? h("section", { class: "panel" }, h("h2", {}, "Серверы"),
          h("p", {}, `${serversDown} из ${o.servers.total} не принимают подключения: выключены вручную или давно не выходили на связь.`),
          h("button", { class: "btn", type: "button", onclick: () => ctx.go("servers") }, "Открыть серверы"))
        : null));
}
