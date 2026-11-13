// Standalone page opened in the phone's browser: shows/downloads a config passed in the URL
// fragment. The fragment is never sent to any server; we also wipe it from history at once.
import qrcode from "qrcode-generator";
import { fromFragment } from "./wg.js";

const params = new URLSearchParams(location.hash.slice(1));
history.replaceState(null, "", location.pathname);
const root = document.getElementById("app");
const ru = /^(ru|uk|be)/i.test(navigator.language || "");
const T = ru
  ? { title: "Конфигурация WireGuard", dl: "Скачать файл", copy: "Скопировать", hint: "Скачайте файл и откройте его в приложении WireGuard (или импортируйте из файла). Затем закройте эту вкладку.", none: "Нет данных. Создайте подключение заново в Telegram." }
  : { title: "WireGuard configuration", dl: "Download file", copy: "Copy", hint: "Download the file and open it with the WireGuard app (or import from file). Then close this tab.", none: "Nothing to show. Create the connection again in Telegram." };

function el(tag, text, attrs = {}) {
  const e = document.createElement(tag);
  if (text) e.textContent = text;
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

let config = "";
try {
  config = fromFragment(params.get("c") || "");
} catch {
  config = "";
}
const name = (params.get("n") || "vpn").replace(/[^A-Za-z0-9_=+.-]/g, "").slice(0, 15) || "vpn";

if (!config.startsWith("[Interface]")) {
  root.append(el("p", T.none));
} else {
  root.append(el("h2", T.title), el("p", T.hint, { class: "muted" }));
  const dl = el("button", T.dl, { class: "wide" });
  dl.onclick = () => {
    const url = URL.createObjectURL(new Blob([config], { type: "application/octet-stream" }));
    const a = el("a", "", { href: url, download: `${name}.conf` });
    document.body.append(a);
    a.click();
    a.remove();
  };
  const cp = el("button", T.copy, { class: "secondary wide" });
  cp.onclick = () => navigator.clipboard.writeText(config).then(() => (cp.textContent = "✓"));
  const qr = qrcode(0, "M");
  qr.addData(config);
  qr.make();
  const box = el("div", "", { class: "qr" });
  box.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 4, scalable: true });
  root.append(dl, cp, box);
}
