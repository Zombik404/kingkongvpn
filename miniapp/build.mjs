// Bundles src/ into dist/ (committed, so servers don't need Node). Run: npm ci && npm run build
import { build } from "esbuild";
import { copyFileSync, mkdirSync, rmSync } from "node:fs";

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist");
await build({
  entryPoints: ["src/app.js", "src/conf.js"],
  bundle: true,
  minify: true,
  format: "esm",
  target: ["es2020", "safari15", "chrome90"],
  outdir: "dist",
  legalComments: "eof",
  sourcemap: false,
});
for (const f of ["index.html", "conf.html", "style.css"]) copyFileSync(`src/${f}`, `dist/${f}`);
mkdirSync("dist/assets");
for (const f of ["logo.png", "jungle.jpg", "vine.png", "wreath.png", "gorilla.png", "og-corner-top.png", "og-corner-bottom.png", "og-edge.png", "og-leaf.png",
  ...["idle", "blink", "eat1", "eat2", "happy", "sad"].map((f) => `dealer-${f}.webp`)]) copyFileSync(`src/assets/${f}`, `dist/assets/${f}`);
console.log("built dist/");
