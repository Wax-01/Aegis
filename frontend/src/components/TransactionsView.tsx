import { RotateCcw } from "lucide-react";
import { useState } from "react";
import { gql, RECOVER_SAGA, WALLET_TX_QUERY } from "../api";
import { dateTime, FLAG_LABEL, humanize, money, num, STEP_LABEL, STEP_OUTCOME, time } from "../format";
import { useMutation, useQuery } from "../hooks";
import type { Saga, SagaStatus, WalletTransaction } from "../types";
import { LineDiagram } from "./LineDiagram";
import { TripTable } from "./OperationView";
import { SagaStatusLabel } from "./SagaStatus";

const FILTERS: { id: string; label: string; match: (s: SagaStatus) => boolean }[] = [
  { id: "all", label: "Todas", match: () => true },
  { id: "ok", label: "Completadas", match: (s) => s === "COMPLETED" },
  { id: "comp", label: "Compensadas", match: (s) => s === "COMPENSATED" || s === "COMPENSATING" },
  { id: "bad", label: "Fallidas", match: (s) => s === "FAILED" || s === "COMPENSATION_FAILED" },
  {
    id: "run",
    label: "En curso",
    match: (s) => s === "STARTED" || s === "CONNECTOR_RESERVED" || s === "PAYMENT_CAPTURED",
  },
];

