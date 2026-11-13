// Mini Games: Jungle Kong Blackjack. The server decides everything (cards, turns, balances);
// this module only draws the table it is given and sends the player's choices.
// Built with the app's own helpers and styles (passed in by app.js) so it looks like the rest.

const SUIT = { S: "♠", H: "♥", D: "♦", C: "♣" };
const RANK = { T: "10" };
const LIVE = ["insurance", "playing"];
const FRAMES = ["idle", "blink", "eat1", "eat2", "happy", "sad"];

export function initGames(d) {
  const { h, api, t, toast, store, root, setBack, goHome, page, tg, lang } = d;
  const nf = new Intl.NumberFormat(lang === "ru" ? "ru-RU" : "en-GB", { maximumFractionDigits: 1 });
  const days = (hours) => nf.format(hours / 24);
  const uid = () => Array.from(crypto.getRandomValues(new Uint8Array(9)), (b) => b.toString(16).padStart(2, "0")).join("");
  const errText = (e) => (e.code && t("gErr")[e.code]) || e.message || t("gErrGeneric");
  for (const f of FRAMES) new Image().src = `assets/dealer-${f}.webp`; // warm the cache
  // replaceChildren that skips empty slots (a bare null would be printed as the word "null")
  const put = (el, ...kids) => el.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));

  // ------------------------------------------------------------------ sound (synthesised)
  let audio = null;
  const soundOn = () => store.get("vpnhub.sound") !== "off";
  function tone(freq, at, len, type = "sine", gain = 0.07) {
    const o = audio.createOscillator(), g = audio.createGain();
    o.type = type; o.frequency.value = freq;
    g.gain.setValueAtTime(0, audio.currentTime + at);
    g.gain.linearRampToValueAtTime(gain, audio.currentTime + at + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + at + len);
    o.connect(g).connect(audio.destination);
    o.start(audio.currentTime + at); o.stop(audio.currentTime + at + len + 0.02);
  }
  const SOUNDS = {
    card: () => { tone(900, 0, 0.05, "triangle", 0.05); tone(500, 0.02, 0.05, "triangle", 0.04); },
    chip: () => { tone(1500, 0, 0.05, "square", 0.03); tone(2000, 0.05, 0.06, "square", 0.03); },
    win: () => [523, 659, 784, 1047].forEach((f, i) => tone(f, i * 0.09, 0.22)),
    blackjack: () => [523, 659, 784, 1047, 1319, 1568].forEach((f, i) => tone(f, i * 0.07, 0.3)),
    lose: () => [392, 330, 262].forEach((f, i) => tone(f, i * 0.13, 0.28, "sine", 0.06)),
    push: () => { tone(440, 0, 0.15); tone(440, 0.18, 0.15); },
    chomp: () => { tone(180, 0, 0.07, "sawtooth", 0.04); tone(140, 0.09, 0.07, "sawtooth", 0.04); },
    turn: () => tone(880, 0, 0.12, "sine", 0.05),
  };
  function play(name) {
    if (!soundOn()) return;
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      if (audio.state === "suspended") audio.resume();
      SOUNDS[name]?.();
    } catch { /* no audio on this device */ }
  }

  // ------------------------------------------------------------------ small pieces
  function sub(title, back, ...content) { // an inner game screen (no monkey swing)
    window.scrollTo(0, 0);
    put(root, 
      h("header", { class: "bar" },
        h("button", { class: "ghost back", onclick: back, "aria-label": t("back") }, "‹"),
        h("h1", {}, title)),
      ...content.flat().filter(Boolean));
    setBack(back);
  }

  function card(c, cls = "") {
    if (c === "??") return h("div", { class: `pc back ${cls}` }, h("img", { src: "assets/logo.png", alt: "" }));
    const r = RANK[c[0]] || c[0], s = c[1];
    return h("div", { class: `pc ${s === "H" || s === "D" ? "red" : ""} ${cls}`, "aria-label": `${r}${SUIT[s]}` },
      h("span", { class: "pc-r" }, r), h("span", { class: "pc-s" }, SUIT[s]), h("span", { class: "pc-big" }, SUIT[s]));
  }

  const avatar = (name, seat) => h("span", { class: `av av-${seat}` }, (name || "?").trim().charAt(0).toUpperCase());

  // ------------------------------------------------------------------ hub
  async function gamesScreen(viaPage = true) {
    let hub;
    try { hub = await api("/games"); } catch (e) { toast(errText(e)); return; }
    const name = tg?.initDataUnsafe?.user?.first_name;
    if (hub.profile && name && /^Player [0-9A-F]{4}$/.test(hub.profile.nickname)) {
      try { hub.profile = await api("/games/profile", { method: "PUT", body: { nickname: name } }); } catch { /* keep the default */ }
    }
    const p = hub.profile || { rounds: 0, wins: 0, blackjacks: 0, best_streak: 0 };
    const stat = (n, label) => h("div", {}, h("div", { class: "big" }, String(n)), h("div", { class: "lbl" }, label));
    const content = [
      h("section", { class: "card glow game-hero" },
        h("img", { class: "game-hero-img", src: "assets/dealer-idle.webp", alt: "" }),
        h("div", {},
          h("div", { class: "lbl" }, t("gKicker")),
          h("div", { class: "game-title" }, "Jungle Kong Blackjack"),
          h("p", { class: "small muted" }, t("gTagline")))),
      !hub.enabled ? h("p", { class: "card warn" }, t("gDisabled")) : [
        hub.room_id ? h("button", { class: "primary wide", onclick: () => resume(hub.room_id) }, t("gResume")) : null,
        h("button", { class: hub.room_id ? "secondary wide" : "primary wide", onclick: playSolo }, t("gSolo")),
        hub.multiplayer ? h("button", { class: "secondary wide", onclick: () => friendsScreen() }, t("gFriends")) : null,
      ],
      h("section", { class: "card" },
        h("div", { class: "card-title" }, t("gBonus"),
          h("span", { class: "pill solid" }, `${days(hub.balance_hours)} ${t("gDaysShort")}`)),
        h("p", { class: "small muted" }, hub.stakes ? t("gBonusStakes") : t("gBonusFun")),
        h("button", { class: "secondary wide", onclick: walletScreen }, t("gWallet"))),
      h("section", { class: "card stats4g" },
        stat(p.rounds, t("gRounds")), stat(p.wins, t("gWins")), stat(p.blackjacks, t("gBlackjacks")), stat(p.best_streak, t("gStreak"))),
      h("div", { class: "row2" },
        h("button", { class: "secondary", onclick: historyScreen }, t("gHistory")),
        h("button", { class: "secondary", onclick: leaderboardScreen }, t("gLeaders"))),
    ];
    if (viaPage) page(t("gTitle"), ...content.flat().filter(Boolean));
    else sub(t("gTitle"), goHome, content);
  }
  const backToHub = () => gamesScreen(false);

  async function playSolo() {
    try { openTable(await api("/games/rooms/solo", { method: "POST" })); } catch (e) { toast(errText(e)); }
  }
  async function resume(roomId) {
    try { openTable(await api(`/games/rooms/${roomId}`)); } catch (e) { toast(errText(e)); backToHub(); }
  }
  async function joinByCode(code) {
    try { openTable(await api("/games/rooms/join", { method: "POST", body: { code: String(code).trim().toUpperCase() } })); }
    catch (e) { toast(errText(e)); }
  }

  // ------------------------------------------------------------------ friends: create / join / open tables
  async function friendsScreen() {
    let seats = 2, vis = "private";
    const seg = (items, get, set) => {
      const box = h("div", { class: "seg" });
      const draw = () => put(box, ...items.map(([v, label]) =>
        h("button", { class: get() === v ? "on" : "", onclick: () => { set(v); draw(); } }, label)));
      draw();
      return box;
    };
    const code = h("input", { id: "bj-code", placeholder: "ABC123", maxlength: 8, autocapitalize: "characters", autocomplete: "off" });
    const list = h("div", {}, h("p", { class: "muted small" }, t("loading")));
    sub(t("gFriends"), backToHub,
      h("section", { class: "card" },
        h("div", { class: "card-title" }, t("gCreate")),
        h("label", {}, t("gSeats")), seg([[2, "2"], [3, "3"], [4, "4"]], () => seats, (v) => { seats = v; }),
        h("label", {}, t("gVisibility")), seg([["private", t("gPrivate")], ["public", t("gPublic")]], () => vis, (v) => { vis = v; }),
        h("button", { class: "primary wide", onclick: async () => {
          try { openTable(await api("/games/rooms", { method: "POST", body: { max_players: seats, visibility: vis } })); }
          catch (e) { toast(errText(e)); }
        } }, t("gCreateBtn"))),
      h("section", { class: "card" },
        h("div", { class: "card-title" }, t("gJoinCode")),
        h("div", { class: "row" }, code, h("button", { class: "primary", onclick: () => code.value.trim() && joinByCode(code.value) }, t("gJoin")))),
      h("section", { class: "card" }, h("div", { class: "card-title" }, t("gOpenTables")), list));
    try {
      const rooms = await api("/games/rooms");
      put(list, ...(rooms.length ? rooms.map((r) =>
        h("div", { class: "device" },
          h("div", { class: "dev-main" }, h("strong", {}, `${t("gTable")} ${r.code}`),
            h("div", { class: "small muted" }, t("gPlayersN", { n: r.players, m: r.max_players }))),
          h("button", { class: "secondary", onclick: async () => {
            try { openTable(await api("/games/rooms/join", { method: "POST", body: { room_id: r.id } })); }
            catch (e) { toast(errText(e)); friendsScreen(); }
          } }, t("gJoin")))) : [h("p", { class: "muted small" }, t("gNoTables"))]));
    } catch (e) { put(list, h("p", { class: "warn small" }, errText(e))); }
  }

  // ------------------------------------------------------------------ the table
  let table = null; // the open table: connection, timers, last view

  function closeTable() {
    if (!table) return;
    table.alive = false;
    try { table.ws?.close(); } catch { /* already closed */ }
    for (const id of table.timers) clearTimeout(id);
    clearInterval(table.poll);
    table = null;
  }

  function openTable(view) {
    closeTable();
    const el = {
      dealerImg: h("img", { class: "bj-dealer-img", src: "assets/dealer-idle.webp", alt: "" }),
      dealerCards: h("div", { class: "bj-cards bj-dealer-cards" }),
      dealerTotal: h("span", { class: "bj-total" }),
      banner: h("div", { class: "bj-banner", role: "status" }),
      status: h("div", { class: "bj-status" }),
      timer: h("div", { class: "bj-timer" }, h("i", {})),
      seats: h("div", { class: "bj-seats" }),
      controls: h("div", { class: "bj-controls" }),
      foot: h("div", { class: "bj-foot" }),
      offline: h("div", { class: "bj-offline", hidden: true }, t("gOffline")),
    };
    const snd = h("button", { class: "ghost bj-snd", "aria-label": t("gSound") });
    const drawSnd = () => { snd.textContent = soundOn() ? "🔊" : "🔇"; };
    snd.addEventListener("click", () => { store.set("vpnhub.sound", soundOn() ? "off" : "on"); drawSnd(); play("chip"); });
    drawSnd();
    table = { id: view.id, view: null, alive: true, ws: null, wsOk: false, poll: null, timers: new Set(), seen: new Set(),
      roundNo: -1, settledShown: -1, stake: null, busy: false, mood: "idle", el };
    const leaveScreen = () => { closeTable(); backToHub(); };
    window.scrollTo(0, 0);
    put(root, 
      h("header", { class: "bar" },
        h("button", { class: "ghost back", onclick: leaveScreen, "aria-label": t("back") }, "‹"),
        h("h1", {}, "Blackjack"), snd),
      el.offline,
      h("section", { class: "bj" },
        h("div", { class: "bj-dealer" }, el.dealerImg, h("div", { class: "bj-dealer-row" }, el.dealerCards, el.dealerTotal)),
        h("div", { class: "bj-felt" }, el.banner, el.status, el.timer, el.seats),
        el.controls),
      el.foot);
    setBack(leaveScreen);
    apply(view);
    connect();
    idleLoop();
  }

  const later = (fn, ms) => { const tb = table; const id = setTimeout(() => { tb.timers.delete(id); if (tb.alive) fn(); }, ms); tb.timers.add(id); return id; };

  function setMood(frame, holdMs) {
    if (!table) return;
    table.el.dealerImg.src = `assets/dealer-${frame}.webp`;
    table.mood = frame;
    if (holdMs) later(() => { if (table.mood === frame) setMood("idle"); }, holdMs);
  }

  function idleLoop() { // blinking, and a banana between rounds
    const tb = table;
    const tick = () => {
      if (!tb.alive) return;
      const resting = tb.view && !LIVE.includes(tb.view.phase);
      if (tb.mood === "idle") {
        if (resting && Math.random() < 0.3) {
          play("chomp");
          ["eat1", "eat2", "eat1", "eat2"].forEach((f, i) => later(() => setMood(f), i * 420));
          later(() => setMood("idle"), 4 * 420 + 300);
        } else { setMood("blink"); later(() => { if (tb.mood === "blink") setMood("idle"); }, 160); }
      }
      later(tick, 2600 + Math.random() * 2200);
    };
    later(tick, 1800);
  }

  // --- networking: WebSocket push, with polling whenever the socket is down
  function connect() {
    const tb = table;
    const url = `${location.origin.replace(/^http/, "ws")}/api/v1/games/ws`;
    let tries = 0;
    const open = () => {
      if (!tb.alive) return;
      let ws;
      try { ws = new WebSocket(url); } catch { tb.wsOk = false; return; }
      tb.ws = ws;
      ws.onopen = () => { ws.send(JSON.stringify({ token: d.getToken(), room: tb.id })); };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        tries = 0; tb.wsOk = true; tb.el.offline.hidden = true;
        if (msg.type === "room") apply(msg.room);
        if (msg.type === "left") { toast(t("gKicked")); closeTable(); backToHub(); }
      };
      ws.onclose = () => { tb.wsOk = false; if (tb.alive) later(open, Math.min(8000, 800 * 2 ** tries++)); };
      ws.onerror = () => { try { ws.close(); } catch { /* closing anyway */ } };
    };
    open();
    tb.poll = setInterval(async () => { // the fallback, and the keep-alive check
      if (!tb.alive || tb.wsOk || tb.busy) return;
      try { apply(await api(`/games/rooms/${tb.id}`)); tb.el.offline.hidden = true; }
      catch (e) {
        if (e.code === "forbidden" || e.code === "not_found") { closeTable(); backToHub(); } else tb.el.offline.hidden = false;
      }
    }, 2500);
  }

  async function send(path, body) {
    const tb = table;
    if (!tb || tb.busy) return;
    tb.busy = true;
    tb.el.controls.classList.add("busy");
    const payload = { ...body, action_id: uid() };
    try {
      let view;
      try { view = await api(`/games/rooms/${tb.id}${path}`, { method: "POST", body: payload }); }
      catch (e) { // a network hiccup: the same action_id makes the retry safe
        if (e.code) throw e;
        view = await api(`/games/rooms/${tb.id}${path}`, { method: "POST", body: payload });
      }
      tb.el.offline.hidden = true;
      if (tb.alive) apply(view);
    } catch (e) {
      if (tb.alive) { toast(errText(e)); if (!e.code) tb.el.offline.hidden = false; }
    } finally {
      tb.busy = false;
      tb.el.controls.classList.remove("busy");
    }
  }

  // --- drawing
  function apply(view) {
    const tb = table;
    if (!tb || !tb.alive || (tb.view && view.version < tb.view.version)) return;
    const prev = tb.view;
    tb.view = view;
    if (view.round_no !== tb.roundNo) { tb.roundNo = view.round_no; tb.seen = new Set(); tb.holeShown = false; }
    let fresh = 0;
    const draw = (c, key) => { // cards not seen before fly in, one after another
      const isNew = !tb.seen.has(key);
      tb.seen.add(key);
      const node = card(c, isNew ? "deal" : "");
      if (isNew) { node.style.setProperty("--i", String(fresh++)); later(() => play("card"), (fresh - 1) * 130); }
      return node;
    };
    const r = view.round;
    const me = view.players.find((p) => p.me);
    const live = LIVE.includes(view.phase);

    // dealer
    if (r) {
      const hole = r.dealer.cards[1];
      const flip = hole !== "??" && !tb.holeShown && prev && prev.round && prev.round.dealer.cards[1] === "??";
      put(tb.el.dealerCards, ...r.dealer.cards.map((c, i) => {
        const node = draw(c, `d${i}:${c === "??" ? "x" : "v"}`);
        if (i === 1 && flip) node.classList.add("flip");
        return node;
      }));
      if (hole !== "??") tb.holeShown = true;
      tb.el.dealerTotal.textContent = String(r.dealer.total);
      tb.el.dealerTotal.hidden = false;
    } else { put(tb.el.dealerCards); tb.el.dealerTotal.hidden = true; }

    // seats
    tb.el.seats.className = `bj-seats n${view.players.length}`;
    put(tb.el.seats, ...view.players.map((p) => {
      const rs = r?.seats.find((s) => s.seat === p.seat);
      const res = r?.results?.seats.find((s) => s.seat === p.seat);
      const hands = (rs?.hands || []).map((hd, hi) => {
        const active = live && r.turn && r.turn.seat === p.seat && r.turn.hand === hi;
        const out = res?.hands[hi]?.outcome;
        return h("div", { class: `bj-hand ${active ? "active" : ""} ${out ? `out-${out}` : ""}` },
          h("div", { class: "bj-cards" }, ...hd.cards.map((c, ci) => draw(c, `s${p.seat}h${hi}c${ci}:${c}`))),
          h("div", { class: "bj-hand-meta" },
            h("span", { class: "bj-total" }, hd.blackjack ? "BJ" : String(hd.total)),
            hd.bet ? h("span", { class: "chip" }, `${days(hd.bet)}`) : null,
            out ? h("span", { class: `tag tag-${out}` }, t("gOut")[out]) : hd.doubled ? h("span", { class: "tag" }, "×2") : null));
      });
      const waiting = !rs && (live || view.phase === "betting" || view.phase === "settled");
      return h("div", { class: `bj-seat ${p.me ? "me" : ""} ${p.online || p.me ? "" : "off"}` },
        h("div", { class: "bj-name" }, avatar(p.nickname, p.seat), h("span", {}, p.me ? t("gYou") : p.nickname),
          p.ready && !live ? h("span", { class: "tag tag-win" }, "✓") : null),
        hands.length ? hands : h("div", { class: "bj-empty" }, waiting && live ? t("gNextRound") : ""));
    }));

    // status line + timer
    let status = "";
    if (view.status === "paused") status = t("gPaused");
    else if (view.phase === "insurance") status = t("gInsuranceQ");
    else if (view.phase === "playing" && r?.turn) {
      const who = view.players.find((p) => p.seat === r.turn.seat);
      status = who?.me ? t("gYourTurn") : t("gTurnOf", { name: who?.nickname || "…" });
    } else if (view.phase === "betting") status = t("gBetting", { n: view.players.filter((p) => p.ready).length, m: view.players.length });
    else if (view.phase === "waiting") status = t("gPlaceBet");
    tb.el.status.textContent = status;
    const left = view.deadline ? new Date(view.deadline) - new Date(view.server_time) : 0;
    const total = view.max_players > 1 && left > 0;
    tb.el.timer.hidden = !total;
    if (total && view.deadline !== prev?.deadline) {
      const bar = h("i", {});
      bar.style.setProperty("--ms", `${Math.max(0, left)}ms`);
      put(tb.el.timer, bar);
    }
    if (view.phase === "playing" && r?.turn && me && r.turn.seat === me.seat && !(prev?.round?.turn?.seat === me.seat && prev.phase === "playing")) play("turn");

    // result of the round
    if (view.phase === "settled" && tb.settledShown !== view.round_no && r?.results) {
      tb.settledShown = view.round_no;
      const mine = r.results.seats.find((s) => s.seat === me?.seat);
      if (mine) {
        const kind = mine.blackjack && mine.result === "win" ? "blackjack" : mine.result;
        const delay = 500 + fresh * 130;
        later(() => {
          tb.el.banner.className = `bj-banner show ${kind}`;
          put(tb.el.banner, h("strong", {}, t("gResult")[kind]),
            mine.net ? h("span", {}, `${mine.net > 0 ? "+" : "−"}${days(Math.abs(mine.net))} ${t("gDaysShort")}`) : null);
          play(kind);
          setMood(mine.result === "win" ? "sad" : mine.result === "lose" ? "happy" : "idle", 2600);
        }, delay);
      }
    }
    if (view.phase !== "settled") tb.el.banner.className = "bj-banner";

    drawControls(view, me, live);
    drawFoot(view);
  }

  function drawControls(view, me, live) {
    const tb = table, box = tb.el.controls;
    const btn = (label, cls, fn, extra) => h("button", { class: `${cls} bj-btn`, onclick: fn }, label, extra ? h("small", {}, extra) : null);
    if (view.status !== "open") { put(box, h("p", { class: "muted center" }, view.status === "paused" ? t("gPaused") : t("gClosed"))); return; }
    if (live) {
      const a = view.me.actions, x = view.me.extra_hours;
      const cost = (k) => (x[k] ? `${days(x[k])} ${t("gDaysShort")}` : null);
      if (!a.length) { put(box, h("p", { class: "muted center" }, view.me.in_round ? t("gWaitOthers") : t("gNextRound"))); return; }
      if (a.includes("insurance")) {
        put(box, h("div", { class: "bj-grid two" },
          btn(t("gInsurance"), "secondary", () => send("/actions", { action: "insurance" }), cost("insurance")),
          btn(t("gNoInsurance"), "primary", () => send("/actions", { action: "no_insurance" }))));
        return;
      }
      const act = (name) => () => { play("chip"); send("/actions", { action: name }); };
      put(box, 
        h("div", { class: "bj-grid two" }, btn(t("gHit"), "primary", act("hit")), btn(t("gStand"), "secondary", act("stand"))),
        h("div", { class: "bj-grid three" },
          a.includes("double") ? btn(t("gDouble"), "secondary", act("double"), cost("double")) : null,
          a.includes("split") ? btn(t("gSplit"), "secondary", act("split"), cost("split")) : null,
          a.includes("surrender") ? btn(t("gSurrender"), "ghost", act("surrender")) : null));
      return;
    }
    if (me?.ready) { put(box, h("p", { class: "muted center" }, t("gWaitOthers"))); return; }
    const again = view.round_no > 0;
    if (!view.stakes) {
      put(box, 
        btn(again ? t("gAgain") : t("gDeal"), "primary wide", () => { play("chip"); send("/bet", { stake_days: 0, client_seed: uid() }); }),
        h("p", { class: "small muted center" }, t("gFunNote")));
      return;
    }
    const opts = view.stake_options_days, bal = view.me.balance_hours;
    if (tb.stake === null || tb.stake * 24 > bal) tb.stake = opts.find((o) => o * 24 <= bal) ?? null;
    const chips = h("div", { class: "bj-stakes" }, ...opts.map((o) =>
      h("button", { class: `stake ${tb.stake === o ? "on" : ""}`, disabled: o * 24 > bal, onclick: () => { tb.stake = o; play("chip"); drawControls(view, me, live); } },
        h("b", {}, String(o)), h("small", {}, t("gDaysShort")))));
    put(box, 
      h("p", { class: "small muted center" }, t("gBalance", { n: days(bal) })),
      chips,
      tb.stake === null
        ? h("p", { class: "warn center small" }, t("gNoBonus"))
        : btn(t("gConfirmStake", { n: tb.stake }), "primary wide", () => { play("chip"); send("/bet", { stake_days: tb.stake, client_seed: uid() }); }));
  }

  function drawFoot(view) {
    const tb = table, multi = view.max_players > 1;
    const link = d.botLink() ? `${d.botLink()}?start=room_${view.code}` : null;
    put(tb.el.foot, 
      multi ? h("section", { class: "card small bj-invite" },
        h("div", {}, h("span", { class: "muted" }, `${t("gTable")} `), h("strong", { class: "bj-code" }, view.code),
          h("span", { class: "muted" }, ` · ${view.visibility === "public" ? t("gPublic") : t("gPrivate")} · ${view.players.length}/${view.max_players}`)),
        h("div", { class: "row" },
          h("button", { class: "secondary", onclick: async () => {
            try { await navigator.clipboard.writeText(link || view.code); toast(t("copied")); } catch { toast(view.code); }
          } }, t("gCopyCode")),
          link ? h("button", { class: "secondary", onclick: () => {
            const u = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(t("gInviteText", { app: d.appName }))}`;
            if (tg?.openTelegramLink) tg.openTelegramLink(u); else window.open(u, "_blank", "noopener");
          } }, t("gInvite")) : null)) : null,
      h("div", { class: "bj-links" },
        h("button", { class: "ghost small", onclick: () => fairSheet(view) }, t("gFair")),
        h("button", { class: "ghost small", onclick: () => rulesSheet() }, t("gRules")),
        h("button", { class: "ghost small danger", onclick: async () => {
          const id = tb.id; closeTable();
          try { await api(`/games/rooms/${id}/leave`, { method: "POST" }); } catch { /* already gone */ }
          backToHub();
        } }, t("gLeave"))));
  }

  // ------------------------------------------------------------------ sheets
  function sheet(title, ...content) {
    const wrap = h("div", { class: "sheet-wrap" });
    const close = () => wrap.remove();
    wrap.append(h("div", { class: "sheet card", role: "dialog", "aria-label": title },
      h("div", { class: "card-title" }, title, h("button", { class: "ghost", onclick: close, "aria-label": t("back") }, "✕")),
      ...content.flat().filter(Boolean)));
    wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
    document.body.append(wrap);
    return wrap;
  }

  async function rulesSheet() {
    let r = null;
    try { r = (await api("/games")).rules; } catch { /* show the general rules */ }
    sheet(t("gRules"), h("ul", { class: "steps" }, ...t("gRulesList")(r).map((x) => h("li", {}, x))));
  }

  async function sha256hex(s) {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
    return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
  }
  // The same shuffle as the server (backend/app/games/fair.py), run on this device.
  async function shuffledShoe(serverSeed, clientSeed, nonce, decks) {
    const enc = new TextEncoder();
    const key = await crypto.subtle.importKey("raw", enc.encode(serverSeed), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const shoe = [];
    for (let k = 0; k < decks; k++) for (const s of "SHDC") for (const r of "A23456789TJQK") shoe.push(r + s);
    let counter = 0, block = [], pos = 8;
    const next = async () => {
      if (pos >= 8) {
        const sig = new DataView(await crypto.subtle.sign("HMAC", key, enc.encode(`${clientSeed}:${nonce}:${counter++}`)));
        block = Array.from({ length: 8 }, (_, i) => sig.getUint32(i * 4));
        pos = 0;
      }
      return block[pos++];
    };
    for (let i = shoe.length - 1; i > 0; i--) {
      const span = i + 1, limit = 2 ** 32 - (2 ** 32 % span);
      let x;
      do { x = await next(); } while (x >= limit);
      const j = x % span;
      [shoe[i], shoe[j]] = [shoe[j], shoe[i]];
    }
    return shoe;
  }

  function fairSheet(view) {
    const f = view.last_fair;
    const out = h("p", { class: "small" });
    const mono = (label, v) => h("div", { class: "fair-row" }, h("span", { class: "lbl" }, label), h("code", {}, v));
    sheet(t("gFair"),
      h("p", { class: "small muted" }, t("gFairText")),
      mono(t("gFairNext"), view.next_seed_hash),
      f ? [
        h("div", { class: "card-sub" }, t("gFairLast", { n: f.number })),
        mono(t("gFairHash"), f.server_seed_hash), mono(t("gFairSeed"), f.server_seed), mono(t("gFairClient"), f.client_seed),
        h("button", { class: "secondary wide", onclick: async () => {
          try {
            const okHash = (await sha256hex(f.server_seed)) === f.server_seed_hash;
            const shoe = await shuffledShoe(f.server_seed, f.client_seed, f.number, f.decks);
            const r = view.round;
            const n = r.seats.length;
            const dealt = r.seats.every((s, i) => { // deal order: first cards, dealer up, second cards, hole
              const first = s.hands[0].cards[0];
              return shoe[i] === first || s.hands.length > 1; // after a split the first hand still starts with it
            }) && shoe[n] === r.dealer.cards[0] && shoe[2 * n + 1] === r.dealer.cards[1];
            out.className = okHash && dealt ? "small ok" : "small warn";
            out.textContent = okHash && dealt ? t("gFairOk") : t("gFairBad");
          } catch { out.className = "small warn"; out.textContent = t("gFairUnavailable"); }
        } }, t("gFairCheck")),
        out,
      ] : h("p", { class: "small muted" }, t("gFairNone")));
  }

  // ------------------------------------------------------------------ wallet, history, leaderboard
  async function walletScreen() {
    let w, hub;
    try { [w, hub] = await Promise.all([api("/games/wallet"), api("/games")]); } catch (e) { toast(errText(e)); return; }
    const whole = Math.floor(w.balance_hours / 24);
    const amount = h("input", { id: "bj-redeem", type: "number", min: 1, max: whole, value: whole || 1, inputmode: "numeric" });
    sub(t("gWallet"), backToHub,
      h("section", { class: "card glow" },
        h("div", { class: "lbl" }, t("gBonus")),
        h("div", { class: "promo-num" }, `${days(w.balance_hours)} ${t("gDaysShort")}`),
        h("p", { class: "small muted" }, hub.stakes ? t("gBonusStakes") : t("gBonusFun"))),
      hub.redeem_enabled && whole >= 1 ? h("section", { class: "card" },
        h("div", { class: "card-title" }, t("gRedeem")),
        h("p", { class: "small muted" }, t("gRedeemText")),
        h("div", { class: "row" }, amount, h("button", { class: "primary", onclick: async () => {
          const n = Math.floor(Number(amount.value));
          if (!(n >= 1 && n <= whole)) { toast(t("gRedeemBad", { n: whole })); return; }
          try {
            await api("/games/wallet/redeem", { method: "POST", body: { days: n, action_id: uid() } });
            toast(t("gRedeemDone", { n }));
            walletScreen();
          } catch (e) { toast(errText(e)); }
        } }, t("gRedeemBtn")))) : null,
      h("section", { class: "card" },
        h("div", { class: "card-title" }, t("gLedger")),
        w.ledger.length ? h("ul", { class: "list" }, ...w.ledger.map((x) =>
          h("li", { class: "device" },
            h("div", { class: "dev-main" }, h("strong", {}, t("gKinds")[x.kind] || x.kind),
              h("div", { class: "small muted" }, new Date(x.at).toLocaleString(lang === "ru" ? "ru-RU" : "en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }))),
            h("strong", { class: x.delta_hours >= 0 ? "ok" : "warn" }, `${x.delta_hours >= 0 ? "+" : "−"}${days(Math.abs(x.delta_hours))}`))))
          : h("p", { class: "muted small" }, t("gLedgerEmpty"))));
  }

  async function historyScreen() {
    let rows;
    try { rows = await api("/games/history"); } catch (e) { toast(errText(e)); return; }
    sub(t("gHistory"), backToHub,
      rows.length ? h("section", { class: "card" }, h("ul", { class: "list" }, ...rows.map((x) =>
        h("li", { class: "device" },
          h("span", { class: `tag tag-${x.result}` }, t("gResult")[x.blackjack && x.result === "win" ? "blackjack" : x.result]),
          h("div", { class: "dev-main" },
            h("div", { class: "mini-cards" }, ...x.hands.flatMap((hd) => hd.cards ? hd.cards : []).slice(0, 6).map((c) => card(c, "mini"))),
            h("div", { class: "small muted" }, `${new Date(x.finished_at).toLocaleString(lang === "ru" ? "ru-RU" : "en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} · ${t("gDealer")} ${x.dealer?.total ?? "?"}`)),
          x.net_hours ? h("strong", { class: x.net_hours > 0 ? "ok" : "warn" }, `${x.net_hours > 0 ? "+" : "−"}${days(Math.abs(x.net_hours))}`) : null))))
        : h("p", { class: "card muted" }, t("gHistoryEmpty")));
  }

  async function leaderboardScreen() {
    let b;
    try { b = await api("/games/leaderboard"); } catch (e) { toast(errText(e)); return; }
    sub(t("gLeaders"), backToHub,
      b.my_rank ? h("p", { class: "card small" }, t("gMyRank", { n: b.my_rank })) : null,
      b.top.length ? h("section", { class: "card" }, h("ul", { class: "list" }, ...b.top.map((x) =>
        h("li", { class: `device ${x.me ? "me-row" : ""}` },
          h("span", { class: "rank-no" }, x.rank <= 3 ? ["🥇", "🥈", "🥉"][x.rank - 1] : String(x.rank)),
          h("div", { class: "dev-main" }, h("strong", {}, x.nickname),
            h("div", { class: "small muted" }, t("gLeaderRow", { r: x.rounds, b: x.blackjacks }))),
          h("strong", {}, `${x.wins} ${t("gWinsShort")}`)))))
        : h("p", { class: "card muted" }, t("gLeadersEmpty")));
  }

  return { gamesScreen, joinByCode, closeTable };
}
