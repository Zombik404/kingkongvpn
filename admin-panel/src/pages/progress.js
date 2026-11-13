// Blackjack progression for staff (ADR-021): players and cheat exclusion, seasons and winners,
// achievements and daily challenges catalogue, XP / level / reward settings.
import { api } from "../api.js";
import { h, table, pagedList, pill, dialog, reasonField, toast, errorText, fmtDate, fmtDateTime, fmtInt } from "../ui.js";
import { editor } from "./settings.js";

const TABS = [
  ["players", "Игроки"],
  ["seasons", "Сезоны"],
  ["achievements", "Достижения"],
  ["challenges", "Задания дня"],
  ["rules", "XP и награды"],
];
const KIND = { weekly: "неделя", monthly: "месяц", event: "событие" };
const BOARD = { xp: "по XP", wins: "по победам", winrate: "по % побед" };
const CAT = { game: "игра", activity: "активность", progress: "прогресс", season: "сезоны" };
const DIFF = { easy: "лёгкое", medium: "среднее", hard: "сложное" };
const METRIC = {
  wins: "побед", rounds: "партий", blackjacks: "блэкджеков", best_win_streak: "побед подряд (рекорд)",
  perfect_wins: "побед ровно с 21", best_day_streak: "дней подряд (рекорд)", days_played: "игровых дней",
  level: "уровень", xp: "XP", season_rank: "место в сезоне не ниже", high_wins: "побед с 20 или 21", win_run: "побед подряд за день",
};
const ru = (t) => (t ? t.ru || t.en || Object.values(t)[0] : "");

function tabs(active) {
  return h("div", { class: "actions tabs", role: "tablist" },
    TABS.map(([id, label]) => h("a", { href: `#/progress/${id}`, class: `btn${id === active ? " primary" : ""}`, role: "tab", "aria-selected": String(id === active) }, label)));
}

export async function progressPage(ctx, rest) {
  const [tab = "players", id] = rest;
  let body;
  if (tab === "player" && id) body = await playerView(ctx, id);
  else if (tab === "seasons") body = await seasonsView(ctx);
  else if (tab === "achievements") body = await achievementsView(ctx);
  else if (tab === "challenges") body = await challengesView(ctx);
  else if (tab === "rules") body = await rulesView(ctx);
  else body = playersView(ctx);
  return h("div", {},
    h("div", { class: "page-head" }, h("h1", {}, "Прогресс и сезоны")),
    h("p", { class: "muted small" }, "XP, уровни, достижения, задания и сезоны считаются на сервере только из доигранных партий. Клиент ничего из этого прислать не может."),
    tabs(tab === "player" ? "players" : tab), body);
}

// ------------------------------------------------------------------ players
function playersView(ctx) {
  const q = h("input", { type: "search", name: "q", placeholder: "Ник или ID пользователя", autocomplete: "off" });
  const only = h("input", { type: "checkbox", name: "excluded" });
  const out = h("div", {});
  const run = () => out.replaceChildren(pagedList(
    (offset, limit) => api("/admin/games/progress/players", { query: { q: q.value.trim(), excluded: only.checked || "", offset, limit } }),
    (rows) => table([
      { label: "Игрок", cell: (p) => h("span", {}, `${p.avatar} `, h("b", {}, p.nickname), p.excluded_at ? [" ", h("span", { class: "pill bad" }, "исключён")] : null) },
      { label: "Уровень", cell: (p) => `${p.level} · ${p.title}` },
      { label: "XP", cell: (p) => h("span", { class: "num" }, fmtInt(p.xp)), r: true },
      { label: "Побед / пораж.", cell: (p) => `${p.wins} / ${p.losses}`, r: true },
      { label: "% побед", cell: (p) => (p.win_rate === null ? "—" : `${p.win_rate} %`), r: true },
      { label: "Дней подряд", cell: (p) => String(p.day_streak), r: true },
    ], rows, { onRow: (p) => ctx.go(`progress/player/${p.user_id}`), empty: q.value ? "Никого не нашли." : "Ещё никто не играл." })));
  const form = h("form", { class: "row" }, h("label", { class: "field" }, "Поиск", q),
    h("label", { class: "check shrink" }, only, "Только исключённые"), h("button", { class: "btn primary shrink", type: "submit" }, "Найти"));
  form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
  run();
  return h("div", {}, h("section", { class: "panel" }, form), out);
}

