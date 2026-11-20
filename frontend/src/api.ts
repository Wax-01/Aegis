import { createClient, type Client } from "graphql-ws";
import { config } from "./config";

/** Error de GraphQL con el mensaje del servidor (ya viene en español desde el gateway). */
export class ApiError extends Error {}

const ADMIN_TOKEN_KEY = "aegisvolt.adminToken";

export function getAdminToken(): string {
  try {
    return sessionStorage.getItem(ADMIN_TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAdminToken(token: string): void {
  try {
    if (token) sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
    else sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch {
    /* almacenamiento bloqueado: el token vive solo en memoria de esta pestaña */
  }
}

export async function gql<T>(
  query: string,
  variables: Record<string, unknown> = {},
  opts: { url?: string; admin?: boolean; signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (opts.admin) headers["x-admin-token"] = getAdminToken();
  let res: Response;
  try {
    res = await fetch(opts.url ?? config.graphqlHttpUrl, {
      method: "POST",
      headers,
      body: JSON.stringify({ query, variables }),
      signal: opts.signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError("No hay conexión con el gateway GraphQL.");
  }
  const body = (await res.json().catch(() => null)) as { data?: T; errors?: { message: string }[] } | null;
  if (!body) throw new ApiError(`El gateway respondió ${res.status} sin cuerpo JSON.`);
  if (body.errors?.length) throw new ApiError(body.errors.map((e) => e.message).join(" · "));
  return body.data as T;
}

let wsClient: Client | null = null;
type Listener = (connected: boolean) => void;
const listeners = new Set<Listener>();
let connected = false;

function setConnected(value: boolean) {
  connected = value;
  listeners.forEach((l) => l(value));
}

export function onConnectionChange(listener: Listener): () => void {
  listeners.add(listener);
  listener(connected);
  return () => listeners.delete(listener);
}

export function ws(): Client {
  if (!wsClient) {
    wsClient = createClient({
      url: config.graphqlWsUrl,
      retryAttempts: Infinity,
      shouldRetry: () => true,
      retryWait: (retries) => new Promise((r) => setTimeout(r, Math.min(1000 * 2 ** retries, 8000))),
      keepAlive: 10_000,
      on: {
        connected: () => setConnected(true),
        closed: () => setConnected(false),
        error: () => setConnected(false),
      },
    });
  }
  return wsClient;
}

// --------------------------------------------------------------------------- documentos

const CONNECTOR = `id stationId connectorType powerKw tier status sagaId fleetId
  liveSession { sagaId status powerKw energyKwh targetKwh soc }`;

export const STATIONS_LIVE = `subscription { stationsLive {
  id name city country address availableConnectors totalConnectors connectors { ${CONNECTOR} } } }`;

const SAGA = `id correlationId environment status fleetId vehicleId stationId stationName connectorId
  connectorPowerKw estimatedKwh fastChargeBoost amount currency surgeMultiplier failureStep failureCode
  failureReason chargingStatus energyDeliveredKwh createdAt updatedAt isTerminal compensated
  flagsSnapshot { key enabled }
  steps { name service type status detail errorCode at }`;

export const SAGAS_LIVE = `subscription($limit: Int!) { sagasLive(limit: $limit) { ${SAGA} } }`;
export const SAGA_LIVE = `subscription($id: ID!) { sagaLive(sagaId: $id) { ${SAGA} } }`;
export const SAGA_QUERY = `query($id: ID!) { saga(id: $id) { ${SAGA} } }`;

export const START_CHARGE = `mutation($input: ChargeRequestInput!) {
  reserveAndActivateCharge(input: $input, waitForCompletion: false) { ${SAGA} } }`;
export const STOP_CHARGE = `mutation($id: ID!) { stopChargingSession(sagaId: $id) { ${SAGA} } }`;
export const RECOVER_SAGA = `mutation($id: ID!) { recoverSaga(sagaId: $id) { ${SAGA} } }`;

export const SESSION_QUERY = `query($id: ID!) { chargingSession(sagaId: $id) {
  sagaId status powerKw currentPowerKw energyKwh targetKwh soc socStart faultCode faultMessage startedAt endedAt } }`;

const FLAG = "key enabled description environment updatedAt updatedBy source";
export const FLAGS_LIVE = `subscription { featureFlagsLive { ${FLAG} } }`;
export const FLAGS_QUERY = `query { featureFlags { ${FLAG} } environment { name } }`;
export const SET_FLAG = `mutation($key: String!, $enabled: Boolean!) { setFeatureFlag(key: $key, enabled: $enabled) { ${FLAG} } }`;

export const WALLETS_QUERY = `query { wallets { fleetId name balance currency updatedAt } }`;
export const WALLET_TX_QUERY = `query($id: ID!) { wallet(fleetId: $id) { fleetId balance currency
  transactions(limit: 12) { id type sagaId amount currency balanceAfter reason tombstone createdAt } } }`;
export const TOP_UP = `mutation($id: ID!, $amount: Float!) { topUpWallet(fleetId: $id, amount: $amount) { fleetId balance currency } }`;

export const QUOTE_QUERY = `query($s: String!, $c: String!, $kwh: Float!, $boost: Boolean!) {
  priceQuote(stationId: $s, connectorId: $c, estimatedKwh: $kwh, fastChargeBoost: $boost) {
    tier ratePerKwh estimatedKwh surgePricingEnabled peakHour surgeMultiplier energyCost boostFee total currency localTime } }`;

export const HEALTH_QUERY = `query { serviceHealth { name status version track latencyMs error }
  environment { name version track instance region awsBackend tables logGroupPrefix } }`;
