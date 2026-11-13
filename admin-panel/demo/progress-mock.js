// Demo stand-in for the staff progression API (/admin/games/progress, achievements, challenges,
// seasons). Catalogue = the server's own (generated for the Mini App demo); players are samples.
import CAT from "../../miniapp/demo/progress-catalogue.json";

const DAY = 864e5;
const iso = (t) => new Date(t).toISOString();
let seq = 1;
const id = () => `0a7e${(seq++).toString(16).padStart(4, "0")}-demo-4000-8000-${Math.random().toString(16).slice(2, 14).padEnd(12, "0")}`;
const cfg = CAT.cfg;
const toReach = (lv) => { const n = Math.max(0, lv - 1); return n * cfg["games.levels.base_xp"] + (cfg["games.levels.step_xp"] * n * (n - 1)) / 2; };
const levelFor = (xp) => { let lv = 1; while (toReach(lv + 1) <= xp) lv++; return lv; };
const titleFor = (lv) => { const k = Object.keys(cfg["games.levels.titles"]).map(Number).filter((x) => x <= lv).sort((a, b) => b - a)[0]; return k ? cfg["games.levels.titles"][String(k)] : ""; };

export function createAdminProgress({ audit, users, reasonOk, needReason, json, fail, page }) {
  const now = Date.now();
  const PLAYERS = [
    ["BananaKing", "🍌", 2380, 97, 117, 11, 9], ["Mango", "🐒", 1910, 61, 70, 7, 6], ["Liana", "🦜", 1440, 52, 66, 5, 3],
    ["Toucan", "🐸", 980, 40, 48, 3, 2], ["Jaguar", "🐆", 610, 33, 41, 2, 1], ["Kiwi", "🦥", 260, 9, 14, 1, 1],
  ].map(([nickname, avatar, xp, wins, losses, bj, streak], i) => {
    const level = levelFor(xp);
    return { user_id: users[i + 4]?.id || id(), nickname, avatar, frame: i === 0 ? "gold" : null, title: titleFor(level), level, xp, level_xp: toReach(level), next_level_xp: toReach(level + 1),
      rounds: wins + losses + 6, wins, losses, pushes: 6, blackjacks: bj, win_rate: Math.round((wins * 1000) / (wins + losses)) / 10, win_streak: 0, best_win_streak: 4 + (i % 3),
      day_streak: streak, best_day_streak: streak + 3, days_played: 20 - i * 2, excluded_at: null };
  });
  const ACH = CAT.achievements.map((a, i) => ({ id: id(), code: a.code, category: a.category, names: a.names, descriptions: a.descriptions, icon: a.icon, metric: a.metric,
    threshold: a.target, xp_reward: a.xp, title: a.title, sort_order: i, enabled: true, unlocked_by: Math.max(0, 6 - Math.floor(Math.log2(a.target + 1))) }));
  const CH = CAT.challenges.map((c) => ({ id: id(), code: c.code, difficulty: c.difficulty, names: c.names, metric: c.metric, target: c.target, xp_reward: c.xp, enabled: true }));
  const d = new Date();
  const wStart = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  const mStart = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1);
  const SEASONS = [
    { id: id(), kind: "weekly", name: "этой недели", starts_at: iso(wStart), ends_at: iso(wStart + 7 * DAY), status: "active", board: "xp", rewards: cfg["games.seasons.rewards_weekly"], finalized_at: null },
    { id: id(), kind: "monthly", name: "этого месяца", starts_at: iso(mStart), ends_at: iso(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1)), status: "active", board: "xp", rewards: cfg["games.seasons.rewards_monthly"], finalized_at: null },
    { id: id(), kind: "weekly", name: "прошлой недели", starts_at: iso(wStart - 7 * DAY), ends_at: iso(wStart), status: "closed", board: "xp", rewards: cfg["games.seasons.rewards_weekly"], finalized_at: iso(wStart + 300e3) },
  ];
  const visible = () => PLAYERS.filter((p) => !p.excluded_at);
  const ranking = (s, board = s.board) => {
    const scale = s.kind === "weekly" ? 0.2 : s.kind === "monthly" ? 0.6 : 0.1;
    const val = (p) => (board === "wins" ? Math.round(p.wins * scale) : board === "winrate" ? Math.round(p.win_rate * 100) : Math.round(p.xp * scale));
    return (s.status === "active" || s.kind === "event" ? visible() : PLAYERS).map((p) => ({ user_id: p.user_id, nickname: p.nickname, value: val(p) }))
      .sort((a, b) => b.value - a.value).map((r, i) => ({ rank: i + 1, ...r }));
  };
  const seasonOut = (s) => ({ ...s, participants: s.kind === "event" && s.status === "closed" ? 0 : visible().length, winners: s.status === "closed" ? ranking(s).slice(0, 3) : [] });
  const find = (arr, x) => arr.find((y) => y.id === x);

  return function route(method, path, q, b) {
    if (path === "/admin/games/progress/players") {
      const term = (q.get("q") || "").toLowerCase();
      let rows = [...PLAYERS].sort((a, c) => c.xp - a.xp);
      if (term) rows = rows.filter((p) => p.user_id === term || p.nickname.toLowerCase().includes(term));
      if (q.get("excluded")) rows = rows.filter((p) => p.excluded_at);
      return json(page(rows, q));
    }
    let m = path.match(/^\/admin\/games\/progress\/players\/([^/]+)(\/(exclude|include))?$/);
    if (m) {
      const p = PLAYERS.find((x) => x.user_id === m[1]);
      if (!p) return fail(404, "not_found", "This user hasn't played yet.");
      if (m[3]) {
        if (!reasonOk(b)) return needReason();
        const on = m[3] === "exclude";
        if (Boolean(p.excluded_at) !== on) { p.excluded_at = on ? iso(Date.now()) : null; audit(`game.player_${on ? "excluded" : "included"}`, "user", p.user_id, { reason: b.reason }); }
        return json({ user_id: p.user_id, excluded_at: p.excluded_at });
      }
      const got = ACH.filter((a) => (a.metric === "wins" && p.wins >= a.threshold) || (a.metric === "rounds" && p.rounds >= a.threshold) || (a.metric === "level" && p.level >= a.threshold) || (a.metric === "blackjacks" && p.blackjacks >= a.threshold));
      return json({ ...p, titles: [p.title, ...(p.frame ? ["King of Jungle"] : [])],
        achievements: got.map((a) => ({ ...a, unlocked_at: iso(now - 5 * DAY) })),
        challenges_today: CH.slice(0, 3).map((c, i) => ({ code: c.code, progress: Math.min(c.target, i + 1), target: c.target, completed_at: i + 1 >= c.target ? iso(now - 3600e3) : null })),
        seasons: SEASONS.map((s) => ({ name: s.name, kind: s.kind, status: s.status, rounds: Math.round(p.rounds * 0.2), wins: Math.round(p.wins * 0.2), losses: Math.round(p.losses * 0.2), xp: Math.round(p.xp * 0.2) })),
        xp_history: [["round", 15], ["challenge", 40], ["round", 5], ["achievement", 50]].map(([kind, amount], i) => ({ kind, amount, at: iso(now - i * 1800e3) })),
        rewards: p.frame ? [{ source: "season", ref: "прошлой недели #1", xp: 500, title: "King of Jungle", frame: "gold", bonus_days: 3, bonus_paid: false, at: iso(wStart + 300e3) }] : [] });
    }
    if (path === "/admin/games/achievements" && method === "GET") return json(ACH);
    if (path === "/admin/games/achievements") {
      if (ACH.some((a) => a.code === b.code)) return fail(409, "exists", "An achievement with this code already exists.");
      const a = { id: id(), sort_order: ACH.length, enabled: true, unlocked_by: 0, ...b };
      ACH.push(a); audit("game.achievement_created", "achievement", a.id, { code: a.code }); return json(a, 201);
    }
    m = path.match(/^\/admin\/games\/achievements\/([^/]+)$/);
    if (m) { const a = find(ACH, m[1]); Object.assign(a, b); audit("game.achievement_updated", "achievement", a.id, { fields: Object.keys(b) }); return json(a); }
    if (path === "/admin/games/challenges" && method === "GET") return json(CH);
    if (path === "/admin/games/challenges") {
      const c = { id: id(), enabled: true, ...b }; CH.push(c); audit("game.challenge_created", "challenge", c.id, { code: c.code }); return json(c, 201);
    }
    m = path.match(/^\/admin\/games\/challenges\/([^/]+)$/);
    if (m) { const c = find(CH, m[1]); Object.assign(c, b); audit("game.challenge_updated", "challenge", c.id, { fields: Object.keys(b) }); return json(c); }
    if (path === "/admin/games/seasons" && method === "GET") return json([...SEASONS].sort((a, c) => a.status.localeCompare(c.status) || c.ends_at.localeCompare(a.ends_at)).map(seasonOut));
    if (path === "/admin/games/seasons") {
      const s = { id: id(), kind: "event", status: "active", finalized_at: null, rewards: cfg["games.seasons.rewards_weekly"], ...b };
      SEASONS.unshift(s); audit("game.season_created", "season", s.id, { name: s.name }); return json(s, 201);
    }
    m = path.match(/^\/admin\/games\/seasons\/([^/]+)(\/(finish|results))?$/);
    if (m) {
      const s = find(SEASONS, m[1]);
      if (!s) return fail(404, "not_found", "No such season.");
      if (m[3] === "results") return json({ season: s, board: q.get("board") || s.board, rows: ranking(s, q.get("board") || s.board), live: s.status === "active" });
      if (!reasonOk(b)) return needReason();
      if (s.status !== "active") return fail(409, "season_closed", "This season is already closed.");
      if (m[3] === "finish") {
        s.status = "closed"; s.finalized_at = iso(Date.now()); if (Date.parse(s.ends_at) > Date.now()) s.ends_at = iso(Date.now());
        audit("game.season_finished", "season", s.id, { reason: b.reason }); return json({ ...s, prizes: Math.min(3, visible().length) });
      }
      const { reason, ...rest } = b;
      Object.assign(s, rest); audit("game.season_updated", "season", s.id, { reason, fields: Object.keys(rest) }); return json(s);
    }
    return null;
  };
}
