// Demo stand-in for the blackjack progression API (XP, levels, achievements, daily challenges,
// streak, boards, seasons). The catalogue and numbers come from the server's own defaults
// (progress-catalogue.json is generated from backend/app/games/catalogue.py); the other players
// are sample rows marked "demo".
import CAT from "./progress-catalogue.json";

const DAY = 864e5;
const AVATARS = ["🦍", "🐒", "🦧", "🦜", "🐆", "🐍", "🐸", "🦥", "🐘", "🐯", "🦩", "🍌"];
const cfg = CAT.cfg;
const toReach = (lv) => { const n = Math.max(0, lv - 1); return n * cfg["games.levels.base_xp"] + (cfg["games.levels.step_xp"] * n * (n - 1)) / 2; };
const levelFor = (xp) => { let lv = 1; while (toReach(lv + 1) <= xp) lv++; return lv; };
const levelTitle = (lv) => { const k = Object.keys(cfg["games.levels.titles"]).map(Number).filter((x) => x <= lv).sort((a, b) => b - a)[0]; return k ? cfg["games.levels.titles"][String(k)] : ""; };
const iso = (t) => new Date(t).toISOString();
const dayOf = (t) => iso(t).slice(0, 10);

export function createProgress(profile, history) {
  const now = Date.now();
  const P = {
    xp: 0, avatar: "🦍", title: null, frame: null,
    day_streak: 2, best_day_streak: 6, days_played: 9, last_day: dayOf(now - DAY), perfect_wins: 0,
    unlocked: {}, xpLog: [], rewards: [], doneChallenges: [],
    today: { rounds: 0, wins: 0, blackjacks: 0, high_wins: 0, win_run: 0, run: 0 },
    played: new Set([1, 2, 5, 6, 7, 8, 12].map((d) => dayOf(now - d * DAY))),
    seasonXp: 0,
  };
  // three challenges a day: one easy, one medium, one hard
  const pick = (d) => CAT.challenges.filter((c) => c.difficulty === d)[0];
  const TODAY = ["easy", "medium", "hard"].map(pick).filter(Boolean).map((c) => ({ ...c, completed_at: null }));

  const SAMPLE = [
    ["Mango", "🐒", 2380, 61, 44, "gold"], ["Liana", "🦜", 1910, 52, 41, "silver"], ["Toucan", "🐸", 1440, 40, 35, "bronze"],
    ["Jaguar", "🐆", 980, 33, 30, null], ["Sloth", "🦥", 610, 21, 24, null], ["Kiwi", "🍌", 260, 9, 11, null],
  ].map(([n, av, xp, wins, losses, frame]) => ({ nickname: `${n} ⋅ demo`, avatar: av, xp, wins, losses, frame, level: levelFor(xp), title: levelTitle(levelFor(xp)) }));

  const metric = (m) => ({
    wins: profile.wins, rounds: profile.rounds, blackjacks: profile.blackjacks, best_win_streak: profile.best_streak,
    perfect_wins: P.perfect_wins, days_played: P.days_played, best_day_streak: P.best_day_streak,
    level: levelFor(P.xp), xp: P.xp, season_rank: 0,
  })[m] ?? 0;

  function addXp(amount, kind, events) {
    if (!amount) return;
    const before = levelFor(P.xp);
    P.xp += amount; P.seasonXp += amount;
    P.xpLog.unshift({ amount, kind, at: iso(Date.now()) });
    if (kind === "round") events.push({ type: "xp", amount, kind });
    const after = levelFor(P.xp);
    if (after > before) events.push({ type: "level", level: after, title: levelTitle(after) });
  }

  function card() {
    const lv = levelFor(P.xp), decided = profile.wins + profile.losses;
    return {
      nickname: profile.nickname, avatar: P.avatar, frame: P.frame, title: P.title || levelTitle(lv),
      level: lv, xp: P.xp, level_xp: toReach(lv), next_level_xp: toReach(lv + 1), progress: (P.xp - toReach(lv)) / (toReach(lv + 1) - toReach(lv)), level_title: levelTitle(lv),
      rounds: profile.rounds, wins: profile.wins, losses: profile.losses, pushes: profile.pushes, blackjacks: profile.blackjacks,
      win_rate: decided ? Math.round((profile.wins * 1000) / decided) / 10 : null, win_streak: profile.streak, best_win_streak: profile.best_streak,
      day_streak: P.day_streak, best_day_streak: P.best_day_streak, days_played: P.days_played,
    };
  }

  /** After a settled round: what it gave, in the order the app shows it. */
  function onRound({ result, blackjack, total }) {
    const events = [];
    const win = result === "win";
    // the day counts once a round is finished (not for opening the app)
    const today = dayOf(Date.now());
    if (!P.played.has(today)) {
      P.played.add(today); P.days_played++;
      P.day_streak = P.last_day === dayOf(Date.now() - DAY) ? P.day_streak + 1 : 1;
      P.best_day_streak = Math.max(P.best_day_streak, P.day_streak); P.last_day = today;
      const tier = cfg["games.streak.rewards"][String(P.day_streak)];
      if (tier) {
        P.rewards.unshift({ source: "streak", ref: `${P.day_streak} days`, xp: tier.xp || 0, title: tier.title || null, frame: null, bonus_days: tier.bonus_days || 0, bonus_paid: false, at: iso(Date.now()) });
        events.push({ type: "reward", xp: tier.xp || 0, title: tier.title || null, bonus_days: 0 });
        addXp(tier.xp || 0, "streak", events);
      }
    }
    if (win && total === 21 && !blackjack) P.perfect_wins++;
    addXp(cfg["games.xp.round"] + (win ? cfg["games.xp.win"] : 0) + (blackjack ? cfg["games.xp.blackjack"] : 0), "round", events);
    const t = P.today;
    t.rounds++; if (win) { t.wins++; t.run++; t.win_run = Math.max(t.win_run, t.run); } else if (result === "lose") t.run = 0;
    if (blackjack) t.blackjacks++;
    if (win && total >= 20) t.high_wins++;
    for (const c of TODAY) {
      if (c.completed_at || (t[c.metric] ?? 0) < c.target) continue;
      c.completed_at = iso(Date.now());
      P.doneChallenges.unshift({ names: c.names, day: dayOf(Date.now()), xp: c.xp });
      events.push({ type: "challenge", names: c.names, xp: c.xp });
      addXp(c.xp, "challenge", events);
    }
    for (let pass = 0; pass < 2; pass++) { // an achievement's XP can unlock a level achievement
      for (const a of CAT.achievements) {
        if (P.unlocked[a.code] || metric(a.metric) < a.target) continue;
        P.unlocked[a.code] = iso(Date.now());
        events.push({ type: "achievement", icon: a.icon, names: a.names, xp: a.xp, title: a.title });
        addXp(a.xp, "achievement", events);
      }
    }
    const lv = events.filter((e) => e.type === "level").pop();
    return [...events.filter((e) => e.type !== "level"), ...(lv ? [lv] : [])];
  }

  const meRow = () => ({ ...card(), nickname: profile.nickname, me: true });
  function boardRows(board, period) {
    const scale = period === "weekly" ? 0.18 : period === "monthly" ? 0.55 : 1;
    const players = SAMPLE.map((s) => ({ ...s, xp: Math.round(s.xp * scale), wins: Math.round(s.wins * scale), losses: Math.round(s.losses * scale), me: false }));
    const mine = { ...meRow(), xp: period === "all" ? P.xp : P.seasonXp, wins: profile.wins, losses: profile.losses };
    const minRounds = 20;
    const val = (x) => (board === "xp" ? x.xp : board === "wins" ? x.wins : Math.round((x.wins * 10000) / Math.max(1, x.wins + x.losses)));
    let rows = [...players, mine].filter((x) => (board === "winrate" ? x.wins + x.losses >= minRounds : val(x) > 0));
    rows = rows.sort((a, b) => val(b) - val(a)).map((x, i) => ({ rank: i + 1, nickname: x.nickname, avatar: x.avatar, frame: x.frame, level: x.level, title: x.title, value: val(x), me: x.me }));
    return { rows, min_rounds: minRounds };
  }

  function seasonBounds(kind) {
    const d = new Date();
    if (kind === "weekly") {
      const start = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
      return [start, start + 7 * DAY];
    }
    return [Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1), Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1)];
  }
  function season(kind) {
    const [s, e] = seasonBounds(kind);
    return { id: `demo-${kind}`, kind, name: kind, starts_at: iso(s), ends_at: iso(e), board: "xp" };
  }

  function route(method, p, q, body) {
    if (p === "/games/me") {
      const lv = levelFor(P.xp);
      const titles = [...new Set([...Object.keys(cfg["games.levels.titles"]).map(Number).filter((x) => x <= lv).map((x) => cfg["games.levels.titles"][String(x)]),
        ...CAT.achievements.filter((a) => a.title && P.unlocked[a.code]).map((a) => a.title), ...P.rewards.filter((r) => r.title).map((r) => r.title)])];
      const got = CAT.achievements.filter((a) => P.unlocked[a.code]).sort((a, b) => P.unlocked[b.code].localeCompare(P.unlocked[a.code]));
      const all = boardRows("xp", "all").rows, wins = boardRows("wins", "all").rows;
      return [200, { ...card(), ranks: { xp: all.find((x) => x.me)?.rank ?? null, wins: wins.find((x) => x.me)?.rank ?? null }, titles, chosen_title: P.title, avatars: AVATARS,
        achievements: { unlocked: got.length, total: CAT.achievements.length, latest: got.slice(0, 6).map((a) => ({ ...a, unlocked_at: P.unlocked[a.code] })) },
        recent: history.slice(0, 5) }];
    }
    if (p === "/games/profile" && method === "PUT") {
      if (body.nickname) profile.nickname = String(body.nickname).slice(0, 24);
      if (body.avatar && AVATARS.includes(body.avatar)) P.avatar = body.avatar;
      if (body.title !== undefined) P.title = body.title || null;
      return [200, { ...profile, progress: card() }];
    }
    if (p === "/games/achievements") {
      return [200, CAT.achievements.map((a) => ({ ...a, progress: Math.min(metric(a.metric), a.target), unlocked_at: P.unlocked[a.code] || null }))];
    }
    if (p === "/games/challenges") {
      const nowT = Date.now(), d = new Date();
      const resets = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1);
      const rewards = Object.entries(cfg["games.streak.rewards"]).map(([days, r]) => ({ days: Number(days), ...r })).sort((a, b) => a.days - b.days);
      return [200, {
        enabled: true, day: dayOf(nowT), resets_at: iso(resets),
        today: TODAY.map((c) => ({ ...c, progress: Math.min(P.today[c.metric] ?? 0, c.target) })),
        streak: { current: P.day_streak, best: P.best_day_streak, played_today: P.played.has(dayOf(nowT)), next_reward: rewards.find((r) => r.days > P.day_streak) || null, rewards, bonus_days_enabled: false },
        calendar: [...P.played].map((day) => ({ day })), history: P.doneChallenges,
      }];
    }
    if (p === "/games/xp") return [200, P.xpLog.slice(0, Number(q.get("limit") || 50))];
    if (p === "/games/rewards") return [200, P.rewards];
    if (p === "/games/boards") {
      const board = q.get("board") || "xp", period = q.get("period") || "weekly", term = (q.get("q") || "").toLowerCase();
      const { rows, min_rounds } = boardRows(board, period);
      const found = term ? rows.filter((x) => x.nickname.toLowerCase().includes(term)) : rows;
      const off = Number(q.get("offset") || 0), lim = Number(q.get("limit") || 20);
      return [200, { board, period, rows: found.slice(off, off + lim), total: rows.length, me: rows.find((x) => x.me) || null, min_rounds, season: period === "all" ? null : season(period) }];
    }
    if (p === "/games/seasons") {
      const cur = ["weekly", "monthly"].map((kind) => {
        const { rows } = boardRows("xp", kind);
        return { ...season(kind), status: "active", participants: rows.length, top: rows.slice(0, 3), me: rows.find((x) => x.me) || null,
          my_rounds: profile.rounds, min_rounds: cfg["games.seasons.min_rounds"] ?? 10, rewards: cfg[`games.seasons.rewards_${kind}`] };
      });
      const [ws] = seasonBounds("weekly");
      const past = { id: "demo-past", kind: "weekly", name: "weekly", starts_at: iso(ws - 7 * DAY), ends_at: iso(ws), board: "xp",
        winners: SAMPLE.slice(0, 3).map((x, i) => ({ rank: i + 1, nickname: x.nickname })) };
      return [200, { now: iso(Date.now()), current: cur, events: [], archive: [past], bonus_days_enabled: false }];
    }
    const m = p.match(/^\/games\/seasons\/([^/]+)\/results$/);
    if (m) return [200, { rows: SAMPLE.map((x, i) => ({ rank: i + 1, nickname: x.nickname, avatar: x.avatar, frame: x.frame, value: Math.round(x.xp * 0.2), me: false })) }];
    return null;
  }

  return { card, onRound, route };
}
