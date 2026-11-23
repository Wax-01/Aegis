import { Square, TriangleAlert, Zap } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { gql, QUOTE_QUERY, SESSION_QUERY, START_CHARGE, STOP_CHARGE } from "../api";
import { dateTime, humanize, money, num, SESSION_STATUS, shortId, STEP_LABEL } from "../format";
import { useMutation, useQuery } from "../hooks";
import type { ChargingSession, FeatureFlag, PriceQuote, Saga, Station, Wallet } from "../types";
import { LineDiagram } from "./LineDiagram";
import { MiniLine } from "./MiniLine";
import { SagaStatusLabel } from "./SagaStatus";

export interface Selection {
  stationId: string;
  connectorId: string;
}

interface Props {
  stations: Station[] | null;
  sagas: Saga[] | null;
  wallets: Wallet[] | null;
  flags: FeatureFlag[] | null;
  selection: Selection | null;
  onSelection: (s: Selection | null) => void;
  activeSaga: Saga | null;
  onActivate: (id: string | null) => void;
  onWalletsChanged: () => void;
}

export function OperationView(props: Props) {
  const { activeSaga, sagas, onActivate } = props;
  const session = useQuery<{ chargingSession: ChargingSession | null }>(
    SESSION_QUERY,
    activeSaga?.status === "COMPLETED" ? { id: activeSaga.id } : null,
    { intervalMs: 2000 },
  ).data?.chargingSession;

  // La sesión física sigue viva después de que la SAGA termina: su estado alimenta la última parada.
  const sagaForLine = useMemo(() => {
    if (!activeSaga || !session) return activeSaga;
    return { ...activeSaga, chargingStatus: session.status, energyDeliveredKwh: session.energyKwh };
  }, [activeSaga, session]);

  return (
    <main className="work" id="contenido">
      <section className="trip" aria-labelledby="trip-title">
        <TripHeader saga={activeSaga} onClear={() => onActivate(null)} />
        <LineDiagram
          saga={sagaForLine}
          emptyHint={
            props.selection
              ? `Listo: ${props.selection.connectorId} seleccionado. Pulsa «Reservar y activar» para iniciar el recorrido.`
              : "Elige un conector libre en Estaciones y lanza la carga: el recorrido aparece aquí, estación por estación."
          }
        />
        {activeSaga?.failureReason && <FailureNote saga={activeSaga} />}
        {session && activeSaga && <SessionStrip session={session} saga={activeSaga} />}
      </section>

      <ChargeForm {...props} />

      <section className="recent" aria-labelledby="recent-title">
        <div className="section-head">
          <h2 id="recent-title">Últimos recorridos</h2>
          <span className="muted">Clic en una fila para verla en la línea</span>
        </div>
        <TripTable sagas={sagas?.slice(0, 8) ?? null} activeId={activeSaga?.id ?? null} onPick={onActivate} />
      </section>
    </main>
  );
}

function TripHeader({ saga, onClear }: { saga: Saga | null; onClear: () => void }) {
  if (!saga) {
    return (
      <div className="trip-head">
        <h1 id="trip-title">Nueva carga</h1>
      </div>
    );
  }
  return (
    <div className="trip-head">
      <h1 id="trip-title">
        {saga.fleetId} <span className="arrow">→</span> {saga.connectorId}
      </h1>
      <div className="trip-meta">
        <SagaStatusLabel status={saga.status} />
        <span className="serial" title="correlation_id = saga_id: lo comparten los 4 servicios y CloudWatch">
          {saga.correlationId}
        </span>
        <span className="muted">{dateTime(saga.createdAt)}</span>
        {saga.amount !== null && <span className="muted">{money(saga.amount, saga.currency ?? "USD")}</span>}
        <button type="button" className="btn-link" onClick={onClear}>
          Nueva carga
        </button>
      </div>
    </div>
  );
}

function FailureNote({ saga }: { saga: Saga }) {
  return (
    <p className="failure-note">
      <TriangleAlert size={18} aria-hidden="true" />
      <span>
        <b>
          Falló {STEP_LABEL[saga.failureStep ?? ""] ?? saga.failureStep}
          {saga.failureCode ? ` · ${saga.failureCode}` : ""}.
        </b>{" "}
        {humanize(saga.failureReason ?? "")}
      </span>
    </p>
  );
}

