// Renders the PNG icons from src/icon.svg once; build.py embeds all three in index.html.
// Only needed after changing src/icon.svg:  npx -y -p playwright@1.61.0 node tools/render-icons.mjs
//   src/icon-32.png             32 x 32, the browser-tab fallback for browsers without SVG favicons
//   src/apple-touch-icon.png    180 x 180, full-bleed: iOS rounds the corners itself
import { chromium } from "playwright";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

const src = resolve(dirname(new URL(import.meta.url).pathname), "..", "src");
const svg = readFileSync(join(src, "icon.svg"), "utf8");
const browser = await chromium.launch();
async function render(markup, size, file) {
  const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
  const sized = markup.replace(/width="64" height="64"/, `width="${size}" height="${size}"`);
  await page.setContent(`<!doctype html><html><body style="margin:0;background:transparent">${sized}</body></html>`);
  writeFileSync(join(src, file), await page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } }));
  await page.close();
}
await render(svg, 32, "icon-32.png");
await render(svg.replace('rx="15"', 'rx="0"'), 180, "apple-touch-icon.png");
await browser.close();
console.log("wrote src/icon-32.png and src/apple-touch-icon.png");
