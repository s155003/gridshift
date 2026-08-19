/* Drive the new search controls in a real browser.
 *
 * Typing a workload and picking a region out of 214 are interactions, and
 * interactions are exactly what a build and a unit test cannot check.
 *
 *     node shoot-search.mjs [url]
 */

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const URL = process.argv[2] ?? "http://localhost:4173/gridshift/";
mkdirSync("../assets", { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => m.type() === "error" && errors.push(`console: ${m.text()}`));

await page.goto(URL, { waitUntil: "networkidle", timeout: 90_000 });
await page.waitForFunction(() => {
  const dd = document.querySelector("dl dd");
  return dd && /\d/.test(dd.textContent);
}, { timeout: 90_000 }).catch(() => errors.push("figures never populated"));

const read = async () => (await page.locator("#verdict, section p").filter({ hasText: /Run |Starting now/ }).first().innerText().catch(() => "")).replace(/\s+/g, " ");

console.log("--- typing workloads ---");
for (const q of [
  "run the dishwasher before 7am",
  "train a model for 4 hours on a 700W GPU by tomorrow",
  "8 hour data centre batch, no rush",
  "heat the hot water for 3 hours overnight",
]) {
  await page.fill("#workload", q);
  await page.press("#workload", "Enter");
  await page.waitForTimeout(700);
  const summary = await page.locator("text=/^Read as/").first().innerText().catch(() => "(no summary)");
  console.log(`  "${q}"`);
  console.log(`     ${summary.replace(/\s+/g, " ")}`);
}

console.log("\n--- region search across 214 regions ---");
for (const q of ["poland", "kenya", "brazil", "curacao"]) {
  await page.click("#region");
  await page.fill("#region", q);
  await page.waitForTimeout(350);
  const first = await page.locator('#region-list li button').first().innerText().catch(() => "(none)");
  console.log(`  "${q}" -> ${first.replace(/\s+/g, " ")}`);
}

// Commit to one and confirm the forecast actually reloads for it.
await page.click("#region");
await page.fill("#region", "poland");
await page.waitForTimeout(350);
await page.locator("#region-list li button").first().click();
await page.waitForTimeout(6000);
console.log("\nafter switching to Poland:");
console.log("  " + (await read()).slice(0, 190));

await page.evaluate(async () => {
  const step = window.innerHeight * 0.8;
  for (let y = 0; y < document.body.scrollHeight; y += step) {
    window.scrollTo(0, y);
    await new Promise((r) => setTimeout(r, 200));
  }
  window.scrollTo(0, 0);
});
await page.waitForTimeout(900);
await page.screenshot({ path: "../assets/dashboard.png", fullPage: true });
console.log("\nwrote assets/dashboard.png");

await browser.close();
console.log("\n--- browser complaints ---");
console.log(errors.length ? errors.join("\n") : "none");
process.exit(errors.length ? 1 : 0);
