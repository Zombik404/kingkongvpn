// Clickable demo of the admin panel on sample data: node demo/build.mjs → demo/dist/
import { build } from "esbuild";
import { copyFileSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";

const out = "demo/dist";
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
await build({
  entryPoints: { main: "demo/entry.js" },
  bundle: true,
  minify: true,
  format: "esm",
  target: ["es2020", "safari15", "chrome90"],
  outdir: out,
  loader: { ".json": "json" },
  legalComments: "none",
});
copyFileSync("src/style.css", `${out}/style.css`);
copyFileSync("demo/demo.css", `${out}/demo.css`);
copyFileSync("../miniapp/src/assets/logo.png", `${out}/logo.png`);
const html = readFileSync("src/index.html", "utf8")
  .replace("<title>KingKong VPN — админка</title>", "<title>KingKong Admin Demo</title>")
  .replace('<link rel="stylesheet" href="style.css">', '<link rel="stylesheet" href="style.css">\n  <link rel="stylesheet" href="demo.css">');
writeFileSync(`${out}/index.html`, html);
console.log("built admin-panel/demo/dist/");