interface Props {
  sagas: Saga[] | null;
  error: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function TransactionsView({ sagas, error, selectedId, onSelect }: Props) {
  const [filter, setFilter] = useState("all");
  const f = FILTERS.find((x) => x.id === filter) ?? FILTERS[0];
  const visible = sagas?.filter((s) => f.match(s.status)) ?? null;
  const selected = sagas?.find((s) => s.id === selectedId) ?? visible?.[0] ?? null;

  return (
    <main className="work work-split" id="contenido">
      <section className="ledger" aria-labelledby="ledger-title">
        <div className="section-head">
          <h1 id="ledger-title">Transacciones</h1>
          <span className="muted">Historial SAGA del ambiente, en vivo</span>
        </div>
        <div className="filters" role="group" aria-label="Filtrar por estado">
          {FILTERS.map((x) => {
            const count = sagas?.filter((s) => x.match(s.status)).length ?? 0;
            return (
              <button
                key={x.id}
                type="button"
                className="chip"
                aria-pressed={filter === x.id}
                onClick={() => setFilter(x.id)}
              >
                {x.label} <span className="chip-count">{count}</span>
              </button>
            );
          })}
        </div>
        {error && <p className="inline-error">{error}</p>}
        {visible && visible.length === 0 && sagas && sagas.length > 0 ? (
          <p className="empty">
            Ningún recorrido con estado «{f.label}».{" "}
            <button type="button" className="btn-link" onClick={() => setFilter("all")}>
              Ver todas
            </button>
          </p>
        ) : (
          <TripTable sagas={visible} activeId={selected?.id ?? null} onPick={onSelect} dense />
        )}
      </section>
      <section className="detail" aria-label="Detalle de la transacción">
        {selected ? <SagaDetail saga={selected} /> : <p className="empty">Selecciona un recorrido.</p>}
      </section>
    </main>
  );
}

function SagaDetail({ saga }: { saga: Saga }) {
  const recover = useMutation((id: string) => gql<{ recoverSaga: Saga }>(RECOVER_SAGA, { id }));
  const wallet = useQuery<{ wallet: { transactions: WalletTransaction[] } }>(
    WALLET_TX_QUERY,
    { id: saga.fleetId },
    { intervalMs: 4000 },
  );
  const moves = wallet.data?.wallet.transactions.filter((t) => t.sagaId === saga.id) ?? [];
  const stale = !saga.isTerminal && Date.now() - new Date(saga.updatedAt).getTime() > 60_000;
  const recoverable = saga.status === "COMPENSATION_FAILED" || stale;

  return (
    <div className="detail-body">
      <div className="detail-head">
        <h2>
          {saga.fleetId} <span className="arrow">→</span> {saga.connectorId}
        </h2>
        <SagaStatusLabel status={saga.status} />
      </div>
      <dl className="facts">
        <div>
          <dt>correlation_id</dt>
          <dd className="serial">{saga.correlationId}</dd>
        </div>
        <div>
          <dt>Estación</dt>
          <dd>{saga.stationName ?? saga.stationId}</dd>
        </div>
        <div>
          <dt>Vehículo</dt>
          <dd>{saga.vehicleId}</dd>
        </div>
        <div>
          <dt>Energía</dt>
          <dd>
            {num(saga.estimatedKwh, 0)} kWh · {saga.connectorPowerKw} kW
          </dd>
        </div>
        <div>
          <dt>Monto</dt>
          <dd>
            {money(saga.amount, saga.currency ?? "USD")}
            {saga.surgeMultiplier && saga.surgeMultiplier !== 1 ? ` · recargo ×${num(saga.surgeMultiplier, 2)}` : ""}
          </dd>
        </div>
        <div>
          <dt>Creada</dt>
          <dd>{dateTime(saga.createdAt)}</dd>
        </div>
      </dl>

      <LineDiagram saga={saga} />

      {recoverable && (
        <div className="recover">
          <p>
            {saga.status === "COMPENSATION_FAILED"
              ? "Una compensación falló. Puedes reintentarlas: son idempotentes (no reembolsa dos veces)."
              : "Esta saga lleva más de un minuto sin avanzar. Recuperarla re-ejecuta sus compensaciones."}
          </p>
          <button type="button" className="btn btn-quiet" disabled={recover.pending} onClick={() => recover.run(saga.id)}>
            <RotateCcw size={14} aria-hidden="true" />
            {recover.pending ? "Recuperando…" : "Recuperar saga"}
          </button>
          {recover.error && <p className="inline-error">{recover.error}</p>}
        </div>
      )}

      <h3>Pasos y compensaciones</h3>
      <ol className="timeline">
        {saga.steps.map((st, i) => (
          <li key={`${st.name}-${i}`} className={`tl tl-${st.type === "COMPENSATION" ? "comp" : "act"} is-${st.status.toLowerCase()}`}>
            <span className="tl-time">{time(st.at)}</span>
            <span className="tl-dot" aria-hidden="true" />
            <div className="tl-body">
              <span className="tl-title">
                {STEP_LABEL[st.name] ?? st.name}
                <span className="tl-status">{st.type === "COMPENSATION" ? "compensación" : "acción"} ·{" "}
                  {STEP_OUTCOME[st.status] ?? st.status.toLowerCase()}</span>
              </span>
              <span className="tl-service">{st.service}</span>
              <span className="tl-detail">
                {st.errorCode && <b>{st.errorCode} · </b>}
                {humanize(st.detail)}
              </span>
            </div>
          </li>
        ))}
        {!saga.steps.length && <li className="muted">Sin pasos registrados todavía.</li>}
      </ol>

      <h3>Movimientos de billetera</h3>
      {moves.length ? (
        <table className="moves">
          <tbody>
            {moves.map((t) => (
              <tr key={t.id}>
                <td>{t.type === "CHARGE" ? "Cobro" : t.type === "REFUND" ? "Reembolso" : t.type}</td>
                <td className={`num ${t.type === "REFUND" ? "pos" : ""}`}>
                  {t.type === "REFUND" ? "+" : "−"}
                  {money(Math.abs(t.amount), t.currency)}
                </td>
                <td className="muted">{t.balanceAfter !== null ? `saldo ${money(t.balanceAfter, t.currency)}` : ""}</td>
                <td className="muted">{time(t.createdAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">Sin movimientos para esta saga (el cobro no llegó a capturarse).</p>
      )}

      <h3>Flags al momento de la saga</h3>
      <ul className="snapshot">
        {saga.flagsSnapshot.map((fl) => (
          <li key={fl.key}>
            <span className={`pill-state ${fl.enabled ? "on" : "off"}`}>{fl.enabled ? "ON" : "OFF"}</span>
            {FLAG_LABEL[fl.key] ?? fl.key}
          </li>
        ))}
      </ul>
    </div>
  );
}