function SessionStrip({ session, saga }: { session: ChargingSession; saga: Saga }) {
  const stop = useMutation((id: string) => gql<{ stopChargingSession: Saga }>(STOP_CHARGE, { id }));
  const charging = session.status === "CHARGING" || session.status === "ACTIVE";
  const pct = session.targetKwh > 0 ? Math.min(100, (session.energyKwh / session.targetKwh) * 100) : 0;
  return (
    <div className="session" aria-live="polite">
      <dl className="session-figures">
        <div>
          <dt>Potencia</dt>
          <dd>
            {num(session.currentPowerKw, 0)} <small>kW</small>
          </dd>
        </div>
        <div>
          <dt>Energía</dt>
          <dd>
            {num(session.energyKwh)} <small>/ {num(session.targetKwh, 0)} kWh</small>
          </dd>
        </div>
        <div>
          <dt>Batería</dt>
          <dd>
            {num(session.soc, 0)} <small>%</small>
          </dd>
        </div>
        <div>
          <dt>Sesión</dt>
          <dd className="session-state">{SESSION_STATUS[session.status] ?? session.status}</dd>
        </div>
      </dl>
      <div className="meter" aria-hidden="true">
        <span style={{ width: `${pct}%` }} />
      </div>
      {charging && (
        <button type="button" className="btn btn-quiet" disabled={stop.pending} onClick={() => stop.run(saga.id)}>
          <Square size={14} aria-hidden="true" />
          {stop.pending ? "Deteniendo…" : "Detener carga"}
        </button>
      )}
      {stop.error && <p className="inline-error">{stop.error}</p>}
    </div>
  );
}

