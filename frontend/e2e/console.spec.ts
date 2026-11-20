import { expect, test, type Page } from "@playwright/test";

const GRAPHQL_URL = process.env.E2E_GRAPHQL_URL ?? "http://127.0.0.1:8080/graphql";
const ADMIN_TOKEN = process.env.ADMIN_TOKEN ?? "local-admin-token";
const FAULT = "SIMULATE_CHARGER_HARDWARE_FAULT";

async function api<T>(query: string, variables: Record<string, unknown> = {}): Promise<T> {
  const res = await fetch(GRAPHQL_URL, {
    method: "POST",
    headers: { "content-type": "application/json", "x-admin-token": ADMIN_TOKEN },
    body: JSON.stringify({ query, variables }),
  });
  const body = (await res.json()) as { data: T; errors?: { message: string }[] };
  if (body.errors?.length) throw new Error(body.errors[0].message);
  return body.data;
}

async function setFlag(key: string, enabled: boolean) {
  await api(`mutation($k: String!, $e: Boolean!) { setFeatureFlag(key: $k, enabled: $e) { key } }`, {
    k: key,
    e: enabled,
  });
  // Los servicios cachean las flags ~3 s.
  await new Promise((r) => setTimeout(r, 3500));
}

async function openConsole(page: Page) {
  await page.route("**/config.js", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: `window.__AEGIS_CONFIG__ = { environment: "dev", graphqlHttpUrl: ${JSON.stringify(GRAPHQL_URL)} };`,
    }),
  );
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.goto("/");
}

async function launchCharge(page: Page) {
  await page.getByRole("button", { name: "Operación" }).click();
  // Conector libre de una estación que no esté marcada en falla.
  const free = page.locator(".connector:not([disabled])", { hasNotText: "Ultra" }).first();
  await expect(free).toBeVisible();
  await free.click();
  await page.getByLabel("Flota").selectOption("FLEET-ANDES-EXPRESS");
  await page.getByRole("button", { name: "Reservar y activar" }).click();
}

test.afterAll(async () => {
  await setFlag(FAULT, false);
});

test("muestra el ambiente y las estaciones en vivo", async ({ page }) => {
  await openConsole(page);
  await expect(page.getByText("Línea dev", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Estaciones" })).toBeVisible();
  await expect(page.locator(".connector").first()).toBeVisible();
  await expect(page.getByText("En vivo")).toBeVisible();
});

test("SAGA feliz: reserva, cobro y activación completan el recorrido", async ({ page }) => {
  await setFlag(FAULT, false);
  await openConsole(page);
  await launchCharge(page);
  const trip = page.locator(".trip");
  await expect(trip.locator(".trip-meta .status")).toHaveText(/Completada/);
  await expect(trip.locator(".stop-main.is-failed")).toHaveCount(0);
  await expect(trip.locator(".stop-return")).toHaveCount(0);
});

test("falla física: el ramal de retorno reembolsa y libera el conector", async ({ page }) => {
  await setFlag(FAULT, true);
  await openConsole(page);
  await launchCharge(page);
  const trip = page.locator(".trip");
  await expect(trip.locator(".trip-meta .status")).toHaveText(/Compensada/);
  await expect(trip.locator(".stop-main.is-failed .stop-name")).toHaveText("Activación");
  await expect(trip.locator(".stop-return.is-done .stop-name")).toHaveText(["Reembolso", "Liberación"]);
  await setFlag(FAULT, false);
});

test("el historial muestra pasos y compensaciones de la transacción", async ({ page }) => {
  await openConsole(page);
  await page.getByRole("button", { name: "Transacciones" }).click();
  await page.getByRole("button", { name: /Compensadas/ }).click();
  await expect(page.locator(".timeline .tl-comp").first()).toBeVisible();
  await expect(page.getByText("correlation_id")).toBeVisible();
});

test("el visualizador de flags lista las tres flags del ambiente", async ({ page }) => {
  await openConsole(page);
  await page.getByRole("button", { name: "Feature flags" }).click();
  for (const key of ["ENABLE_DYNAMIC_SURGE_PRICING", "ENABLE_FAST_CHARGE_BOOST", FAULT]) {
    await expect(page.getByText(key, { exact: true })).toBeVisible();
  }
  await expect(page.getByRole("switch")).toHaveCount(3);
});