async function playerView(ctx, id) {
  const p = await api(`/admin/games/progress/players/${encodeURIComponent(id)}`);
  const reload = () => ctx.go(`progress/player/${p.user_id}`);
  const excluded = Boolean(p.excluded_at);
  const actions = ctx.can("games:write") ? h("button", { class: excluded ? "btn" : "btn danger", type: "button", onclick: async () => {
    const done = await dialog({
      title: excluded ? "Вернуть в рейтинги" : "Исключить из рейтингов",
      text: excluded ? "Игрок снова появится в таблицах и сможет получать сезонные награды."
        : "Игрок пропадёт из всех таблиц и не получит сезонных наград. Делайте это только при подтверждённой накрутке.",
      danger: !excluded, ok: excluded ? "Вернуть" : "Исключить", fields: [reasonField],
      submit: (v) => api(`/admin/games/progress/players/${p.user_id}/${excluded ? "include" : "exclude"}`, { method: "POST", body: v }),
    });
    if (done) { toast(excluded ? "Игрок возвращён" : "Игрок исключён"); reload(); }
  } }, excluded ? "Вернуть в рейтинги" : "Исключить из рейтингов") : null;
  const ch = p.challenges_today;
  return h("div", {},
    h("p", {}, h("a", { href: "#/progress/players" }, "‹ Игроки"), "  ", ctx.can("users:read") ? h("a", { href: `#/users/${p.user_id}` }, "Карточка пользователя") : null),
    h("div", { class: "page-head case-head" }, h("h2", {}, `${p.avatar} ${p.nickname}`), excluded ? h("span", { class: "pill bad" }, `исключён ${fmtDate(p.excluded_at)}`) : h("span", { class: "pill good" }, "в рейтингах"), actions),
    h("div", { class: "case" },
      h("div", {}, h("dl", {}, h("dt", {}, "Уровень"), h("dd", { class: "big" }, `${p.level} · ${p.title}`),
        h("dt", {}, "XP"), h("dd", {}, `${fmtInt(p.xp)} (до следующего уровня ${fmtInt(p.next_level_xp - p.xp)})`))),
      h("div", {}, h("dl", {}, h("dt", {}, "Партии"), h("dd", { class: "big" }, `${p.rounds}`),
        h("dt", {}, "Побед / поражений / ничьих"), h("dd", {}, `${p.wins} / ${p.losses} / ${p.pushes}, блэкджеков ${p.blackjacks}`))),
      h("div", {}, h("dl", {}, h("dt", {}, "Серия дней"), h("dd", { class: "big" }, `${p.day_streak} (рекорд ${p.best_day_streak})`),
        h("dt", {}, "Лучшая серия побед"), h("dd", {}, String(p.best_win_streak))))),
    h("div", { class: "grid two" },
      h("section", { class: "panel" }, h("h2", {}, "Достижения"),
        p.achievements.length ? h("p", {}, p.achievements.map((a) => h("span", { class: "pill", title: fmtDate(a.unlocked_at) }, `${a.icon} ${ru(a.names)}`)).flatMap((x) => [x, " "])) : h("p", { class: "empty" }, "Пока нет."),
        h("p", { class: "muted small" }, `Титулы: ${p.titles.join(", ") || "—"}`)),
      h("section", { class: "panel" }, h("h2", {}, "Задания сегодня"),
        ch.length ? table([
          { label: "Задание", cell: (c) => c.code },
          { label: "Прогресс", cell: (c) => `${c.progress} / ${c.target}`, r: true },
          { label: "Выполнено", cell: (c) => (c.completed_at ? fmtDateTime(c.completed_at) : "—") },
        ], ch) : h("p", { class: "empty" }, "Сегодня ещё не играл.")),
      h("section", { class: "panel" }, h("h2", {}, "Сезоны"),
        table([
          { label: "Сезон", cell: (s) => `${s.name} (${KIND[s.kind] || s.kind})` },
          { label: "Партий", cell: (s) => String(s.rounds), r: true },
          { label: "Побед / пораж.", cell: (s) => `${s.wins} / ${s.losses}`, r: true },
          { label: "XP", cell: (s) => fmtInt(s.xp), r: true },
          { label: "", cell: (s) => pill(s.status === "active" ? "open" : "closed") },
        ], p.seasons, { empty: "Не участвовал." })),
      h("section", { class: "panel" }, h("h2", {}, "Награды"),
        table([
          { label: "Когда", cell: (r) => fmtDateTime(r.at) },
          { label: "За что", cell: (r) => `${r.source === "season" ? "сезон" : r.source === "streak" ? "серия дней" : r.source}: ${r.ref}` },
          { label: "Что", cell: (r) => [r.xp ? `+${r.xp} XP` : null, r.title, r.frame ? `рамка ${r.frame}` : null, r.bonus_days ? `${r.bonus_days} бонусн. дн. ${r.bonus_paid ? "(начислено)" : "(выключено)"}` : null].filter(Boolean).join(", ") },
        ], p.rewards, { empty: "Наград ещё не было." }))),
    h("section", { class: "panel" }, h("h2", {}, "История XP"),
      table([
        { label: "Когда", cell: (x) => fmtDateTime(x.at) },
        { label: "За что", cell: (x) => ({ round: "партия", achievement: "достижение", challenge: "задание дня", streak: "серия дней", season: "сезон" })[x.kind] || x.kind },
        { label: "XP", cell: (x) => `+${x.amount}`, r: true },
      ], p.xp_history, { empty: "XP ещё не было." })));
}

