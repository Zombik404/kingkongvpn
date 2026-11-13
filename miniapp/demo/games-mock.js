// The clickable demo's stand-in for the game server: one solo table against the dealer with
// fun chips. The shuffle is the real provably-fair one (src/fair.js), so "Verify this round"
// genuinely re-checks the demo's cards. Sample leaderboard rows are marked as samples.
import { sha256hex, shuffledShoe } from "../src/fair.js";
import { createProgress } from "./progress-mock.js";

const DECKS = 6;
const OPTIONS = [10, 20, 50, 100, 200, 500];
const DAILY = 1000;
const RANKV = { A: 11, T: 10, J: 10, Q: 10, K: 10 };
const value = (c) => RANKV[c[0]] || Number(c[0]);
const total = (cards) => {
  let t = 0, aces = 0;
  for (const c of cards) { t += value(c); if (c[0] === "A") aces++; }
  while (t > 21 && aces) { t -= 10; aces--; }
  return { t, soft: aces > 0 };
};
const natural = (h) => h.cards.length === 2 && total(h.cards).t === 21 && !h.split;
const hex = (n) => Array.from(crypto.getRandomValues(new Uint8Array(n)), (b) => b.toString(16).padStart(2, "0")).join("");


export function createGames(lang) {
  const ru = lang === "ru";
  const g = {
    profile: { nickname: ru ? "Демо-игрок" : "Demo player", rounds: 0, wins: 0, losses: 0, pushes: 0, blackjacks: 0, net_hours: 0, streak: 0, best_streak: 0, chips: DAILY, best_win: 0, best_win_stake: 0 },
    room: null,
    history: [],
    rounds: {},
    nextSeed: hex(32),
    version: 1,
    seen: new Set(),
    lastEvents: [],
  };
  const prog = createProgress(g.profile, g.history); // XP, levels, achievements, challenges, boards
  const SAMPLES = [["Mango ⋅ demo", 1500, 1000], ["Liana ⋅ demo", 750, 500], ["Toucan ⋅ demo", 400, 200], ["Jaguar ⋅ demo", 300, 200]];

  const extra = (r) => {
    const h = r.hands[r.turn];
    const out = {};
    if (h.cards.length === 2 && g.profile.chips >= h.bet) out.double = h.bet;
    if (h.cards.length === 2 && value(h.cards[0]) === value(h.cards[1]) && r.hands.length < 4 && g.profile.chips >= h.bet) out.split = h.bet;
    return out;
  };
  function actions(r) {
    if (!r || r.phase !== "playing") return [];
    const h = r.hands[r.turn];
    const a = ["hit", "stand"];
    const x = extra(r);
    if ("double" in x) a.push("double");
    if ("split" in x) a.push("split");
    if (h.cards.length === 2 && r.hands.length === 1) a.push("surrender");
    return a;
  }

  async function deal(stake, seed) {
    const p = g.profile;
    if (stake && !OPTIONS.includes(stake)) throw { status: 422, code: "bad_stake" };
    if (stake > p.chips) throw { status: 409, code: "no_chips" };
    g.lastEvents = [];
    p.chips -= stake;
    const number = (g.room.round_no || 0) + 1;
    const serverSeed = g.nextSeed;
    const clientSeed = `0=${seed}`;
    const shoe = await shuffledShoe(serverSeed, clientSeed, number, DECKS);
    const draw = () => shoe.shift();
    const first = draw(), up = draw(), second = draw(), hole = draw();
    const r = { id: `round-${number}`, number, stake, serverSeed, clientSeed, draw, phase: "playing", turn: 0,
      hands: [{ cards: [first, second], bet: stake, doubled: false, surrendered: false, done: false }], dealer: [up, hole], results: null };
    g.room.round_no = number;
    g.room.round = r;
    g.room.round_id = r.id;
    if (natural(r.hands[0]) || (["A", "T", "J", "Q", "K"].includes(up[0]) && total(r.dealer).t === 21)) finish(r);
    g.version++;
  }

  function nextHand(r) {
    while (r.turn < r.hands.length && r.hands[r.turn].done) r.turn++;
    if (r.turn >= r.hands.length) finish(r);
  }

  function act(action) {
    const r = g.room.round;
    if (!actions(r).includes(action)) throw { status: 409, code: "not_allowed" };
    const h = r.hands[r.turn];
    if (action === "hit") { h.cards.push(r.draw()); if (total(h.cards).t >= 21) h.done = true; }
    if (action === "stand") h.done = true;
    if (action === "double") { g.profile.chips -= h.bet; h.bet *= 2; h.doubled = true; h.cards.push(r.draw()); h.done = true; }
    if (action === "surrender") { h.surrendered = true; h.done = true; }
    if (action === "split") {
      g.profile.chips -= h.bet;
      const other = { cards: [h.cards.pop(), r.draw()], bet: h.bet, doubled: false, surrendered: false, done: false, split: true };
      h.cards.push(r.draw()); h.split = true;
      r.hands.splice(r.turn + 1, 0, other);
    }
    nextHand(r);
    g.version++;
  }

  function finish(r) {
    const live = r.hands.some((h) => !h.surrendered && total(h.cards).t <= 21);
    const dealerBJ = total(r.dealer).t === 21 && r.dealer.length === 2;
    if (live && !(r.hands.length === 1 && natural(r.hands[0]))) {
      while (total(r.dealer).t < 17) r.dealer.push(r.draw());
    }
    const d = total(r.dealer).t;
    let staked = 0, returned = 0;
    const hands = r.hands.map((h) => {
      const t = total(h.cards).t;
      staked += h.bet;
      let outcome, back;
      if (h.surrendered) [outcome, back] = ["surrender", h.bet - h.bet / 2];
      else if (natural(h)) [outcome, back] = dealerBJ ? ["push", h.bet] : ["blackjack", h.bet + (h.bet * 3) / 2];
      else if (t > 21) [outcome, back] = ["bust", 0];
      else if (dealerBJ) [outcome, back] = ["lose", 0];
      else if (d > 21 || t > d) [outcome, back] = ["win", 2 * h.bet];
      else if (t === d) [outcome, back] = ["push", h.bet];
      else [outcome, back] = ["lose", 0];
      returned += back;
      return { outcome, total: t, bet: h.bet, returned: back };
    });
    const net = returned - staked;
    const bj = hands.some((x) => x.outcome === "blackjack");
    const result = net > 0 ? "win" : net < 0 ? "lose" : "push";
    r.phase = "settled";
    r.turn = null;
    r.results = { dealer_total: d, dealer_blackjack: dealerBJ, seats: [{ seat: 0, staked, returned, net, result, blackjack: bj, hands }] };
    const p = g.profile;
    p.chips += returned;
    p.rounds++;
    if (result === "win") { p.wins++; p.streak++; p.best_streak = Math.max(p.best_streak, p.streak); }
    else if (result === "lose") { p.losses++; p.streak = 0; } else p.pushes++;
    if (bj) p.blackjacks++;
    if (r.stake && net > p.best_win) { p.best_win = net; p.best_win_stake = staked; p.best_win_at = new Date().toISOString(); }
    const summary = publicRound(r);
    g.rounds[r.id] = { round_id: r.id, number: r.number, server_seed: r.serverSeed, client_seed: r.clientSeed, decks: DECKS, summary };
    g.history.unshift({ round_id: r.id, finished_at: new Date().toISOString(), result, blackjack: bj, staked_hours: staked, returned_hours: returned, net_hours: net, currency: r.stake ? "chips" : null, dealer: summary.dealer, hands: summary.seats[0].hands, players: 1 });
    g.lastEvents = prog.onRound({ result, blackjack: bj, total: hands[0].total });
    g.room.last_fair = { round_id: r.id, number: r.number, server_seed: r.serverSeed, client_seed: r.clientSeed, decks: DECKS };
    g.nextSeed = hex(32);
  }

  function publicRound(r) {
    const settled = r.phase === "settled";
    return {
      phase: r.phase, turn: r.turn === null ? null : { seat: 0, hand: r.turn },
      dealer: { cards: settled ? [...r.dealer] : [r.dealer[0], "??"], total: settled ? total(r.dealer).t : value(r.dealer[0]) },
      seats: [{ seat: 0, bet: r.stake, insurance: 0, hands: r.hands.map((h) => ({ cards: [...h.cards], total: total(h.cards).t, soft: total(h.cards).soft, bet: h.bet, doubled: h.doubled, surrendered: h.surrendered, done: h.done, blackjack: natural(h) })) }],
      results: r.results,
    };
  }

  async function view() {
    const room = g.room, r = room.round;
    for (const f of Object.values(g.rounds)) f.server_seed_hash ??= await sha256hex(f.server_seed);
    if (room.last_fair) room.last_fair.server_seed_hash = await sha256hex(room.last_fair.server_seed);
    const live = r && r.phase === "playing";
    return {
      id: room.id, code: room.code, visibility: "private", max_players: 1, status: "open",
      phase: r ? r.phase : "waiting", round_no: room.round_no, version: g.version, deadline: null, server_time: new Date().toISOString(),
      stakes: false, stake_options_days: [], currency: "chips", stake_options: OPTIONS, round_currency: r && r.stake ? "chips" : null,
      next_seed_hash: await sha256hex(g.nextSeed),
      players: [{ seat: 0, nickname: g.profile.nickname, me: true, owner: true, online: true, ready: false, stake_days: 0 }],
      round: r ? publicRound(r) : null,
      me: { seat: 0, actions: live ? actions(r) : [], extra_hours: live ? extra(r) : {}, balance_hours: 0, chips: g.profile.chips, in_round: !!live,
        progress: r && r.phase === "settled" ? g.lastEvents : [] },
      last_fair: room.last_fair || null,
    };
  }

  function board() {
    const p = g.profile;
    const rows = SAMPLES.map(([nickname, w, s], i) => ({ nickname, best_win: w, stake: s, at: new Date(Date.now() - (i + 1) * 86400000).toISOString(), me: false }));
    if (p.best_win > 0) rows.push({ nickname: p.nickname, best_win: p.best_win, stake: p.best_win_stake, at: p.best_win_at, me: true });
    rows.sort((a, b) => b.best_win - a.best_win || a.at.localeCompare(b.at));
    const top = rows.map((x, i) => ({ ...x, rank: i + 1 }));
    const mine = top.find((x) => x.me);
    return { top, my_rank: mine ? mine.rank : null, my_best: p.best_win ? { win: p.best_win, stake: p.best_win_stake } : null };
  }

  /** Returns [status, body] or null when the path isn't a game route. */
  return async function route(method, p, body, q = new URLSearchParams()) {
    if (!p.startsWith("/games")) return null;
    try {
      if (p === "/games") return [200, { enabled: true, multiplayer: false, stakes: false, stake_options_days: [], redeem_enabled: false, balance_hours: 0, currency: "chips", chips: g.profile.chips, chips_daily: DAILY, chip_options: OPTIONS, profile: { ...g.profile }, progress: prog.card(), room_id: g.room ? g.room.id : null, rules: { decks: DECKS, dealer_hits_soft_17: false, blackjack_pays: [3, 2], allow_double: true, allow_split: true, allow_surrender: true, allow_insurance: false, max_hands: 4 } }];
      if (p === "/games/rooms/solo") { g.room ||= { id: "demo-table", code: "KONG42", round_no: 0, round: null }; return [200, await view()]; }
      const m = p.match(/^\/games\/rooms\/([^/]+)(\/\w+)?$/);
      if (m && g.room && m[1] === g.room.id) {
        if (method === "GET") return [200, await view()];
        if (body?.action_id && g.seen.has(body.action_id)) return [200, await view()];
        if (body?.action_id) g.seen.add(body.action_id);
        if (m[2] === "/bet") { if (g.room.round?.phase === "playing") throw { status: 409, code: "round_in_progress" }; await deal(Number(body.stake || 0), body.client_seed || "demo"); return [200, await view()]; }
        if (m[2] === "/actions") { act(body.action); return [200, await view()]; }
        if (m[2] === "/leave") { if (g.room.round?.phase === "playing") { while (g.room.round.phase === "playing") act("stand"); } g.room = null; return [204, null]; }
      }
      if (p === "/games/wallet") return [200, { balance_hours: 0, ledger: [] }];
      if (p === "/games/history") return [200, g.history.slice(0, 30)];
      if (p === "/games/leaderboard") return [200, board()];
      const pr = prog.route(method, p, q, body || {});
      if (pr) return pr;
      const f = p.match(/^\/games\/rounds\/([^/]+)\/fairness$/);
      if (f && g.rounds[f[1]]) { const x = g.rounds[f[1]]; return [200, { ...x, server_seed_hash: await sha256hex(x.server_seed) }]; }
      return [404, { error: { code: "not_found", message: "Not found" } }];
    } catch (e) {
      if (e && e.status) return [e.status, { error: { code: e.code, message: e.code } }];
      throw e;
    }
  };
}
