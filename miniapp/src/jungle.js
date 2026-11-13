// Jungle dressing for the Mini App: swaying vines, fireflies, a leaf wreath, and the monkey that
// swings across the screen on page changes. Decorative only — static markup, no user data.
const NS = "http://www.w3.org/2000/svg";
const reduced = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function svg(viewBox, cls, inner) {
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("viewBox", viewBox);
  s.setAttribute("class", cls);
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = inner; // static strings built below
  return s;
}

const leafPath = (len, w) => `M0,0 C${len * 0.25},${-w} ${len * 0.7},${-w * 0.9} ${len},0 C${len * 0.7},${w * 0.9} ${len * 0.25},${w} 0,0Z`;

/** A hanging vine (wavy stem + leaves) for the screen edges. */
function vine(height = 640, seed = 0) {
  let d = "M12,-6";
  const leaves = [];
  for (let y = 0; y <= height; y += 8) {
    const x = 12 + Math.sin((y + seed * 37) / 38) * 6;
    d += ` L${x.toFixed(1)},${y}`;
    if (y % 40 === 24) {
      const side = (y / 40 + seed) % 2 < 1 ? 1 : -1;
      leaves.push(`<path class="jv-leaf" transform="translate(${x.toFixed(1)},${y}) rotate(${side > 0 ? 28 : 152})" d="${leafPath(17, 5.5)}"/>`);
    }
  }
  return svg(`0 0 24 ${height}`, "jv", `<path class="jv-stem" d="${d}"/>${leaves.join("")}`);
}

/** Vines at both edges and a few fireflies; added once, behind the content. */
export function mountJungle() {
  if (document.querySelector(".jungle")) return;
  const box = document.createElement("div");
  box.className = "jungle";
  box.setAttribute("aria-hidden", "true");
  [["l", 0, 620], ["l2", 1, 380], ["r", 2, 560], ["r2", 3, 300]].forEach(([side, seed, len]) => {
    const v = vine(len, seed);
    v.classList.add(`jv-${side}`);
    box.append(v);
  });
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
  const parts = ['<circle class="wr-stem" cx="100" cy="100" r="80"/>'];
  const n = 36;
  for (let i = 0; i < n; i++) {
    const a = (i / n) * 2 * Math.PI;
    const x = 100 + 80 * Math.cos(a), y = 100 + 80 * Math.sin(a);
    const deg = (a * 180) / Math.PI + 90 + (i % 2 ? 38 : 142);
    parts.push(`<path class="wr-leaf${i % 3 === 0 ? " hi" : ""}" transform="translate(${x.toFixed(1)},${y.toFixed(1)}) rotate(${deg.toFixed(0)})" d="${leafPath(11, 3.6)}"/>`);
  }
  return svg("0 0 200 200", "orbit wreath", parts.join(""));
}

const MONKEY =
  // arms up to the vine, then body, head, legs and a curled tail
  '<path class="mk-fur-l" d="M33,54 Q22,30 43,9"/><path class="mk-fur-l" d="M57,54 Q68,30 47,9"/>' +
  '<path class="mk-tail" d="M48,84 C64,102 44,120 30,108 C23,101 31,93 36,100"/>' +
  '<path class="mk-fur-l" d="M39,80 Q26,86 24,100"/><path class="mk-fur-l" d="M51,80 Q64,86 68,98"/>' +
  '<ellipse class="mk-fur" cx="45" cy="64" rx="17" ry="21"/><ellipse class="mk-skin" cx="45" cy="68" rx="10" ry="13"/>' +
  '<circle class="mk-fur" cx="29.5" cy="35" r="6.5"/><circle class="mk-fur" cx="60.5" cy="35" r="6.5"/>' +
  '<circle class="mk-skin" cx="29.5" cy="35" r="3.2"/><circle class="mk-skin" cx="60.5" cy="35" r="3.2"/>' +
  '<circle class="mk-fur" cx="45" cy="37" r="14.5"/>' +
  '<path class="mk-skin" d="M35,36 C35,29 41,28 45,31 C49,28 55,29 55,36 C58,42 53,50 45,50 C37,50 32,42 35,36Z"/>' +
  '<circle class="mk-eye" cx="41" cy="36.5" r="1.9"/><circle class="mk-eye" cx="49" cy="36.5" r="1.9"/>' +
  '<path class="mk-mouth" d="M40,43 Q45,47.5 50,43"/>' +
  '<circle class="mk-fur" cx="43.5" cy="9" r="4.2"/><circle class="mk-fur" cx="46.5" cy="9" r="4.2"/>';

/**
 * The monkey swings across on a vine: "fwd" = left → right (opening a page),
 * "back" = right → left (going back). The new screen slides in the same direction.
 */
export function swing(dir, root) {
  if (reduced()) return;
  document.querySelector(".swing")?.remove();
  const layer = document.createElement("div");
  layer.className = `swing ${dir}`;
  layer.setAttribute("aria-hidden", "true");
  const arm = document.createElement("div");
  arm.className = "swing-arm";
  const rope = document.createElement("div");
  rope.className = "swing-vine";
  arm.append(rope, svg("0 0 90 122", "swing-monkey", MONKEY));
  layer.append(arm);
  document.body.append(layer);
  const done = () => layer.remove();
  arm.addEventListener("animationend", done, { once: true });
  setTimeout(done, 1900); // safety net if the event never fires
  enter(dir, root);
}

/** Slide the freshly rendered screen in from the side the monkey came from. */
export function enter(dir, root) {
  if (reduced() || !root) return;
  root.classList.remove("enter-fwd", "enter-back");
  void root.offsetWidth; // restart the animation
  root.classList.add(dir === "back" ? "enter-back" : "enter-fwd");
  root.addEventListener("animationend", () => root.classList.remove("enter-fwd", "enter-back"), { once: true });
}
