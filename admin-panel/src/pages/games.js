import { api } from "../api.js";
import { h, table, pagedList, pill, dialog, reasonField, toast, fmtDateTime, fmtInt, shortId } from "../ui.js";

const stat = (value, label, warn = false) => h("div", { class: `stat${warn ? " warn" : ""}` }, h("b", {}, value), h("span", {}, label));
const userLink = (id) => (id ? h("a", { href: `#/users/${id}`, onclick: (e) => e.stopPropagation() }, `…${shortId(id)}`) : "—");

export async function gamesPage(ctx) {
  const [o, suspicious] = await Promise.all([api("/admin/games/overview"), api("/admin/games/suspicious")]);
  const write = ctx.can("games:write");
  const switches = [
    ["Игры", o.enabled],
    ["Ставки бонусными днями", o.stakes_enabled],
    ["Общие столы", o.multiplayer_enabled],
  ];
  const roomAction = (r, action, label, danger = false) => h("button", { class: `btn${danger ? " danger" : ""}`, type: "button", onclick: async () => {
    const done = await dialog({
      title: `${label}: стол ${r.code || shortId(r.id)}`, danger, ok: label, fields: [reasonField],
      text: action === "close" ? "Ставки текущего раунда вернутся игрокам." : null,
      submit: (v) => api(`/admin/games/rooms/${r.id}/${action}`, { method: "POST", body: v }),
    });
    if (done) { toast("Готово"); ctx.go("games"); }
  } }, label);

  return h("div", {},
    h("div", { class: "page-head" }, h("h1", {}, "Блэкджек")),
    h("div", { class: "stats" },
      stat(fmtInt(o.rounds_today), "раундов сегодня"),
      stat(fmtInt(o.open_rooms), "открытых столов"),
      stat(fmtInt(o.seated_players), "игроков за столами"),
      stat(fmtInt(Math.round(o.bonus_hours_outstanding / 24)), "бонусных дней на руках у игроков"),
      stat(fmtInt(suspicious.length), "подозрительных игроков", suspicious.length > 0)),
    h("section", { class: "panel" }, h("h2", {}, "Переключатели"),
      h("p", {}, switches.map(([label, on]) => h("span", {}, `${label}: `, h("span", { class: `pill ${on ? "good" : ""}` }, on ? "включено" : "выключено"), "  "))),
      h("p", { class: "muted small" }, "Меняются в разделе «Настройки» (ключи games.*). Ставки бонусными днями держите выключенными до проверки юристом: во многих странах это считается азартной игрой."),
      ctx.can("settings:read") ? h("button", { class: "btn", type: "button", onclick: () => ctx.go("settings") }, "Открыть настройки") : null),
    h("section", { class: "panel" }, h("h2", {}, "Подозрительные результаты за 7 дней"),
      h("p", { class: "muted small" }, "Больше 60 % побед на 30+ раундах или большой выигрыш бонусных дней. Повод посмотреть вручную, а не доказательство."),
      table([
        { label: "Игрок", cell: (s) => userLink(s.user_id) },
        { label: "Раундов", cell: (s) => String(s.rounds), r: true },
        { label: "Побед", cell: (s) => `${Math.round(s.win_rate * 100)} %`, r: true },
        { label: "Итог, часов", cell: (s) => String(s.net_hours), r: true },
      ], suspicious, { onRow: (s) => ctx.go(`users/${s.user_id}`), empty: "Никого — всё в пределах обычного." })),
    h("section", { class: "panel" }, h("h2", {}, "Столы"), pagedList(
      (offset, limit) => api("/admin/games/rooms", { query: { offset, limit } }),
      (rows) => table([
        { label: "Стол", cell: (r) => r.code || `…${shortId(r.id)}` },
        { label: "Игроков", cell: (r) => `${r.players} / ${r.max_players}`, r: true },
        { label: "Раунд", cell: (r) => String(r.round_no), r: true },
        { label: "Статус", cell: (r) => pill(r.status) },
        { label: "", cell: (r) => (write && r.status !== "closed" ? h("div", { class: "actions" },
          r.status === "open" ? roomAction(r, "pause", "Пауза") : roomAction(r, "resume", "Продолжить"),
          roomAction(r, "close", "Закрыть", true)) : "") },
      ], rows, { empty: "Столов нет." }), { pageSize: 20 })),
    h("section", { class: "panel" }, h("h2", {}, "События"), pagedList(
      (offset, limit) => api("/admin/games/events", { query: { offset, limit } }),
      (rows) => table([
        { label: "Когда", cell: (e) => fmtDateTime(e.at) },
        { label: "Событие", cell: (e) => e.action },
        { label: "Кто", cell: (e) => userLink(e.actor_id) },
        { label: "Подробности", cell: (e) => h("span", { class: "json" }, JSON.stringify(e.details || {})) },
      ], rows, { empty: "Событий нет." }), { pageSize: 20 })));
}
