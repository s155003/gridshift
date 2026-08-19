/* Screenshot the live dashboard and report anything the browser complains about.
 *
 * Everything else in this repo is verified by grep, build output or a test.
 * None of that catches a React runtime error or a layout defect, so this
 * drives a real browser against the deployed page and captures both what it
 * looks like and what the console says.
 *
 *     node shoot.mjs [url]
 */

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const URL = process.argv[2] ?? "https://s155003.github.io/gridshift/";
const OUT = "../assets";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });

const errors = [];
page.on("console", (m) => {
  if (m.type() === "error") errors.push(`console.error: ${m.text()}`);
});
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("requestfailed", (r) => errors.push(`request failed: ${r.url()} ${r.failure()?.errorText}`));

console.log(`opening ${URL}`);
await page.goto(URL, { waitUntil: "networkidle", timeout: 90_000 });

// The figures only exist once a forecast has arrived and been scheduled.
await page.waitForFunction(
  () => {
    const dd = document.querySelector("dl dd");
    return dd && /\d/.test(dd.textContent);
  },
  { timeout: 90_000 },
).catch(() => errors.push("figures never populated within 90s"));

await page.waitForTimeout(1200); // let the entry animations settle

const verdict = (await page.locator("p").first().innerText().catch(() => "")).replace(/\s+/g, " ");
const cells = await page.locator("dl div").allInnerTexts().catch(() => []);
const windows = await page.locator("ul li").allInnerTexts().catch(() => []);
const tier = await page.locator("header span").innerText().catch(() => "");
const hasSvg = await page.locator("svg polyline, svg path").count();

await page.screenshot({ path: `${OUT}/dashboard.png`, fullPage: true });
console.log("wrote assets/dashboard.png");

// Switch to a transferred region to prove the caveat path renders too.
await page.selectOption("#region", "CAISO").catch(() => {});
await page.waitForTimeout(3500);
const tier2 = await page.locator("header span").innerText().catch(() => "");
await page.screenshot({ path: `${OUT}/dashboard-caiso.png`, fullPage: true });
console.log("wrote assets/dashboard-caiso.png");

await browser.close();

console.log("\n--- what the page actually rendered ---");
console.log("tier badge (GB) :", tier);
console.log("tier badge (CAISO):", tier2);
console.log("chart drawn     :", hasSvg > 0 ? "yes" : "NO");
console.log("summary cells   :", cells.map((c) => c.replace(/\n/g, "=")).join(" | ") || "(none)");
console.log("run windows     :", windows.join(" | ") || "(none)");
console.log("verdict         :", verdict.slice(0, 220));

console.log("\n--- browser complaints ---");
console.log(errors.length ? errors.join("\n") : "none");
process.exit(errors.length ? 1 : 0);
