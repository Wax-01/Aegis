import { SESSION_STATUS } from "./format";
import type { Saga } from "./types";

export type StopState = "pending" | "current" | "done" | "failed";
export type ReturnState = "pending" | "done" | "failed";

export interface MainStop {
  key: string;
  label: string;
  service: string;
  state: StopState;
  detail: string | null;
  errorCode: string | null;
}

export interface ReturnStop {
  key: string;
  label: string;
  /** Índice de la parada principal que deshace (0 reserva, 1 cobro, 2 activación). */
  undoes: number;
  state: ReturnState;
  detail: string | null;
}

export interface LineModel {
  stops: MainStop[];
  returns: ReturnStop[];
  /** Hasta qué parada llegó el tren por la línea principal. */
  reached: number;
  /** La línea de retorno está abierta (hay compensaciones previstas o ejecutadas). */
  returning: boolean;
  /** Fracción dibujada de la línea de retorno (0..1). */
  returnProgress: number;
  failedAt: number | null;
  /** Parada de retorno donde está el tren, o null si sigue en la línea principal. */
  trainOnReturn: number | null;
}

const ACTIONS = [
  { key: "RESERVE_CONNECTOR", label: "Reserva", service: "station-reservation" },
  { key: "CHARGE_WALLET", label: "Cobro", service: "billing-wallet" },
  { key: "ACTIVATE_CHARGER", label: "Activación", service: "energy-dispatch" },
];

const COMPENSATIONS: Record<string, { label: string; undoes: number }> = {
  RELEASE_CONNECTOR: { label: "Liberación", undoes: 0 },
  REFUND_WALLET: { label: "Reembolso", undoes: 1 },
  ABORT_CHARGER: { label: "Aborto", undoes: 2 },
};

const COMPENSATION_FOR = ["RELEASE_CONNECTOR", "REFUND_WALLET", "ABORT_CHARGER"];

const RETURNING = new Set(["COMPENSATING", "COMPENSATED", "COMPENSATION_FAILED"]);

export function emptyModel(): LineModel {
  return {
    stops: [
      ...ACTIONS.map((a) => ({ ...a, state: "pending" as StopState, detail: null, errorCode: null })),
      { key: "SESSION", label: "Carga", service: "energy-dispatch", state: "pending", detail: null, errorCode: null },
    ],
    returns: [],
    reached: -1,
    returning: false,
    returnProgress: 0,
    failedAt: null,
    trainOnReturn: null,
  };
}

export function buildModel(saga: Saga | null): LineModel {
  if (!saga) return emptyModel();
  const model = emptyModel();
  const actions = saga.steps.filter((s) => s.type === "ACTION");
  const comps = saga.steps.filter((s) => s.type === "COMPENSATION");

  let reached = -1;
  ACTIONS.forEach((a, i) => {
    const step = actions.filter((s) => s.name === a.key).at(-1);
    if (!step) return;
    const stop = model.stops[i];
    stop.detail = step.detail;
    stop.errorCode = step.errorCode;
    if (step.status === "SUCCEEDED") {
      stop.state = "done";
      reached = i;
    } else if (step.status === "FAILED") {
      stop.state = "failed";
      model.failedAt = i;
      reached = i;
    }
  });

  const returning = RETURNING.has(saga.status) || comps.length > 0;

  if (!saga.isTerminal && !returning && model.failedAt === null) {
    // El tren va camino a la siguiente parada.
    const next = Math.min(reached + 1, 2);
    if (model.stops[next].state === "pending") {
      model.stops[next].state = "current";
      reached = next;
    }
  }

  // Parada final: la sesión de carga física.
  const session = model.stops[3];
  if (saga.status === "COMPLETED") {
    reached = 3;
    const charging = saga.chargingStatus === "CHARGING" || saga.chargingStatus === "ACTIVE";
    session.state = charging ? "current" : saga.chargingStatus === "FAULTED" ? "failed" : "done";
    const kwh = saga.energyDeliveredKwh;
    session.detail = charging
      ? "Entregando energía"
      : saga.chargingStatus
        ? `Sesión ${(SESSION_STATUS[saga.chargingStatus] ?? saga.chargingStatus).toLowerCase()}${kwh ? ` · ${kwh.toFixed(1)} kWh` : ""}`
        : null;
  }

  if (returning) {
    // Compensaciones previstas: una por cada paso que alcanzó a ejecutarse (en orden inverso).
    const expected: string[] = [];
    for (let i = 2; i >= 0; i--) {
      const st = model.stops[i].state;
      if (st === "done" || st === "failed") expected.push(COMPENSATION_FOR[i]);
    }
    const executed = new Map(comps.map((c) => [c.name, c]));
    // Pasos fallidos sin compensación ejecutada no se compensan (error de negocio): fuera de la lista.
    const names = expected.filter((n) => {
      if (executed.has(n)) return true;
      const idx = COMPENSATIONS[n].undoes;
      return model.stops[idx].state === "done" || saga.status === "COMPENSATING";
    });
    comps.forEach((c) => {
      if (!names.includes(c.name)) names.push(c.name);
    });
    names.sort((a, b) => COMPENSATIONS[b].undoes - COMPENSATIONS[a].undoes);
    model.returns = names.map((n) => {
      const step = executed.get(n);
      return {
        key: n,
        label: COMPENSATIONS[n].label,
        undoes: COMPENSATIONS[n].undoes,
        state: step ? (step.status === "COMPENSATED" ? "done" : "failed") : "pending",
        detail: step?.detail ?? null,
      };
    });
    const doneCount = model.returns.filter((r) => r.state !== "pending").length;
    const terminal = saga.status === "COMPENSATED" || saga.status === "COMPENSATION_FAILED";
    model.returnProgress = terminal ? 1 : model.returns.length ? Math.max(0.12, doneCount / model.returns.length) : 0.12;
    const lastDone = [...model.returns].reverse().find((r) => r.state !== "pending");
    const lastIdx = lastDone ? model.returns.indexOf(lastDone) : -1;
    model.trainOnReturn = lastIdx >= 0 ? lastIdx : null;
  }

  model.reached = reached;
  model.returning = returning;
  return model;
}
