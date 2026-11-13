// Blackjack progression screens (ADR-021): profile, leaderboards, achievements, daily challenges
// and streak, seasons, and the celebrations after a round. All numbers come from the server; this
// module only draws them with the app's own helpers and styles.

const MEDAL = ["🥇", "🥈", "🥉"];
const DIFF = { easy: "🌱", medium: "🌿", hard: "🌳" };

export function initProgress(d) {
  const { h, api, t, toast, lang, sub, sheet, back, nf, errText, store } = d;
  const L = (obj) => (obj ? obj[lang] || obj.en || Object.values(obj)[0] : "");
  const titleName = (x) => (x ? t("pTitles")[x] || x : "");
  const fmtDay = (iso) => new Date(iso).toLocaleDateString(lang === "ru" ? "ru-RU" : "en-GB", { day: "numeric", month: "short" });
  const bar = (part, whole, cls = "") => {
    const fill = h("div", { class: "bar-fill" });
    fill.style.setProperty("--w", `${Math.max(0, Math.min(100, whole ? (part / whole) * 100 : 0)).toFixed(1)}%`);
    return h("div", { class: `bar-track ${cls}` }, fill);
  };
  const face = (avatar, frame, size = "") => h("span", { class: `pf-av ${frame ? `fr-${frame}` : ""} ${size}`, "aria-hidden": "true" }, avatar || "🦍");
  const pct = (bp) => `${nf.format(bp / 100)} %`;

  // Text is set at once (the element is usually not on the page yet); it keeps ticking while it
  // is shown and stops when its screen is gone.
  function countdown(iso, el, done) {
    const end = Date.parse(iso);
    let shown = false, waits = 0;
    const tick = () => {
      if (el.isConnected) shown = true;
      else if (shown || ++waits > 20) return;
      const s = Math.max(0, Math.floor((end - Date.now()) / 1000));
      const dd = Math.floor(s / 86400), hh = Math.floor((s % 86400) / 3600), mm = Math.floor((s % 3600) / 60);
      el.textContent = s <= 0 ? t("pEnded") : dd ? t("pLeftD", { d: dd, h: hh }) : t("pLeftH", { h: hh, m: mm });
      if (s <= 0) { if (shown) setTimeout(() => done?.(), 5000); return; }
      setTimeout(tick, shown ? 30_000 : 300);
    };
    tick();
    return el;
  }

  // ------------------------------------------------------------------ hub card
  function hubCard(p) {
    if (!p) return null;
    return h("section", { class: "card pf-card", role: "button", tabindex: 0, onclick: profileScreen, onkeydown: (e) => { if (e.key === "Enter") profileScreen(); } },
      h("div", { class: "pf-row" },
        face(p.avatar, p.frame),
        h("div", { class: "pf-main" },
          h("div", { class: "pf-name" }, h("strong", {}, p.nickname), p.day_streak ? h("span", { class: "pill" }, `🔥 ${p.day_streak}`) : null),
          h("div", { class: "small muted" }, `${t("pLevel", { n: p.level })} · ${titleName(p.title)}`)),
        h("span", { class: "pf-lv" }, String(p.level))),
      bar(p.xp - p.level_xp, p.next_level_xp - p.level_xp, "xp"),
      h("div", { class: "small muted pf-xp" }, t("pXpTo", { xp: nf.format(p.xp - p.level_xp), need: nf.format(p.next_level_xp - p.level_xp), n: p.level + 1 })));
  }

  function hubButtons() {
    return h("div", { class: "pf-grid" },
      h("button", { class: "secondary", onclick: () => boardsScreen() }, `🏆 ${t("pBoards")}`),
      h("button", { class: "secondary", onclick: challengesScreen }, `📅 ${t("pChallenges")}`),
      h("button", { class: "secondary", onclick: achievementsScreen }, `🎖️ ${t("pAchievements")}`),
      h("button", { class: "secondary", onclick: seasonsScreen }, `🗓️ ${t("pSeasons")}`));
  }

  // ------------------------------------------------------------------ profile
  async function profileScreen() {
    let p;
    try { p = await api("/games/me"); } catch (e) { toast(errText(e)); return; }
    const stat = (v, label) => h("div", {}, h("div", { class: "big" }, v), h("div", { class: "lbl" }, label));
    const name = h("input", { id: "pf-name", value: p.nickname, maxlength: 24, "aria-label": t("pNickname") });
    const save = async (body) => {
      try { await api("/games/profile", { method: "PUT", body }); toast(t("pSaved")); profileScreen(); } catch (e) { toast(errText(e)); }
    };
    sub(t("pProfile"), back,
      h("section", { class: "card glow pf-hero" },
        h("button", { class: "ghost pf-av-btn", "aria-label": t("pAvatar"), onclick: () => sheet(t("pAvatar"),
          h("div", { class: "pf-avatars" }, ...p.avatars.map((a) => h("button", { class: `pf-av big ${a === p.avatar ? "on" : ""}`, onclick: (e) => { e.target.closest(".sheet-wrap")?.remove(); save({ avatar: a }); } }, a)))) },
          face(p.avatar, p.frame, "huge")),
        h("div", { class: "pf-hero-main" },
          h("div", { class: "row" }, name, h("button", { class: "secondary", onclick: () => save({ nickname: name.value.trim() }) }, t("pSave"))),
          h("button", { class: "ghost pf-title", onclick: () => sheet(t("pTitle"),
            h("p", { class: "small muted" }, t("pTitleText")),
            h("ul", { class: "list" }, ...p.titles.map((x) => h("li", {}, h("button", { class: `ghost wide ${x === p.title ? "on" : ""}`, onclick: (e) => { e.target.closest(".sheet-wrap")?.remove(); save({ title: x === p.level_title ? "" : x }); } }, `${x === p.title ? "✓ " : ""}${titleName(x)}`))))) },
            `👑 ${titleName(p.title)} ›`),
          h("div", { class: "pf-lvline" }, h("strong", {}, t("pLevel", { n: p.level })), h("span", { class: "small muted" }, `${nf.format(p.xp)} XP`)),
          bar(p.xp - p.level_xp, p.next_level_xp - p.level_xp, "xp"),
          h("div", { class: "small muted" }, t("pXpTo", { xp: nf.format(p.xp - p.level_xp), need: nf.format(p.next_level_xp - p.level_xp), n: p.level + 1 })))),
      h("section", { class: "card stats4g pf-stats" },
        stat(p.rounds, t("gRounds")), stat(p.wins, t("gWins")), stat(p.losses, t("pLosses")), stat(p.pushes, t("pPushes")),
        stat(p.blackjacks, t("gBlackjacks")), stat(p.win_rate === null ? "—" : `${nf.format(p.win_rate)}%`, t("pWinRate")),
        stat(p.best_win_streak, t("gStreak")), stat(`🔥 ${p.day_streak}`, t("pDayStreak"))),
      h("section", { class: "card" },
        h("div", { class: "card-title" }, t("pRanks")),
        h("p", {}, t("pRankLine", { xp: p.ranks.xp ? `#${p.ranks.xp}` : "—", wins: p.ranks.wins ? `#${p.ranks.wins}` : "—" })),
        h("button", { class: "secondary wide", onclick: () => boardsScreen() }, t("pBoards"))),
      h("section", { class: "card" },
        h("div", { class: "card-title" }, t("pAchievements"), h("span", { class: "pill" }, `${p.achievements.unlocked} / ${p.achievements.total}`)),
        p.achievements.latest.length
          ? h("div", { class: "ach-strip" }, ...p.achievements.latest.map((a) => h("span", { class: "ach-mini", title: L(a.names) }, a.icon)))
          : h("p", { class: "small muted" }, t("pNoAch")),
        h("button", { class: "secondary wide", onclick: achievementsScreen }, t("pAllAch"))),
      h("section", { class: "card" },
        h("div", { class: "card-title" }, t("pRecent")),
        p.recent.length ? h("ul", { class: "list" }, ...p.recent.map((x) => h("li", { class: "device" },
          h("span", { class: `tag tag-${x.result}` }, t("gResult")[x.blackjack && x.result === "win" ? "blackjack" : x.result]),
          h("div", { class: "dev-main small muted" }, new Date(x.finished_at).toLocaleString(lang === "ru" ? "ru-RU" : "en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })))))
          : h("p", { class: "small muted" }, t("gHistoryEmpty")),
        h("button", { class: "ghost wide", onclick: xpScreen }, t("pXpHistory"))));
  }

  async function xpScreen() {
    let xs, rs;
    try { [xs, rs] = await Promise.all([api("/games/xp?limit=50"), api("/games/rewards?limit=30")]); } catch (e) { toast(errText(e)); return; }
    sub(t("pXpHistory"), profileScreen,
      rs.length ? h("section", { class: "card" }, h("div", { class: "card-title" }, t("pRewards")),
        h("ul", { class: "list" }, ...rs.map((r) => h("li", { class: "device" },
          h("div", { class: "dev-main" }, h("strong", {}, r.source === "streak" ? `🔥 ${t("pStreak")}: ${t("pDays", { n: parseInt(r.ref, 10) || "" })}` : `🏆 ${r.ref}`), h("div", { class: "small muted" }, [r.title ? `👑 ${titleName(r.title)}` : null, r.frame ? t("pFrames")[r.frame] : null,
            r.bonus_days ? (r.bonus_paid ? t("pBonusPaid", { n: r.bonus_days }) : t("pBonusOff")) : null].filter(Boolean).join(" · "))),
          h("strong", { class: "ok" }, `+${nf.format(r.xp)} XP`))))) : null,
      h("section", { class: "card" },
        xs.length ? h("ul", { class: "list" }, ...xs.map((x) => h("li", { class: "device" },
          h("div", { class: "dev-main" }, h("strong", {}, t("pXpKinds")[x.kind] || x.kind),
            h("div", { class: "small muted" }, new Date(x.at).toLocaleString(lang === "ru" ? "ru-RU" : "en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }))),
          h("strong", { class: "ok" }, `+${nf.format(x.amount)}`))))
          : h("p", { class: "small muted" }, t("pXpEmpty"))));
  }

  // ------------------------------------------------------------------ leaderboards
  const BOARDS = ["xp", "wins", "winrate", "jackpot"];
  async function boardsScreen(state = { board: store.get("vpnhub.board") || "xp", period: "weekly", q: "" }) {
    const box = h("div", {});
    const seg = (items, cur, pick) => h("div", { class: "seg wide-seg", role: "tablist" },
      ...items.map(([k, label]) => h("button", { class: k === cur ? "on" : "", role: "tab", "aria-selected": String(k === cur), onclick: () => pick(k) }, label)));
    const draw = () => {
      try { store.set("vpnhub.board", state.board); } catch { /* fine */ }
      sub(t("pBoards"), back,
        seg(BOARDS.map((k) => [k, t("pBoardNames")[k]]), state.board, (k) => { state.board = k; draw(); }),
        state.board === "jackpot" ? null : seg([["weekly", t("pWeek")], ["monthly", t("pMonth")], ["all", t("pAllTime")]], state.period, (k) => { state.period = k; draw(); }),
        box);
      load(0, []);
    };
    const search = h("input", { id: "lb-q", type: "search", placeholder: t("pSearch"), value: state.q, maxlength: 24 });
    search.addEventListener("change", () => { state.q = search.value.trim(); load(0, []); });
    async function load(offset, acc) {
      if (state.board === "jackpot") return jackpot();
      let b;
      try {
        b = await api(`/games/boards?board=${state.board}&period=${state.period}&offset=${offset}&limit=20${state.q ? `&q=${encodeURIComponent(state.q)}` : ""}`);
      } catch (e) { box.replaceChildren(h("p", { class: "card warn" }, errText(e))); return; }
      const rows = acc.concat(b.rows);
      const value = (x) => (state.board === "winrate" ? pct(x.value) : state.board === "xp" ? `${nf.format(x.value)} XP` : nf.format(x.value));
      const row = (x) => h("div", { class: `lb-row lb-p ${x.me ? "me-row" : ""} ${x.rank <= 3 ? `top${x.rank}` : ""}` },
        h("span", { class: "rank-no" }, x.rank <= 3 ? MEDAL[x.rank - 1] : String(x.rank)),
        h("span", { class: "lb-name" }, face(x.avatar, x.frame, "sm"),
          h("span", {}, h("strong", {}, x.me ? `${x.nickname} (${t("gYou")})` : x.nickname),
            h("small", { class: "muted" }, `${t("pLv", { n: x.level })} · ${titleName(x.title)}`))),
        h("strong", { class: "right lb-win" }, value(x)));
      const head = h("section", { class: "card glow lb-head" },
        b.season ? h("div", { class: "lbl" }, `${t("pSeasonOf")[b.season.kind] || b.season.name} · `, countdown(b.season.ends_at, h("span", {}), () => draw())) : h("div", { class: "lbl" }, t("pAllTime")),
        h("p", { class: "small muted" }, t("pBoardHint")[state.board], state.board === "winrate" ? ` ${t("pMinRounds", { n: b.min_rounds })}` : ""),
        h("p", { class: "small" }, t("pParticipants", { n: nf.format(b.total) })),
        h("div", { class: "row" }, search, h("button", { class: "secondary", "aria-label": t("pRefresh"), onclick: () => load(0, []) }, "↻")));
      const mine = b.me && !rows.some((x) => x.me) ? h("section", { class: "card lb me-pinned" }, h("div", { class: "lbl" }, t("pYourPlace")), row(b.me)) : null;
      box.replaceChildren(...[head,
        rows.length ? h("section", { class: "card lb" }, ...rows.map(row),
          rows.length < b.total && !state.q && b.rows.length === 20 ? h("button", { class: "ghost wide", onclick: () => load(offset + 20, rows) }, t("pMore")) : null)
          : h("p", { class: "card muted" }, state.q ? t("pNobodyFound") : t("pBoardEmpty")),
        mine].filter(Boolean)); // a bare null would be printed as text
    }
    async function jackpot() {
      let b;
      try { b = await api("/games/leaderboard"); } catch (e) { box.replaceChildren(h("p", { class: "card warn" }, errText(e))); return; }
      box.replaceChildren(
        h("section", { class: "card glow lb-head" }, h("div", { class: "lbl" }, t("gLbKicker")), h("p", { class: "small muted" }, t("gLbText")),
          b.my_rank ? h("p", { class: "small" }, t("gMyRank", { n: b.my_rank })) : null),
        b.top.length ? h("section", { class: "card lb" },
          ...b.top.map((x) => h("div", { class: `lb-row lb-p ${x.me ? "me-row" : ""} ${x.rank <= 3 ? `top${x.rank}` : ""}` },
            h("span", { class: "rank-no" }, x.rank <= 3 ? MEDAL[x.rank - 1] : String(x.rank)),
            h("span", { class: "lb-name" }, h("strong", {}, x.me ? `${x.nickname} (${t("gYou")})` : x.nickname), h("small", { class: "muted" }, `${t("gLbStake")}: ${nf.format(x.stake)}`)),
            h("strong", { class: "right lb-win" }, `+${nf.format(x.best_win)} 🪙`))))
          : h("p", { class: "card muted" }, t("gLeadersEmpty")));
    }
    draw();
  }

  // ------------------------------------------------------------------ achievements
  async function achievementsScreen() {
    let list;
    try { list = await api("/games/achievements"); } catch (e) { toast(errText(e)); return; }
    const cats = ["game", "activity", "progress", "season"];
    const done = list.filter((a) => a.unlocked_at).length;
    sub(t("pAchievements"), back,
      h("section", { class: "card glow" }, h("div", { class: "lbl" }, t("pAchievements")),
        h("div", { class: "promo-num" }, `${done} / ${list.length}`), bar(done, list.length)),
      ...cats.map((c) => {
        const items = list.filter((a) => a.category === c);
        if (!items.length) return null;
        return h("section", { class: "card" }, h("div", { class: "card-title" }, t("pAchCats")[c]),
          h("div", { class: "ach-grid" }, ...items.map((a) => h("div", { class: `ach ${a.unlocked_at ? "got" : ""}` },
            h("span", { class: "ach-ic", "aria-hidden": "true" }, a.icon),
            h("div", { class: "ach-body" },
              h("strong", {}, L(a.names)),
              h("div", { class: "small muted" }, L(a.descriptions)),
              a.unlocked_at ? h("div", { class: "small ok" }, `✓ ${fmtDay(a.unlocked_at)} · +${a.xp} XP${a.title ? ` · 👑 ${titleName(a.title)}` : ""}`)
                : [a.target > 1 ? bar(a.progress, a.target) : null,
                  h("div", { class: "small muted" }, `${a.target > 1 ? `${nf.format(a.progress)} / ${nf.format(a.target)} · ` : ""}+${a.xp} XP`)])))));
      }));
  }

  // ------------------------------------------------------------------ challenges + streak
  async function challengesScreen() {
    let c;
    try { c = await api("/games/challenges"); } catch (e) { toast(errText(e)); return; }
    const played = new Set(c.calendar.map((x) => x.day));
    const today = new Date(`${c.day}T12:00:00Z`);
    const cells = [];
    for (let i = 34; i >= 0; i--) {
      const dd = new Date(today.getTime() - i * 864e5).toISOString().slice(0, 10);
      cells.push(h("span", { class: `cal ${played.has(dd) ? "on" : "off"} ${i === 0 ? "today" : ""}`, title: dd }));
    }
    const s = c.streak;
    const reward = (r) => [`+${r.xp || 0} XP`, r.title ? `👑 ${titleName(r.title)}` : null, r.bonus_days && s.bonus_days_enabled ? t("pBonusDays", { n: r.bonus_days }) : null].filter(Boolean).join(" · ");
    sub(t("pChallenges"), back,
      h("section", { class: "card glow" },
        h("div", { class: "card-title" }, t("pToday"), h("span", { class: "pill" }, countdown(c.resets_at, h("span", {}), () => challengesScreen()))),
        !c.enabled ? h("p", { class: "small muted" }, t("pChOff")) : c.today.length ? h("ul", { class: "list" }, ...c.today.map((x) => h("li", { class: `ch ${x.completed_at ? "done" : ""}` },
          h("span", { class: "ch-ic" }, x.completed_at ? "✅" : DIFF[x.difficulty]),
          h("div", { class: "dev-main" },
            h("strong", {}, L(x.names)),
            bar(x.progress, x.target),
            h("div", { class: "small muted" }, `${t("pDiff")[x.difficulty]} · ${x.progress} / ${x.target} · +${x.xp} XP`)))))
          : h("p", { class: "small muted" }, t("pChNone")),
        h("p", { class: "small muted" }, t("pChHint"))),
      h("section", { class: "card" },
        h("div", { class: "card-title" }, t("pStreak"), h("span", { class: "pill solid" }, `🔥 ${s.current}`)),
        h("p", { class: "small" }, t("pStreakLine", { best: s.best }), s.played_today ? ` ${t("pPlayedToday")}` : ` ${t("pPlayToKeep")}`),
        s.next_reward ? h("p", { class: "small" }, t("pNextReward", { n: s.next_reward.days, r: reward(s.next_reward) })) : null,
        h("div", { class: "cal-grid", role: "img", "aria-label": t("pCalendar") }, ...cells),
        h("div", { class: "small muted cal-legend" }, h("span", { class: "cal on" }), t("pPlayedDay"), h("span", { class: "cal off" }), t("pMissedDay")),
        h("ul", { class: "steps small" }, ...s.rewards.map((r) => h("li", {}, `${t("pDays", { n: r.days })}: ${reward(r)}`)))),
      c.history.length ? h("section", { class: "card" }, h("div", { class: "card-title" }, t("pChDone")),
        h("ul", { class: "list" }, ...c.history.map((x) => h("li", { class: "device" }, h("div", { class: "dev-main" }, h("strong", {}, L(x.names)), h("div", { class: "small muted" }, fmtDay(x.day))), h("strong", { class: "ok" }, `+${x.xp}`))))) : null);
  }

  // ------------------------------------------------------------------ seasons
  async function seasonsScreen() {
    let s;
    try { s = await api("/games/seasons"); } catch (e) { toast(errText(e)); return; }
    const prize = (r) => [r.title ? `👑 ${titleName(r.title)}` : null, r.frame ? t("pFrames")[r.frame] : null, `+${nf.format(r.xp || 0)} XP`, r.bonus_days && s.bonus_days_enabled ? t("pBonusDays", { n: r.bonus_days }) : null].filter(Boolean).join(" · ");
    const places = (r) => (r.places[0] === r.places[1] ? (MEDAL[r.places[0] - 1] || `#${r.places[0]}`) : `${r.places[0]}–${r.places[1]}`);
    // seasons run midnight to midnight in the game's time zone: take the middle of the first
    // and last day so the dates read right in any time zone within ±12 h
    const range = (x) => `${fmtDay(new Date(Date.parse(x.starts_at) + 432e5).toISOString())} – ${fmtDay(new Date(Date.parse(x.ends_at) - 432e5).toISOString())}`;
    sub(t("pSeasons"), back,
      ...s.current.map((x) => h("section", { class: "card glow season" },
        h("div", { class: "card-title" }, t("pSeasonOf")[x.kind], h("span", { class: "pill" }, countdown(x.ends_at, h("span", {}), () => seasonsScreen()))),
        h("p", { class: "small muted" }, `${range(x)} · ${t("pBoardBy")[x.board]} · ${t("pParticipants", { n: nf.format(x.participants) })}`),
        x.me ? h("p", {}, t("pYouAre", { n: x.me.rank })) : h("p", { class: "small" }, t("pNotYet")),
        x.my_rounds < x.min_rounds ? h("p", { class: "small muted" }, t("pMinForPrize", { n: x.min_rounds, have: x.my_rounds })) : null,
        x.top.length ? h("div", { class: "lb" }, ...x.top.map((r) => h("div", { class: `lb-row lb-p ${r.me ? "me-row" : ""} top${r.rank}` },
          h("span", { class: "rank-no" }, MEDAL[r.rank - 1]), h("span", { class: "lb-name" }, face(r.avatar, r.frame, "sm"), h("strong", {}, r.nickname)),
          h("strong", { class: "right lb-win" }, x.board === "xp" ? `${nf.format(r.value)} XP` : nf.format(r.value))))) : null,
        h("details", {}, h("summary", { class: "small" }, t("pPrizes")),
          h("ul", { class: "list small" }, ...x.rewards.map((r) => h("li", { class: "device" }, h("strong", {}, places(r)), h("span", { class: "dev-main" }, prize(r)))))),
        h("button", { class: "secondary wide", onclick: () => boardsScreen({ board: x.board, period: x.kind, q: "" }) }, t("pOpenBoard")))),
      ...s.events.map((x) => h("section", { class: "card season" }, h("div", { class: "card-title" }, `🎪 ${x.name}`, h("span", { class: "pill" }, countdown(x.ends_at, h("span", {})))),
        h("p", { class: "small muted" }, range(x)))),
      !s.bonus_days_enabled ? h("p", { class: "small muted pad-x" }, t("pBonusOffNote")) : null,
      h("section", { class: "card" }, h("div", { class: "card-title" }, t("pArchive")),
        s.archive.length ? h("ul", { class: "list" }, ...s.archive.map((x) => h("li", { class: "device", role: "button", tabindex: 0, onclick: () => resultsSheet(x) },
          h("div", { class: "dev-main" }, h("strong", {}, `${t("pSeasonOf")[x.kind] || "🎪"} ${range(x)}`),
            h("div", { class: "small muted" }, x.winners.map((w) => `${MEDAL[w.rank - 1]} ${w.nickname}`).join("  ") || t("pNoWinners"))), h("span", {}, "›"))))
          : h("p", { class: "small muted" }, t("pArchiveEmpty"))));
  }

  async function resultsSheet(season) {
    let r;
    try { r = await api(`/games/seasons/${season.id}/results?board=${season.board}`); } catch (e) { toast(errText(e)); return; }
    sheet(`${t("pSeasonOf")[season.kind] || season.name} · ${t("pFinal")}`,
      r.rows.length ? h("div", { class: "lb" }, ...r.rows.slice(0, 20).map((x) => h("div", { class: `lb-row lb-p ${x.me ? "me-row" : ""} ${x.rank <= 3 ? `top${x.rank}` : ""}` },
        h("span", { class: "rank-no" }, x.rank <= 3 ? MEDAL[x.rank - 1] : String(x.rank)),
        h("span", { class: "lb-name" }, face(x.avatar, x.frame, "sm"), h("strong", {}, x.nickname)),
        h("strong", { class: "right lb-win" }, season.board === "xp" ? `${nf.format(x.value)} XP` : nf.format(x.value)))))
        : h("p", { class: "small muted" }, t("pNoWinners")));
  }

  // ------------------------------------------------------------------ after a round
  function toastCard(icon, title, text) {
    const el = h("div", { class: "ach-toast", role: "status" }, h("span", { class: "ach-ic" }, icon), h("div", {}, h("strong", {}, title), h("div", { class: "small" }, text)));
    document.body.append(el);
    setTimeout(() => el.classList.add("out"), 2800);
    setTimeout(() => el.remove(), 3400);
  }

  function levelUp(level, title) {
    const close = () => overlay.remove();
    const bits = Array.from({ length: 40 }, (_, i) => {
      const b = h("span", { class: "bit" });
      b.style.setProperty("--x", `${(i * 37) % 100}%`);
      b.style.setProperty("--col", ["var(--r0)", "var(--r2)", "var(--r4)", "#ffffff"][i % 4]);
      b.style.setProperty("--rot", `${(i * 47) % 360}deg`);
      b.style.setProperty("--dur", `${2.4 + (i % 5) * 0.3}s`);
      b.style.setProperty("--delay", `${(i % 8) * 0.08}s`);
      return b;
    });
    const overlay = h("div", { class: "party", role: "dialog", "aria-label": t("pLevelUp") }, ...bits,
      h("section", { class: "card glow lvup" },
        h("img", { src: "assets/dealer-happy.webp", alt: "", class: "lvup-img" }),
        h("div", { class: "lbl" }, t("pLevelUp")),
        h("div", { class: "lvup-n" }, String(level)),
        title ? h("p", {}, `👑 ${titleName(title)}`) : null,
        h("button", { class: "primary wide", onclick: close }, t("cool"))));
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    document.body.append(overlay);
  }

  // Show what a round gave: XP, then achievements / challenges / rewards one by one, a level-up
  // last (it is the big one). Calm: at most a few cards, no sound spam.
  function celebrate(events, xpEl) {
    if (!events || !events.length) return;
    const xp = events.filter((e) => e.type === "xp").reduce((s, e) => s + e.amount, 0);
    if (xp && xpEl) {
      xpEl.textContent = `+${xp} XP`;
      xpEl.className = "xp-float show";
      setTimeout(() => { xpEl.className = "xp-float"; }, 2200);
    }
    const cards = [];
    for (const e of events) {
      if (e.type === "achievement") cards.push([e.icon, t("pAchGot"), `${L(e.names)} · +${e.xp} XP`]);
      else if (e.type === "challenge") cards.push(["✅", t("pChGot"), `${L(e.names)} · +${e.xp} XP`]);
      else if (e.type === "reward") cards.push(["🎁", t("pRewardGot"), [e.xp ? `+${e.xp} XP` : null, e.title ? `👑 ${titleName(e.title)}` : null, e.bonus_days ? t("pBonusDays", { n: e.bonus_days }) : null].filter(Boolean).join(" · ")]);
      else if (e.type === "xp_cap") cards.push(["⏸️", t("pCapTitle"), t("pCapText")]);
    }
    cards.slice(0, 4).forEach((c, i) => setTimeout(() => toastCard(...c), 600 + i * 1500));
    const lv = events.filter((e) => e.type === "level").pop();
    if (lv) setTimeout(() => levelUp(lv.level, lv.title), 600 + Math.min(cards.length, 4) * 1500);
  }

  return { hubCard, hubButtons, profileScreen, boardsScreen, achievementsScreen, challengesScreen, seasonsScreen, celebrate };
}