function ChargeForm({ stations, wallets, flags, selection, onSelection, onActivate, onWalletsChanged }: Props) {
  const [fleetId, setFleetId] = useState("FLEET-ANDES-EXPRESS");
  const [vehicleId, setVehicleId] = useState("VAN-BOG-0417");
  const [kwh, setKwh] = useState(40);
  const [boost, setBoost] = useState(false);
  const start = useMutation((input: Record<string, unknown>) =>
    gql<{ reserveAndActivateCharge: Saga }>(START_CHARGE, { input }),
  );

  const station = stations?.find((s) => s.id === selection?.stationId) ?? null;
  const connector = station?.connectors.find((c) => c.id === selection?.connectorId) ?? null;
  const connectorFree = connector?.status === "AVAILABLE";
  // Regla de negocio de station-reservation: ULTRA (>= 300 kW) solo con reserva prioritaria (impulso).
  const ultra = connector?.tier === "ULTRA";
  const boostOn = boost || ultra;
  const wallet = wallets?.find((w) => w.fleetId === fleetId) ?? null;
  const flagOn = (key: string) => flags?.find((f) => f.key === key)?.enabled ?? false;

  const quote = useQuery<{ priceQuote: PriceQuote }>(
    QUOTE_QUERY,
    selection && kwh > 0 ? { s: selection.stationId, c: selection.connectorId, kwh, boost: boostOn } : null,
  );
  const q = quote.data?.priceQuote;
  const short = wallet && q ? wallet.balance < q.total : false;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!selection) return;
    const res = await start.run({
      fleetId,
      vehicleId: vehicleId.trim(),
      stationId: selection.stationId,
      connectorId: selection.connectorId,
      estimatedKwh: kwh,
      fastChargeBoost: boostOn,
    });
    if (res) {
      onActivate(res.reserveAndActivateCharge.id);
      onSelection(null);
      setTimeout(onWalletsChanged, 2500);
    }
  };

  return (
    <form className="charge-form" onSubmit={submit} aria-labelledby="form-title">
      <h2 id="form-title" className="sr-only">
        Lanzar carga
      </h2>
      <label className="field">
        <span>Flota</span>
        <select value={fleetId} onChange={(e) => setFleetId(e.target.value)}>
          {(wallets ?? [{ fleetId, name: fleetId, balance: 0, currency: "USD", updatedAt: null }]).map((w) => (
            <option key={w.fleetId} value={w.fleetId}>
              {w.fleetId} · {money(w.balance, w.currency)}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Vehículo</span>
        <input value={vehicleId} onChange={(e) => setVehicleId(e.target.value)} required maxLength={40} />
      </label>
      <label className="field field-wide">
        <span>Conector</span>
        <select
          value={selection ? `${selection.stationId}|${selection.connectorId}` : ""}
          onChange={(e) => {
            const [stationId, connectorId] = e.target.value.split("|");
            onSelection(stationId ? { stationId, connectorId } : null);
          }}
          required
        >
          <option value="">Elige un conector libre…</option>
          {stations?.map((s) => (
            <optgroup key={s.id} label={`${s.name} · ${s.city}`}>
              {s.connectors.map((c) => (
                <option key={c.id} value={`${s.id}|${c.id}`} disabled={c.status !== "AVAILABLE"}>
                  {c.id} · {c.tier} {c.powerKw} kW{c.status !== "AVAILABLE" ? " · ocupado" : ""}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      <label className="field field-narrow">
        <span>Energía (kWh)</span>
        <input
          type="number"
          min={1}
          max={300}
          step={1}
          value={kwh}
          onChange={(e) => setKwh(Number(e.target.value))}
          required
        />
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={boostOn}
          disabled={ultra}
          onChange={(e) => setBoost(e.target.checked)}
        />
        <span>
          Impulso de carga rápida
          {ultra && flagOn("ENABLE_FAST_CHARGE_BOOST") && <small> · obligatorio en conectores ULTRA</small>}
          {ultra && !flagOn("ENABLE_FAST_CHARGE_BOOST") && (
            <small className="warn-inline"> · ULTRA exige impulso y la flag está apagada: la reserva fallará</small>
          )}
          {!ultra && !flagOn("ENABLE_FAST_CHARGE_BOOST") && <small> · flag apagada en este ambiente</small>}
        </span>
      </label>

      <div className="quote" aria-live="polite">
        {!selection && <span className="muted">Selecciona un conector para cotizar.</span>}
        {selection && quote.error && <span className="inline-error">{quote.error}</span>}
        {q && (
          <>
            <span>
              {q.tier} {money(q.ratePerKwh, q.currency)}/kWh × {num(q.estimatedKwh, 0)} kWh
              {q.surgePricingEnabled && q.surgeMultiplier !== 1 && (
                <b className="surge">
                  {" "}
                  · surge {num(q.surgeMultiplier, 2)}× {q.peakHour ? "(hora pico)" : "(valle)"}
                </b>
              )}
              {q.boostFee > 0 && <> · impulso {money(q.boostFee, q.currency)}</>}
            </span>
            <strong className="quote-total">{money(q.total, q.currency)}</strong>
            {short && <span className="warn-text">Saldo insuficiente: el cobro fallará y se liberará el conector.</span>}
          </>
        )}
      </div>

      <button type="submit" className="btn btn-primary" disabled={!selection || !connectorFree || start.pending}>
        <Zap size={18} aria-hidden="true" />
        {start.pending ? "Iniciando…" : "Reservar y activar"}
      </button>
      {start.error && <p className="inline-error form-error">{start.error}</p>}
      {flagOn("SIMULATE_CHARGER_HARDWARE_FAULT") && (
        <p className="flag-warning">
          <TriangleAlert size={16} aria-hidden="true" />
          La flag de falla física está activa: la activación fallará y verás el reembolso y la liberación.
        </p>
      )}
    </form>
  );
}

export function TripTable({
  sagas,
  activeId,
  onPick,
  dense = false,
}: {
  sagas: Saga[] | null;
  activeId: string | null;
  onPick: (id: string) => void;
  dense?: boolean;
}) {
  if (!sagas) return <p className="muted pad">Cargando recorridos…</p>;
  if (!sagas.length) return <p className="empty">Todavía no hay recorridos en este ambiente. Lanza la primera carga.</p>;
  return (
    <div className="table-wrap">
      <table className={`trips${dense ? " is-dense" : ""}`}>
        <thead>
          <tr>
            <th scope="col">Recorrido</th>
            <th scope="col">Saga</th>
            {!dense && <th scope="col">Flota</th>}
            <th scope="col">Conector</th>
            <th scope="col" className="num">
              Monto
            </th>
            <th scope="col">Estado</th>
            <th scope="col">Hora</th>
          </tr>
        </thead>
        <tbody>
          {sagas.map((s) => (
            <tr
              key={s.id}
              className={s.id === activeId ? "is-active" : undefined}
              onClick={() => onPick(s.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onPick(s.id);
                }
              }}
              tabIndex={0}
              aria-selected={s.id === activeId}
            >
              <td className="c-line">
                <MiniLine saga={s} />
              </td>
              <td className="c-saga serial">{shortId(s.id)}</td>
              {!dense && <td className="c-fleet">{s.fleetId}</td>}
              <td className="c-conn">{s.connectorId}</td>
              <td className="c-amount num">{s.amount !== null ? money(s.amount, s.currency ?? "USD") : "—"}</td>
              <td className="c-status">
                <SagaStatusLabel status={s.status} />
              </td>
              <td className="c-time muted">{dateTime(s.createdAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
