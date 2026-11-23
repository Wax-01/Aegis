// Capturas de revisión visual (no forma parte del build). Uso:
//   node scripts/capture.mjs [baseUrl] [outDir]
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const base = process.argv[2] ?? "http://localhost:5173";
const out = process.argv[3] ?? "../.impeccable/review";
const gqlUrl = process.env.E2E_GRAPHQL_URL ?? "http://127.0.0.1:8080/graphql";
mkdirSync(out, { recursive: true });

async function api(query, variables = {}) {
  const res = await fetch(gqlUrl, {
    method: "POST",
    headers: { "content-type": "application/json", "x-admin-token": "local-admin-token" },
    body: JSON.stringify({ query, variables }),
  });
  return res.json();
}
const setFault = (on) =>
  api(`mutation($e:Boolean!){ setFeatureFlag(key:"SIMULATE_CHARGER_HARDWARE_FAULT", enabled:$e){ key } }`, { e: on });

const browser = await chromium.launch();
const desk = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await desk.goto(base);
await desk.getByRole("button", { name: "Operación" }).click();
await desk.waitForSelector(".connector");
await desk.waitForTimeout(800);
await desk.screenshot({ path: `${out}/desktop-empty.png`, fullPage: true });

// Carga con falla física: ramal de retorno
await setFault(true);
await desk.waitForTimeout(3500);
await desk.locator(".connector:not([disabled])", { hasNotText: "Ultra" }).nth(1).click();
await desk.waitForTimeout(600);
await desk.screenshot({ path: `${out}/desktop-selected.png` });
await desk.getByRole("button", { name: "Reservar y activar" }).click();
await desk.waitForTimeout(1300);
await desk.screenshot({ path: `${out}/desktop-midflight.png` });
await desk.locator(".trip-meta .status", { hasText: "Compensada" }).waitFor({ timeout: 30000 });
await desk.waitForTimeout(1200);
await desk.screenshot({ path: `${out}/desktop.png`, fullPage: true });
await setFault(false);

// Carga feliz
await desk.waitForTimeout(3500);
await desk.getByRole("button", { name: "Nueva carga" }).click();
await desk.locator(".connector:not([disabled])", { hasNotText: "Ultra" }).nth(3).click();
await desk.getByRole("button", { name: "Reservar y activar" }).click();
await desk.locator(".trip-meta .status", { hasText: "Completada" }).waitFor({ timeout: 30000 });
await desk.waitForTimeout(2500);
await desk.screenshot({ path: `${out}/desktop-happy.png` });

for (const [tab, file] of [
  ["Transacciones", "desktop-transacciones.png"],
  ["Feature flags", "desktop-flags.png"],
  ["Salud", "desktop-salud.png"],
]) {
  await desk.getByRole("button", { name: tab }).click();
  await desk.waitForTimeout(1500);
  await desk.screenshot({ path: `${out}/${file}`, fullPage: true });
}

const mob = await browser.newPage({ viewport: { width: 390, height: 844 } });
await mob.goto(base);
await mob.evaluate(() => localStorage.setItem("aegisvolt.tab", "operacion"));
await mob.goto(base);
await mob.waitForSelector(".connector");
await mob.waitForTimeout(1000);
await mob.screenshot({ path: `${out}/mobile.png`, fullPage: true });
await mob.getByRole("button", { name: "Transacciones" }).click();
await mob.waitForTimeout(1200);
await mob.screenshot({ path: `${out}/mobile-transacciones.png`, fullPage: true });

await browser.close();
console.log("capturas en", out);
