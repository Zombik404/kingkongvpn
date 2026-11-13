// Jungle dressing for the Mini App: swaying lianas, fireflies, a leaf wreath, and the crowned
// gorilla that swings across the screen on page changes. Decorative only; the artwork is rendered by
// tools/render_jungle.py and tools/render_gorilla.py (no photos, no user data).
const reduced = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function img(src, cls) {
  const i = document.createElement("img");
  i.src = src;
  i.className = cls;
  i.alt = "";
  i.decoding = "async";
  i.draggable = false;
  return i;
}

/** Vines at both edges and a few fireflies; added once, behind the content. */
export function mountJungle() {
  if (document.querySelector(".jungle")) return;
  const box = document.createElement("div");
  box.className = "jungle";
  box.setAttribute("aria-hidden", "true");
  for (const side of ["l", "l2", "r", "r2"]) box.append(img("assets/vine.png", `jv jv-${side}`));
  for (let i = 0; i < 12; i++) {
    const f = document.createElement("span");
    f.className = "firefly";
    f.style.setProperty("--fx", `${(7 + ((i * 53) % 86)).toFixed(0)}%`);
    f.style.setProperty("--fy", `${(8 + ((i * 37) % 84)).toFixed(0)}%`);
    f.style.setProperty("--fd", `${5 + (i % 5) * 1.3}s`);
    f.style.setProperty("--fdelay", `${-(i * 0.9).toFixed(1)}s`);
    box.append(f);
  }
  document.body.append(box);
}

/** A wreath of leaves on a circle (the orbit around the hub). */
export function wreath() {
  return img("assets/wreath.png", "orbit wreath");
}

/**
 "fwd" = left → right (opening a page),
 * "back" = right → left (going back). The new screen slides in the same direction.
 */
const ENTER_AT = 1050; // ms after the swing starts: the king is near the screen edge
let swingStart = 0;

const SWING_MS = 1550;
const NS = "http://www.w3.org/2000/svg";
// gorilla.png is 390×430; the hand that holds the liana sits at 46.2% / 7.2% of the image
const KING_W = 300, KING_H = (300 * 430) / 390, HAND_X = 0.462 * KING_W, HAND_Y = 0.072 * KING_H;

function el(tag, attrs) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

/**
 * The jungle king swings across on a liana like a pendulum: slow at the ends, fastest at the
 * bottom. The liana is a cubic curve whose upper points follow the swing with a delay, so it
 * bends and trails behind him; his body follows the liana's end and sways with the speed.
 * "fwd" = left → right (opening a section), "back" = right → left.
 */
export function swing(dir, root) {
  if (reduced()) return;
  swingStart = performance.now();
  document.querySelector(".swing")?.remove();
  const W = window.innerWidth, H = window.innerHeight;
  const layer = document.createElement("div");
  layer.className = `swing ${dir}`;
  layer.setAttribute("aria-hidden", "true");
  const svgEl = el("svg", { class: "swing-svg", viewBox: `0 0 ${W} ${H}`, width: W, height: H });
  const shade = el("path", { class: "lv-shade" }), body = el("path", { class: "lv-body" });
  const knots = el("path", { class: "lv-knots" }), shine = el("path", { class: "lv-shine" });
  const leaves = [0.28, 0.5, 0.72].map((_, i) => el("path", { class: "lv-leaf", d: i % 2 ? "M0,0 C6,-9 18,-9 26,0 C18,7 6,7 0,0Z" : "M0,0 C6,9 18,9 26,0 C18,-7 6,-7 0,0Z" }));
  svgEl.append(shade, body, knots, shine, ...leaves);
  const king = img("assets/gorilla.png", "swing-king");
  layer.append(svgEl, king);
  document.body.append(layer);

  const sign = dir === "back" ? -1 : 1;
  const P = { x: W / 2, y: -0.16 * H };            // pivot above the screen
  const L = Math.max(0.62 * H, 0.66 * W);            // liana length
  // swing just far enough that he starts and ends right behind the screen edges
  const AMP = Math.min(62, Math.max(32, (Math.asin(Math.min(0.95, (W / 2 + 175) / L)) * 180) / Math.PI));
  const theta = (u) => sign * AMP * Math.cos(Math.PI * Math.min(1, Math.max(0, u))); // degrees
  const at = (deg, len) => {
    const r = (deg * Math.PI) / 180;
    return { x: P.x - len * Math.sin(r), y: P.y + len * Math.cos(r) };
  };
  const bez = (a, b, c, d, t) => {
    const m = 1 - t;
    return {
      x: m * m * m * a.x + 3 * m * m * t * b.x + 3 * m * t * t * c.x + t * t * t * d.x,
      y: m * m * m * a.y + 3 * m * m * t * b.y + 3 * m * t * t * c.y + t * t * t * d.y,
    };
  };

  let raf = 0;
  const frame = (now) => {
    const u = (now - swingStart) / SWING_MS;
    if (u >= 1) { layer.remove(); return; }
    const stretch = 1 + 0.04 * Math.sin(Math.PI * u);           // the liana stretches under his weight
    const E = at(theta(u), L * stretch);
    const c1 = at(theta(u - 0.24), L * 0.36);                    // upper part lags the most
    const c2 = at(theta(u - 0.11), L * 0.72);
    const d = `M${P.x},${P.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${E.x},${E.y}`;
    for (const p of [shade, body, knots, shine]) p.setAttribute("d", d);
    [0.28, 0.5, 0.72].forEach((t, i) => {
      const q = bez(P, c1, c2, E, t), q2 = bez(P, c1, c2, E, t + 0.01);
      const a = (Math.atan2(q2.y - q.y, q2.x - q.x) * 180) / Math.PI;
      leaves[i].setAttribute("transform", `translate(${q.x.toFixed(1)},${q.y.toFixed(1)}) rotate(${(a + (i % 2 ? -50 : 50)).toFixed(1)})`);
    });
    // body hangs along the end of the liana, and swings a little behind it with the speed
    const tx = E.x - c2.x, ty = E.y - c2.y;
    const along = (Math.atan2(-tx, ty) * 180) / Math.PI;
    const speed = Math.sin(Math.PI * u);                          // 0 at the ends, 1 at the bottom
    const lag = sign * 14 * speed;
    const fade = Math.min(1, u / 0.08, (1 - u) / 0.08);
    king.style.setProperty("transform",
      `translate(${(E.x - HAND_X).toFixed(1)}px,${(E.y - HAND_Y).toFixed(1)}px) rotate(${(along + lag).toFixed(2)}deg)${dir === "back" ? " scaleX(-1)" : ""}`);
    layer.style.setProperty("--swing-fade", fade.toFixed(3));
    raf = requestAnimationFrame(frame);
  };
  raf = requestAnimationFrame(frame);
  setTimeout(() => { cancelAnimationFrame(raf); layer.remove(); }, SWING_MS + 600); // safety net
  enter(dir, root);
}

