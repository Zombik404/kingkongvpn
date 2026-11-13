import { api } from "../api.js";
import { h, table, pill, dialog, reasonField, toast, copyButton, fmtDateTime } from "../ui.js";

const STATUS_OPTIONS = [
  ["active", "Работает — принимает подключения"],
  ["draining", "Разгружается — новых не берёт, текущие работают"],
  ["maintenance", "Обслуживание — новых не берёт"],
  ["disabled", "Отключён — сервер отрезан, люди уйдут на другие"],
  ["provisioning", "Подготовка"],
];

function showToken(server, token) {
  const env = `NODE_ID=${server.id}\nNODE_TOKEN=${token}`;
  const dlg = h("dialog", {},
    h("h2", {}, "Токен сервера"),
    h("p", {}, "Показывается один раз. Впишите его в /etc/globalvpn/agent.env на сервере и перезапустите агента."),
    h("div", { class: "once" }, h("p", { class: "secret" }, env)),
    h("div", { class: "actions" }, copyButton(env), h("button", { class: "btn primary", type: "button", onclick: () => dlg.close() }, "Я сохранил")));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}

export async function serversPage(ctx) {
  const [locations, servers] = await Promise.all([api("/admin/vpn/locations"), api("/admin/vpn/servers")]);
  const write = ctx.can("servers:write");
  const locName = (id) => {
    const l = locations.find((x) => x.id === id);
    if (!l) return "—";
    const name = l.names.ru || l.names.en || l.city || l.country_code;
    return name.includes(l.country_code) ? name : `${name} (${l.country_code})`;
  };

  const addLocation = write ? h("button", { class: "btn", type: "button", onclick: async () => {
    const done = await dialog({
      title: "Новая локация",
      fields: [
        { name: "country_code", label: "Страна (2 буквы)", required: true, maxlength: 2, placeholder: "DE" },
        { name: "city", label: "Город", maxlength: 64, placeholder: "Frankfurt" },
        { name: "name_ru", label: "Название для людей (рус.)", maxlength: 64, placeholder: "Франкфурт" },
        { name: "name_en", label: "Название (англ.)", maxlength: 64, placeholder: "Frankfurt" },
      ],
      ok: "Добавить",
      submit: (v) => {
        const names = {};
        if (v.name_ru) names.ru = v.name_ru;
        if (v.name_en) names.en = v.name_en;
        return api("/admin/vpn/locations", { method: "POST", body: { country_code: v.country_code, city: v.city || null, names } });
      },
    });
    if (done) { toast("Локация добавлена"); ctx.go("servers"); }
  } }, "Добавить локацию") : null;

  const addServer = write && locations.length ? h("button", { class: "btn primary", type: "button", onclick: async () => {
    let created = null;
    const done = await dialog({
      title: "Подключить сервер",
      text: "Сервер получит токен для агента. Публичный ключ WireGuard можно не вводить — агент пришлёт его сам.",
      fields: [
        { name: "hostname", label: "Имя сервера", required: true, placeholder: "de-fra-1" },
        { name: "location_id", label: "Локация", type: "select", options: locations.map((l) => [l.id, locName(l.id)]), value: locations[0].id },
        { name: "ipv4", label: "Публичный IPv4", placeholder: "203.0.113.5" },
        { name: "ipv6", label: "Публичный IPv6 (необязательно)" },
        { name: "endpoint_port", label: "Порт WireGuard", type: "number", min: 1, max: 65535, value: 51820, required: true },
        { name: "max_peers", label: "Максимум подключений", type: "number", min: 1, max: 65000, value: 1500, required: true },
      ],
      ok: "Подключить",
      submit: async (v) => {
        created = await api("/admin/vpn/servers", { method: "POST", body: {
          hostname: v.hostname, location_id: v.location_id, ipv4: v.ipv4 || null, ipv6: v.ipv6 || null, endpoint_port: v.endpoint_port, max_peers: v.max_peers,
        } });
      },
    });
    if (done && created) { showToken(created.server, created.token); ctx.go("servers"); }
  } }, "Подключить сервер") : null;

  const serverTable = table([
    { label: "Сервер", cell: (s) => h("span", {}, h("span", { class: `dot ${s.accepting ? "good" : "bad"}`, title: s.accepting ? "принимает подключения" : "не принимает" }), h("b", {}, s.hostname), h("br"), h("span", { class: "muted small" }, `${s.ipv4 || s.ipv6}:${s.endpoint_port}`)) },
    { label: "Локация", cell: (s) => locName(s.location_id) },
    { label: "Статус", cell: (s) => pill(s.status) },
    { label: "Нагрузка", cell: (s) => h("span", { class: "num" }, h("span", { class: "meter" }, h("i", { class: s.load > 0.8 ? "hot" : null, style: { width: `${Math.min(100, Math.round(s.load * 100))}%` } })), `${s.peers} / ${s.max_peers}`) },
    { label: "Связь", cell: (s) => h("span", { class: s.heartbeat_fresh ? "ok-text" : "danger-text" }, s.last_heartbeat_at ? fmtDateTime(s.last_heartbeat_at) : "ещё не выходил") },
    { label: "Агент", cell: (s) => {
      const errs = Array.isArray(s.agent_errors) ? s.agent_errors : (s.agent_errors ? [String(s.agent_errors)] : []);
      return h("span", { class: "actions" }, s.agent_version || "—",
        s.in_sync === false ? h("span", { class: "pill warn", title: "сервер ещё не применил последние изменения" }, "догоняет") : null,
        errs.length ? h("span", { class: "pill bad", title: errs.join("\n") }, `ошибок: ${errs.length}`) : null);
    } },
    { label: "", cell: (s) => (write ? h("div", { class: "actions" },
      h("button", { class: "btn", type: "button", onclick: async (e) => {
        e.stopPropagation();
        const done = await dialog({
          title: `Сервер ${s.hostname}`,
          fields: [
            { name: "status", label: "Статус", type: "select", options: STATUS_OPTIONS, value: s.status },
            { name: "max_peers", label: "Максимум подключений", type: "number", min: 1, max: 65000, value: s.max_peers, required: true },
            { name: "location_id", label: "Локация", type: "select", options: locations.map((l) => [l.id, locName(l.id)]), value: s.location_id },
            reasonField,
          ],
          submit: (v) => api(`/admin/vpn/servers/${s.id}`, { method: "PATCH", body: v }),
        });
        if (done) { toast("Сервер обновлён"); ctx.go("servers"); }
      } }, "Изменить"),
      h("button", { class: "btn", type: "button", onclick: async (e) => {
        e.stopPropagation();
        let res = null;
        const done = await dialog({
          title: "Новый токен сервера", text: "Старый токен перестанет работать сразу — агент отключится, пока вы не впишете новый.", danger: true, ok: "Выпустить",
          fields: [reasonField],
          submit: async (v) => { res = await api(`/admin/vpn/servers/${s.id}/rotate-token`, { method: "POST", body: v }); },
        });
        if (done && res) showToken(s, res.token);
      } }, "Токен")) : "") },
  ], servers, { empty: "Серверов пока нет." });

  const locationTable = table([
    { label: "Локация", cell: (l) => locName(l.id) },
    { label: "Серверов", cell: (l) => `${l.healthy_servers} из ${l.servers} работают`, r: true },
    { label: "Видна людям", cell: (l) => (l.visible_to_users ? h("span", { class: "ok-text" }, "да") : h("span", { class: "muted" }, l.enabled ? "нет рабочих серверов" : "скрыта")) },
    { label: "", cell: (l) => (write ? h("button", { class: "btn", type: "button", onclick: async () => {
      try {
        await api(`/admin/vpn/locations/${l.id}`, { method: "PATCH", body: { enabled: !l.enabled } });
        toast(l.enabled ? "Локация скрыта" : "Локация показана");
        ctx.go("servers");
      } catch (ex) { toast(ex.message, true); }
    } }, l.enabled ? "Скрыть" : "Показать") : "") },
  ], locations, { empty: "Локаций пока нет. Добавьте первую, потом подключите сервер." });

  return h("div", {},
    h("div", { class: "page-head" }, h("h1", {}, "Серверы"), h("div", { class: "actions" }, addLocation, addServer)),
    h("section", { class: "panel" }, h("h2", {}, "VPN-серверы"), serverTable),
    h("section", { class: "panel" }, h("h2", {}, "Локации"), locationTable));
}