// ------------------------------------------------------------------ seasons
function rewardsText(tiers) {
  return (tiers || []).map((t) => {
    const places = t.places[0] === t.places[1] ? `${t.places[0]}` : `${t.places[0]}–${t.places[1]}`;
    return `${places}: ${[t.xp ? `${t.xp} XP` : null, t.title, t.frame, t.bonus_days ? `${t.bonus_days} бонусн. дн.` : null].filter(Boolean).join(", ")}`;
  }).join(" · ");
}
const localInput = (iso) => { const d = new Date(iso); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const toIso = (local) => new Date(local).toISOString();

async function seasonsView(ctx) {
  const write = ctx.can("games:write");
  const seasons = await api("/admin/games/seasons", { query: { limit: 60 } });
  const results = async (s) => {
    const r = await api(`/admin/games/seasons/${s.id}/results`, { query: { board: s.board } });
    const dlg = h("dialog", {}, h("h2", {}, `${s.name}: ${r.live ? "сейчас" : "итоги"} ${BOARD[s.board]}`),
      table([
        { label: "#", cell: (x) => String(x.rank), r: true },
        { label: "Игрок", cell: (x) => (x.user_id ? h("a", { href: `#/progress/player/${x.user_id}`, onclick: () => dlg.close() }, x.nickname) : x.nickname) },
        { label: "Результат", cell: (x) => fmtInt(x.value), r: true },
      ], r.rows.slice(0, 50), { empty: "Участников нет." }),
      h("div", { class: "actions" }, h("button", { class: "btn primary", type: "button", onclick: () => dlg.close() }, "Закрыть")));
    dlg.addEventListener("close", () => dlg.remove());
    document.body.append(dlg);
    dlg.showModal();
  };
  const edit = async (s) => {
    const done = await dialog({
      title: `Сезон ${s.name}`,
      text: "Начало можно менять только до старта. Призы — JSON: [{\"places\":[1,1],\"xp\":500,\"title\":\"King of Jungle\",\"frame\":\"gold\",\"bonus_days\":3}, …]",
      fields: [
        { name: "name", label: "Название", value: s.name, required: true, minlength: 3, maxlength: 64 },
        { name: "ends_at", label: "Окончание", type: "datetime-local", value: localInput(s.ends_at), required: true },
        { name: "board", label: "Призы по рейтингу", type: "select", options: [["xp", "XP"], ["wins", "победы"]], value: s.board },
        { name: "rewards", label: "Призы", type: "textarea", value: JSON.stringify(s.rewards) },
        reasonField,
      ],
      submit: (v) => {
        let rewards;
        try { rewards = JSON.parse(v.rewards); } catch { throw new Error("Призы: это не похоже на JSON."); }
        return api(`/admin/games/seasons/${s.id}`, { method: "PATCH", body: { name: v.name, ends_at: toIso(v.ends_at), board: v.board, rewards, reason: v.reason } });
      },
    });
    if (done) { toast("Сезон сохранён"); ctx.go("progress/seasons"); }
  };
  const finish = async (s) => {
    const done = await dialog({
      title: `Завершить «${s.name}» сейчас`, danger: true, ok: "Завершить и выдать награды",
      text: "Таблица зафиксируется, призы выдадутся один раз. Отменить нельзя.", fields: [reasonField],
      submit: (v) => api(`/admin/games/seasons/${s.id}/finish`, { method: "POST", body: v }),
    });
    if (done) { toast("Сезон завершён, награды выданы"); ctx.go("progress/seasons"); }
  };
  const create = write ? h("button", { class: "btn primary", type: "button", onclick: async () => {
    const start = new Date(Date.now() + 864e5); start.setHours(0, 0, 0, 0);
    const end = new Date(start.getTime() + 7 * 864e5);
    const done = await dialog({
      title: "Новое событие",
      text: "Отдельный сезон со своими датами и призами, рядом с недельным и месячным. Призы по умолчанию — как у недельного.",
      fields: [
        { name: "name", label: "Название", required: true, minlength: 3, maxlength: 64, placeholder: "Новогодние джунгли" },
        { name: "starts_at", label: "Начало", type: "datetime-local", value: localInput(start.toISOString()), required: true },
        { name: "ends_at", label: "Окончание", type: "datetime-local", value: localInput(end.toISOString()), required: true },
        { name: "board", label: "Призы по рейтингу", type: "select", options: [["xp", "XP"], ["wins", "победы"]], value: "xp" },
      ],
      ok: "Создать",
      submit: (v) => api("/admin/games/seasons", { method: "POST", body: { name: v.name, starts_at: toIso(v.starts_at), ends_at: toIso(v.ends_at), board: v.board } }),
    });
    if (done) { toast("Событие создано"); ctx.go("progress/seasons"); }
  } }, "Создать событие") : null;
  return h("div", {},
    h("div", { class: "actions panel flat" }, create),
    h("section", { class: "panel" }, h("h2", {}, "Сезоны"),
      h("p", { class: "muted small" }, "Недельные и месячные открываются и закрываются сами по расписанию в часовом поясе игры (настройка games.timezone)."),
      table([
        { label: "Сезон", cell: (s) => h("span", {}, h("b", {}, s.name), ` (${KIND[s.kind] || s.kind})`) },
        { label: "Даты", cell: (s) => `${fmtDateTime(s.starts_at)} — ${fmtDateTime(s.ends_at)}` },
        { label: "Статус", cell: (s) => pill(s.status === "active" ? "open" : "closed") },
        { label: "Участников", cell: (s) => String(s.participants), r: true },
        { label: "Победители", cell: (s) => (s.winners.length ? s.winners.map((w) => `${w.rank}. ${w.nickname}`).join(", ") : "—") },
        { label: "Призы", cell: (s) => h("span", { class: "json" }, rewardsText(s.rewards)) },
        { label: "", cell: (s) => h("div", { class: "actions" },
          h("button", { class: "btn", type: "button", onclick: () => results(s).catch((e) => toast(errorText(e), true)) }, s.status === "active" ? "Таблица" : "Итоги"),
          write && s.status === "active" ? h("button", { class: "btn", type: "button", onclick: () => edit(s) }, "Изменить") : null,
          write && s.status === "active" ? h("button", { class: "btn danger", type: "button", onclick: () => finish(s) }, "Завершить") : null) },
      ], seasons, { empty: "Сезонов пока нет: первый откроется при первой игре." })));
}

// ------------------------------------------------------------------ achievements
function achFields(a = {}) {
  return [
    { name: "icon", label: "Значок (эмодзи)", value: a.icon || "🏅", required: true, maxlength: 8 },
    { name: "name_ru", label: "Название (рус.)", value: a.names?.ru || "", required: true, maxlength: 64 },
    { name: "name_en", label: "Название (англ.)", value: a.names?.en || "", required: true, maxlength: 64 },
    { name: "desc_ru", label: "Описание (рус.)", value: a.descriptions?.ru || "", required: true, maxlength: 200 },
    { name: "desc_en", label: "Описание (англ.)", value: a.descriptions?.en || "", required: true, maxlength: 200 },
    { name: "threshold", label: "Сколько нужно", type: "number", min: 1, value: a.threshold ?? 10, required: true },
    { name: "xp_reward", label: "Награда XP", type: "number", min: 0, value: a.xp_reward ?? 50, required: true },
    { name: "title", label: "Титул за достижение (необязательно)", value: a.title || "", maxlength: 32 },
  ];
}
const achBody = (v) => ({
  icon: v.icon, names: { ru: v.name_ru, en: v.name_en }, descriptions: { ru: v.desc_ru, en: v.desc_en },
  threshold: v.threshold, xp_reward: v.xp_reward, title: v.title || null,
});

async function achievementsView(ctx) {
  const write = ctx.can("games:write");
  const list = await api("/admin/games/achievements");
  const toggle = (a) => (write ? h("label", { class: "check" }, h("input", { type: "checkbox", checked: a.enabled, onchange: async (e) => {
    try { await api(`/admin/games/achievements/${a.id}`, { method: "PATCH", body: { enabled: e.target.checked } }); toast(e.target.checked ? "Включено" : "Выключено"); }
    catch (ex) { e.target.checked = !e.target.checked; toast(errorText(ex), true); }
  } }), a.enabled ? "да" : "нет") : (a.enabled ? "да" : "нет"));
  const create = write ? h("button", { class: "btn primary", type: "button", onclick: async () => {
    const done = await dialog({
      title: "Новое достижение",
      text: "Условие — один из счётчиков игрока, который ведёт сервер. Достижение даётся один раз.",
      fields: [
        { name: "code", label: "Код (латиница, цифры, _)", required: true, minlength: 3, maxlength: 32, placeholder: "wins_250" },
        { name: "category", label: "Категория", type: "select", options: Object.entries(CAT), value: "game" },
        { name: "metric", label: "Условие", type: "select", options: Object.entries(METRIC).filter(([k]) => !["high_wins", "win_run"].includes(k)), value: "wins" },
        ...achFields(),
      ],
      ok: "Создать",
      submit: (v) => api("/admin/games/achievements", { method: "POST", body: { code: v.code, category: v.category, metric: v.metric, ...achBody(v) } }),
    });
    if (done) { toast("Достижение создано"); ctx.go("progress/achievements"); }
  } }, "Создать достижение") : null;
  return h("div", {},
    h("div", { class: "actions panel flat" }, create),
    h("section", { class: "panel" },
      table([
        { label: "", cell: (a) => a.icon },
        { label: "Достижение", cell: (a) => h("span", {}, h("b", {}, ru(a.names)), h("br"), h("span", { class: "muted small" }, ru(a.descriptions))) },
        { label: "Категория", cell: (a) => CAT[a.category] || a.category },
        { label: "Условие", cell: (a) => `${METRIC[a.metric] || a.metric} ≥ ${fmtInt(a.threshold)}` },
        { label: "XP", cell: (a) => String(a.xp_reward), r: true },
        { label: "Титул", cell: (a) => a.title || "—" },
        { label: "Получили", cell: (a) => fmtInt(a.unlocked_by), r: true },
        { label: "Включено", cell: toggle },
        { label: "", cell: (a) => (write ? h("button", { class: "btn", type: "button", onclick: async () => {
          const done = await dialog({ title: `${a.icon} ${ru(a.names)}`, text: `Код ${a.code}, условие: ${METRIC[a.metric] || a.metric}.`, fields: achFields(a),
            submit: (v) => api(`/admin/games/achievements/${a.id}`, { method: "PATCH", body: achBody(v) }) });
          if (done) { toast("Сохранено"); ctx.go("progress/achievements"); }
        } }, "Изменить") : "") },
      ], list, { empty: "Достижений нет." })));
}

// ------------------------------------------------------------------ challenges
async function challengesView(ctx) {
  const write = ctx.can("games:write");
  const list = await api("/admin/games/challenges");
  const fields = (c = {}) => [
    { name: "name_ru", label: "Текст (рус.)", value: c.names?.ru || "", required: true, maxlength: 80 },
    { name: "name_en", label: "Текст (англ.)", value: c.names?.en || "", required: true, maxlength: 80 },
    { name: "target", label: "Сколько нужно", type: "number", min: 1, max: 1000, value: c.target ?? 3, required: true },
    { name: "xp_reward", label: "Награда XP", type: "number", min: 0, value: c.xp_reward ?? 30, required: true },
  ];
  const create = write ? h("button", { class: "btn primary", type: "button", onclick: async () => {
    const done = await dialog({
      title: "Новое задание дня",
      text: "Каждый день игрок получает одно лёгкое, одно среднее и одно сложное задание из включённых.",
      fields: [
        { name: "code", label: "Код (латиница, цифры, _)", required: true, minlength: 3, maxlength: 32, placeholder: "wins_4" },
        { name: "difficulty", label: "Сложность", type: "select", options: Object.entries(DIFF), value: "medium" },
        { name: "metric", label: "Что считать за день", type: "select", options: ["rounds", "wins", "blackjacks", "high_wins", "win_run"].map((k) => [k, METRIC[k]]), value: "wins" },
        ...fields(),
      ],
      ok: "Создать",
      submit: (v) => api("/admin/games/challenges", { method: "POST", body: { code: v.code, difficulty: v.difficulty, metric: v.metric, names: { ru: v.name_ru, en: v.name_en }, target: v.target, xp_reward: v.xp_reward } }),
    });
    if (done) { toast("Задание создано"); ctx.go("progress/challenges"); }
  } }, "Создать задание") : null;
  return h("div", {},
    h("div", { class: "actions panel flat" }, create),
    h("section", { class: "panel" },
      table([
        { label: "Сложность", cell: (c) => DIFF[c.difficulty] || c.difficulty },
        { label: "Задание", cell: (c) => h("b", {}, ru(c.names)) },
        { label: "Условие", cell: (c) => `${METRIC[c.metric] || c.metric}: ${c.target}` },
        { label: "XP", cell: (c) => String(c.xp_reward), r: true },
        { label: "Включено", cell: (c) => (write ? h("label", { class: "check" }, h("input", { type: "checkbox", checked: c.enabled, onchange: async (e) => {
          try { await api(`/admin/games/challenges/${c.id}`, { method: "PATCH", body: { enabled: e.target.checked } }); toast(e.target.checked ? "Включено" : "Выключено"); }
          catch (ex) { e.target.checked = !e.target.checked; toast(errorText(ex), true); }
        } }), c.enabled ? "да" : "нет") : (c.enabled ? "да" : "нет")) },
        { label: "", cell: (c) => (write ? h("button", { class: "btn", type: "button", onclick: async () => {
          const done = await dialog({ title: ru(c.names), text: `Код ${c.code}.`, fields: fields(c),
            submit: (v) => api(`/admin/games/challenges/${c.id}`, { method: "PATCH", body: { names: { ru: v.name_ru, en: v.name_en }, target: v.target, xp_reward: v.xp_reward } }) });
          if (done) { toast("Сохранено"); ctx.go("progress/challenges"); }
        } }, "Изменить") : "") },
      ], list, { empty: "Заданий нет." })));
}

// ------------------------------------------------------------------ XP, levels, rewards settings
const RULE_GROUPS = [
  ["Что включено", ["games.achievements.enabled", "games.challenges.enabled", "games.seasons.enabled", "games.rewards.bonus_days_enabled"]],
  ["XP за партии", ["games.xp.round", "games.xp.win", "games.xp.blackjack", "games.xp.daily_round_cap"]],
  ["Уровни", ["games.levels.base_xp", "games.levels.step_xp", "games.levels.titles"]],
  ["Рейтинги и сезоны", ["games.leaderboard.min_rounds_winrate", "games.seasons.min_rounds", "games.seasons.board", "games.seasons.participation_xp", "games.seasons.rewards_weekly", "games.seasons.rewards_monthly", "games.timezone"]],
  ["Серия дней", ["games.streak.rewards"]],
];

async function rulesView(ctx) {
  if (!ctx.can("settings:read")) return h("p", { class: "empty" }, "Нужно право смотреть настройки.");
  const all = await api("/admin/settings");
  const write = ctx.can("settings:write");
  return h("div", {},
    h("p", { class: "muted small" }, "Бонусные дни VPN за игру (games.rewards.bonus_days_enabled) держите выключенными до проверки юристом. Пока они выключены, награды — XP, титулы, рамки и достижения; оплаченные дни подписки игра не трогает никогда."),
    RULE_GROUPS.map(([title, keys]) => h("section", {}, h("h2", {}, title), keys.filter((k) => all[k]).map((k) => editor(k, all[k], write)))));
}

