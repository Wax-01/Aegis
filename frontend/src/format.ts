import type { SagaStatus } from "./types";

export function money(amount: number | null | undefined, currency = "USD"): string {
  if (amount === null || amount === undefined) return "—";
  try {
    return new Intl.NumberFormat("es-CO", { style: "currency", currency, minimumFractionDigits: 2 }).format(
      amount,
    );
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}

export function num(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("es-CO", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(
    value,
  );
}

export function time(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.toLocaleDateString("es-CO", { day: "2-digit", month: "short" })} · ${time(iso)}`;
}

export function shortId(id: string): string {
  return id.replace(/-/g, "").slice(0, 8).toUpperCase();
}

export const SAGA_STATUS: Record<SagaStatus, { label: string; tone: "ok" | "bad" | "run" | "warn" }> = {
  STARTED: { label: "Iniciada", tone: "run" },
  CONNECTOR_RESERVED: { label: "Conector reservado", tone: "run" },
  PAYMENT_CAPTURED: { label: "Pago capturado", tone: "run" },
  COMPLETED: { label: "Completada", tone: "ok" },
  COMPENSATING: { label: "Compensando", tone: "warn" },
  COMPENSATED: { label: "Compensada", tone: "bad" },
  FAILED: { label: "Fallida", tone: "bad" },
  COMPENSATION_FAILED: { label: "Compensación fallida", tone: "bad" },
};

export const STEP_LABEL: Record<string, string> = {
  RESERVE_CONNECTOR: "Reserva",
  CHARGE_WALLET: "Cobro",
  ACTIVATE_CHARGER: "Activación",
  RELEASE_CONNECTOR: "Liberación",
  REFUND_WALLET: "Reembolso",
  ABORT_CHARGER: "Aborto del cargador",
};

export const CONNECTOR_STATUS: Record<string, string> = {
  AVAILABLE: "Libre",
  RESERVED: "Reservado",
  CHARGING: "Cargando",
  FAULTED: "En falla",
  OFFLINE: "Fuera de línea",
};

export const FLAG_LABEL: Record<string, string> = {
  ENABLE_DYNAMIC_SURGE_PRICING: "Tarifa dinámica (surge pricing)",
  ENABLE_FAST_CHARGE_BOOST: "Impulso de carga rápida",
  SIMULATE_CHARGER_HARDWARE_FAULT: "Simular falla física del cargador",
};

export const STEP_OUTCOME: Record<string, string> = {
  SUCCEEDED: "completada",
  FAILED: "falló",
  COMPENSATED: "ejecutada",
};

export const SESSION_STATUS: Record<string, string> = {
  CHARGING: "Cargando",
  ACTIVE: "Cargando",
  COMPLETED: "Completada",
  STOPPED: "Detenida",
  ABORTED: "Abortada",
  FAULTED: "En falla",
};

const BACKEND_WORDS: [RegExp, string][] = [
  [/\s*->\s*/g, " → "],
  [/AVAILABLE \(RELEASED\)/g, "disponible (liberado)"],
  [/\bRESERVED\b/g, "reservado"],
  [/\(REFUNDED\)/g, "(reembolsado)"],
  [/\(RELEASED\)/g, "(liberado)"],
  [/\bAVAILABLE\b/g, "disponible"],
  [/sesión CHARGING/g, "sesión en carga"],
  [/\bCHARGING\b/g, "en carga"],
  [/surge x(\d+)\.(\d+)/g, "recargo ×$1,$2"],
  [/\(ground fault\)/g, "(falla a tierra)"],
];

/** Los servicios escriben el detalle de cada paso con estados técnicos en inglés: se traducen al mostrarlos. */
export function humanize(detail: string): string {
  return BACKEND_WORDS.reduce((s, [re, to]) => s.replace(re, to), detail);
}
