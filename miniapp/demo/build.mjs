// Builds the clickable demo into demo/dist/: index.html (inline JS+CSS) + assets + the config page.
import { build } from "esbuild";
import { copyFileSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";

const out = "demo/dist";
rmSync(out, { recursive: true, force: true });
mkdirSync(`${out}/assets`, { recursive: true });
const res = await build({
  entryPoints: ["demo/entry.js"], bundle: true, minify: true, format: "iife", write: false,
  target: ["es2020", "safari15", "chrome90"], legalComments: "none",
});
const js = res.outputFiles[0].text.replace(/<\/script/gi, "<\\/script");
const css = readFileSync("dist/style.css", "utf8") + readFileSync("demo/demo.css", "utf8");
const html = `<title>KingKong VPN</title>
<style>${css}</style>
<main id="app"></main>
<script>${js}</script>
`;
writeFileSync(`${out}/index.html`, html);
for (const f of ["logo.png", "jungle.jpg", "vine.png", "wreath.png", "gorilla.png", "og-corner-top.png", "og-corner-bottom.png", "og-edge.png", "og-leaf.png",
  ...["idle", "blink", "eat1", "eat2", "happy", "sad"].map((f) => `dealer-${f}.webp`)]) copyFileSync(`src/assets/${f}`, `${out}/assets/${f}`);
for (const f of ["conf.html", "conf.js", "style.css"]) copyFileSync(`dist/${f}`, `${out}/${f}`);
console.log("built demo/dist/", Math.round(html.length / 1024), "KB");