/** Slide the freshly rendered screen in from the side the monkey came from. */
export function enter(dir, root) {
  if (reduced() || !root) return;
  root.classList.remove("enter-fwd", "enter-back");
  // count the delay from the start of the swing, so slow data loading doesn't push it later
  const wait = Math.max(0, ENTER_AT - (performance.now() - swingStart));
  root.style.setProperty("--enter-delay", `${Math.round(wait)}ms`);
  void root.offsetWidth; // restart the animation
  root.classList.add(dir === "back" ? "enter-back" : "enter-fwd");
  root.addEventListener("animationend", () => root.classList.remove("enter-fwd", "enter-back"), { once: true });
}


// ---------------------------------------------------------------- "hidden in the jungle"
// While the VPN is on, leaves grow in from the screen edges and stay (gently swaying) until it
// is turned off; then they shrink back. Purely decorative: pointer-events are off, so every
// button underneath keeps working.
let og = null;
let ogOn = false;

function buildOvergrowth() {
  const box = document.createElement("div");
  box.className = "overgrowth";
  box.setAttribute("aria-hidden", "true");
  const vignette = document.createElement("div");
  vignette.className = "og-vignette";
  box.append(vignette);
  const part = (cls, src, delay) => {
    const sway = document.createElement("div");
    sway.className = `og-part ${cls}`;
    sway.style.setProperty("--d", `${delay}ms`);
    sway.append(img(src, "og-img"));
    box.append(sway);
  };
  part("og-edge og-l", "assets/og-edge.png", 0);
  part("og-edge og-r", "assets/og-edge.png", 140);
  part("og-corner og-tl", "assets/og-corner-top.png", 260);
  part("og-corner og-tr", "assets/og-corner-top.png", 380);
  part("og-corner og-bl", "assets/og-corner-bottom.png", 480);
  part("og-corner og-br", "assets/og-corner-bottom.png", 600);
  // single leaves that pop out along the edges after the big clusters
  const spots = [[2, 24], [96, 30], [1, 46], [97, 52], [3, 64], [95, 70], [2, 84], [96, 88], [30, 1], [70, 2], [50, 0], [24, 98], [76, 99]];
  spots.forEach(([x, y], i) => {
    const l = img("assets/og-leaf.png", "og-pop");
    l.style.setProperty("--x", `${x}%`);
    l.style.setProperty("--y", `${y}%`);
    l.style.setProperty("--r", `${(x < 10 ? 0 : x > 90 ? 180 : y < 10 ? 90 : -90) + ((i * 37) % 50) - 25}deg`);
    l.style.setProperty("--d", `${700 + i * 70}ms`);
    box.append(l);
  });
  const chip = document.createElement("div");
  chip.className = "og-chip";
  const title = document.createElement("strong");
  const sub = document.createElement("span");
  chip.append(title, sub);
  box.append(chip);
  document.body.append(box);
  return { box, title, sub };
}

function leafFall(n = 14) {
  if (reduced()) return;
  for (let i = 0; i < n; i++) {
    const l = img("assets/og-leaf.png", "og-fall");
    l.style.setProperty("--x", `${(i * 61) % 100}%`);
    l.style.setProperty("--drift", `${((i * 29) % 120) - 60}px`);
    l.style.setProperty("--spin", `${((i * 83) % 540) - 270}deg`);
    l.style.setProperty("--dur", `${2.4 + (i % 5) * 0.35}s`);
    l.style.setProperty("--d", `${(i % 7) * 0.12}s`);
    l.addEventListener("animationend", () => l.remove(), { once: true });
    document.body.append(l);
  }
}

/** Show or hide the overgrowth. `text` = { title, sub } for the status chip. */
export function setOvergrowth(on, text = {}) {
  if (!og) og = buildOvergrowth();
  og.title.textContent = text.title || "";
  og.sub.textContent = text.sub || "";
  if (on === ogOn) return;
  ogOn = on;
  og.box.classList.toggle("on", on);
  og.box.classList.toggle("off", !on);
  document.documentElement.classList.toggle("vpn-on", on);
  if (on) leafFall();
}
