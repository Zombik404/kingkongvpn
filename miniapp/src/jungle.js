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
 * The jungle king (a gorilla in a crown, banana in hand) swings across on a liana: "fwd" = left → right (opening a page),
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
  arm.append(rope, img("assets/gorilla.png", "swing-monkey"));
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
