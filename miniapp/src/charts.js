// Small SVG chart helpers (no dependencies). Pure geometry is exported for tests.
const NS = "http://www.w3.org/2000/svg";

export function formatBytes(n, lang = "en") {
  const units = lang === "ru" ? ["Б", "КБ", "МБ", "ГБ", "ТБ"] : ["B", "KB", "MB", "GB", "TB"];
  let v = Math.max(0, Number(n) || 0);
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  const digits = i === 0 || v >= 100 ? 0 : v >= 10 ? 1 : 2;
  const num = v.toLocaleString(lang === "ru" ? "ru-RU" : "en-US", { maximumFractionDigits: digits });
  return `${num} ${units[i]}`;
}

/** Monotone cubic (Fritsch–Carlson) path through points — smooth, never overshoots below 0. */
export function smoothPath(pts) {
  if (!pts.length) return "";
  if (pts.length === 1) return `M${pts[0][0]},${pts[0][1]}`;
  const n = pts.length;
  const dx = [], dy = [], m = [];
  for (let i = 0; i < n - 1; i++) {
    dx.push(pts[i + 1][0] - pts[i][0]);
    dy.push(pts[i + 1][1] - pts[i][1]);
    m.push(dy[i] / dx[i]);
  }
  const t = [m[0]];
  for (let i = 1; i < n - 1; i++) t.push(m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2);
  t.push(m[n - 2]);
  for (let i = 0; i < n - 1; i++) {
    if (m[i] === 0) {
      t[i] = 0;
      t[i + 1] = 0;
      continue;
    }
    const a = t[i] / m[i], b = t[i + 1] / m[i], s = a * a + b * b;
    if (s > 9) {
      const k = 3 / Math.sqrt(s);
      t[i] = k * a * m[i];
      t[i + 1] = k * b * m[i];
    }
  }
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    d += ` C${(pts[i][0] + h).toFixed(1)},${(pts[i][1] + t[i] * h).toFixed(1)} ${(pts[i + 1][0] - h).toFixed(1)},${(pts[i + 1][1] - t[i + 1] * h).toFixed(1)} ${pts[i + 1][0].toFixed(1)},${pts[i + 1][1].toFixed(1)}`;
  }
  return d;
}

/** Map values to chart coordinates. Returns [[x,y],...] in a w×h box with padding. */
export function scalePoints(values, w, h, pad = { l: 6, r: 6, t: 10, b: 4 }, max = null) {
  const top = max ?? Math.max(1, ...values);
  const span = Math.max(1, values.length - 1);
  return values.map((v, i) => [
    pad.l + (i * (w - pad.l - pad.r)) / span,
    pad.t + (1 - v / top) * (h - pad.t - pad.b),
  ]);
}

/** Arc path for a ring segment starting at 12 o'clock, clockwise, `fraction` in [0,1]. */
export function arcPath(cx, cy, r, fraction) {
  const f = Math.min(Math.max(fraction, 0), 0.9999);
  const a = f * 2 * Math.PI - Math.PI / 2;
  const x = cx + r * Math.cos(a), y = cy + r * Math.sin(a);
  return `M${cx},${cy - r} A${r},${r} 0 ${f > 0.5 ? 1 : 0} 1 ${x.toFixed(2)},${y.toFixed(2)}`;
}

function el(tag, attrs = {}, ...kids) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  for (const k of kids) e.append(k);
  return e;
}

function gradient(id, stops, vertical = true) {
  const g = el("linearGradient", { id, x1: 0, y1: 0, x2: vertical ? 0 : 1, y2: vertical ? 1 : 0 });
  for (const [offset, color, opacity = 1] of stops) g.append(el("stop", { offset, "stop-color": color, "stop-opacity": opacity }));
  return g;
}

/** Area chart with two series (download behind, upload in front) and date labels. */
export function areaChart(series, { width = 340, height = 170, labels = [] } = {}) {
  const chartH = height - 22;
  const down = series.map((p) => p.download), up = series.map((p) => p.upload);
  const max = Math.max(1, ...down, ...up);
  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, class: "area", role: "img" });
  svg.append(el("defs", {},
    gradient("gDown", [[0, "#ff7a00", 0.85], [1, "#ff3d00", 0.02]]),
    gradient("gUp", [[0, "#ffc46b", 0.75], [1, "#ffb347", 0.02]]),
    gradient("gLine", [[0, "#ffb347"], [1, "#ff3d00"]], false)));
  for (let i = 1; i <= 3; i++) {
    const y = 10 + (i * (chartH - 14)) / 3;
    svg.append(el("line", { x1: 0, x2: width, y1: y, y2: y, class: "grid" }));
  }
  const draw = (values, fill, stroke) => {
    const pts = scalePoints(values, width, chartH, undefined, max);
    const line = smoothPath(pts);
    const area = `${line} L${pts[pts.length - 1][0]},${chartH} L${pts[0][0]},${chartH} Z`;
    svg.append(el("path", { d: area, fill: `url(#${fill})` }));
    svg.append(el("path", { d: line, fill: "none", stroke, "stroke-width": 2.2, "stroke-linecap": "round" }));
  };
  draw(down, "gDown", "url(#gLine)");
  draw(up, "gUp", "#ffc46b");
  const step = Math.max(1, Math.ceil(labels.length / 7));
  labels.forEach((text, i) => {
    if (i % step && i !== labels.length - 1) return;
    const x = scalePoints(down, width, chartH)[i][0];
    const t = el("text", { x, y: height - 4, "text-anchor": i === 0 ? "start" : i === labels.length - 1 ? "end" : "middle", class: "axis" });
    t.textContent = text;
    svg.append(t);
  });
  return svg;
}

export const RING_COLORS = ["#ff5a00", "#ff8a1f", "#ffab40", "#ffc977", "#ffe2b0"];

/** Concentric rings: one per item, length = share of the total. */
export function ringsChart(items, size = 200) {
  const svg = el("svg", { viewBox: `0 0 ${size} ${size}`, class: "rings", role: "img" });
  const total = items.reduce((s, x) => s + x.value, 0) || 1;
  const c = size / 2, stroke = 11, gap = 5;
  items.forEach((item, i) => {
    const r = c - stroke / 2 - 2 - i * (stroke + gap);
    if (r < 12) return;
    svg.append(el("circle", { cx: c, cy: c, r, fill: "none", stroke: "rgba(255,255,255,.06)", "stroke-width": stroke }));
    const frac = Math.max(0.02, item.value / total);
    svg.append(el("path", { d: arcPath(c, c, r, frac), fill: "none", stroke: RING_COLORS[i % RING_COLORS.length], "stroke-width": stroke, "stroke-linecap": "round" }));
  });
  return svg;
}

/** Thick progress ring for the home screen (time left in the paid period). */
export function progressRing(fraction, size = 188) {
  const c = size / 2, r = c - 10;
  const svg = el("svg", { viewBox: `0 0 ${size} ${size}`, class: "progress" });
  svg.append(el("defs", {}, gradient("gRing", [[0, "#ffb347"], [1, "#ff3d00"]], false)));
  svg.append(el("circle", { cx: c, cy: c, r, fill: "none", stroke: "rgba(255,255,255,.07)", "stroke-width": 9 }));
  if (fraction > 0) svg.append(el("path", { d: arcPath(c, c, r, fraction), fill: "none", stroke: "url(#gRing)", "stroke-width": 9, "stroke-linecap": "round" }));
  return svg;
}
