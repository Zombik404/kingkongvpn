// Bundles src/ into dist/ (committed, so servers don't need Node). Run: npm ci && npm run build
import { build } from "esbuild";
import { copyFileSync, mkdirSync, rmSync } from "node:fs";

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist");
await build({
  entryPoints: ["src/main.js"],
  bundle: true,
  minify: true,
  format: "esm",
  target: ["es2020", "safari15", "chrome90"],
  outdir: "dist",
  legalComments: "eof",
  sourcemap: false,
});
for (const f of ["index.html", "style.css"]) copyFileSync(`src/${f}`, `dist/${f}`);
copyFileSync("../miniapp/src/assets/logo.png", "dist/logo.png");
console.log("built admin-panel/dist/");
