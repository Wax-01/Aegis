import { Check, TrainFront, X } from "lucide-react";
import { buildModel, type LineModel } from "../saga-model";
import { humanize } from "../format";
import type { Saga } from "../types";

/** Posición horizontal (%) de cada parada principal: Reserva, Cobro, Activación, Carga. */
const XS = [7, 35, 63, 91];
const Y_MAIN = 116;
const Y_RETURN = 246;

interface Props {
  saga: Saga | null;
  /** Texto que se muestra cuando todavía no hay recorrido. */
  emptyHint?: string;
}

/**
 * La SAGA dibujada como una línea de metro. Cada paso es una estación; si un paso falla se abre el
 * ramal de retorno y el tren vuelve por las compensaciones (reembolso, liberación).
 */
export function LineDiagram({ saga, emptyHint }: Props) {
  const m = buildModel(saga);
  const returnStart = Math.max(0, Math.min(m.reached, 2));
  const returnEnd = m.returns.length ? Math.min(...m.returns.map((r) => r.undoes)) : 0;
  const train = trainPosition(m);
  // Un recorrido terminado sin compensaciones no necesita el espacio del ramal de retorno.
  const settled = Boolean(saga?.isTerminal) && !m.returning;

  return (
    <div
      className={`line-diagram${saga ? "" : " is-empty"}${settled ? " is-settled" : ""}`}
      role="img"
      aria-label={describe(m, saga)}
    >
      <svg className="line-svg" viewBox="0 0 100 320" preserveAspectRatio="none" aria-hidden="true">
        {/* Ramal de retorno fantasma: enseña que existe camino de vuelta */}
        <path
          className="track-ghost"
          d={`M ${XS[2]} ${Y_MAIN} V ${Y_RETURN} H ${XS[0]}`}
          vectorEffect="non-scaling-stroke"
        />
        <line className="track-base" x1={XS[0]} x2={XS[3]} y1={Y_MAIN} y2={Y_MAIN} vectorEffect="non-scaling-stroke" />
        {m.reached >= 0 && (
          <line
            className={`track-run${m.failedAt !== null ? " has-failure" : ""}`}
            x1={XS[0]}
            x2={XS[Math.max(0, m.reached)]}
            y1={Y_MAIN}
            y2={Y_MAIN}
            vectorEffect="non-scaling-stroke"
          />
        )}
        {m.returning && (
          <path
            className="track-return"
            pathLength={1}
            style={{ strokeDashoffset: 1 - m.returnProgress }}
            d={`M ${XS[returnStart]} ${Y_MAIN} V ${Y_RETURN} H ${XS[returnEnd]}`}
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>

      {m.stops.map((stop, i) => (
        <div key={stop.key} className={`stop stop-main stop-${i} is-${stop.state}${i === 3 ? " is-last" : ""}`} style={{ left: `${XS[i]}%`, top: Y_MAIN }}>
          <span className="stop-dot">
            {stop.state === "done" && <Check size={14} strokeWidth={3} />}
            {stop.state === "failed" && <X size={14} strokeWidth={3} />}
          </span>
          <span className="stop-name">{stop.label}</span>
          <span className="stop-service">{stop.service}</span>
          {stop.detail && (
            <span className="stop-detail" title={stop.detail}>
              {stop.errorCode ? <b>{stop.errorCode}</b> : null}
              {humanize(stop.detail)}
            </span>
          )}
        </div>
      ))}

      {saga && !settled && (
        <span className="return-label" style={{ left: `${XS[0]}%`, top: Y_RETURN - 34 }}>
          Ramal de retorno · compensaciones
        </span>
      )}

      {m.returns.map((r) => (
        <div key={r.key} className={`stop stop-return is-${r.state}`} style={{ left: `${XS[r.undoes]}%`, top: Y_RETURN }}>
          <span className="stop-dot">
            {r.state === "done" && <Check size={13} strokeWidth={3} />}
            {r.state === "failed" && <X size={13} strokeWidth={3} />}
          </span>
          <span className="stop-name">{r.label}</span>
          {r.detail && (
            <span className="stop-detail" title={r.detail}>
              {humanize(r.detail)}
            </span>
          )}
        </div>
      ))}

      {saga && train && (
        <span
          className={`train${train.onReturn ? " on-return" : ""}${m.failedAt !== null ? " is-failed" : ""}`}
          style={{ left: `${train.x}%`, top: train.y }}
          aria-hidden="true"
        >
          <TrainFront size={16} strokeWidth={2.25} />
        </span>
      )}

      {!saga && emptyHint && <p className="line-empty">{emptyHint}</p>}
    </div>
  );
}

function trainPosition(m: LineModel): { x: number; y: number; onReturn: boolean } | null {
  if (m.trainOnReturn !== null) {
    const r = m.returns[m.trainOnReturn];
    return { x: XS[r.undoes], y: Y_RETURN, onReturn: true };
  }
  if (m.reached < 0) return { x: XS[0], y: Y_MAIN, onReturn: false };
  return { x: XS[m.reached], y: Y_MAIN, onReturn: false };
}

function describe(m: LineModel, saga: Saga | null): string {
  if (!saga) return "Recorrido de la SAGA sin iniciar: Reserva, Cobro, Activación y Carga.";
  const main = m.stops.map((s) => `${s.label}: ${STATE_WORD[s.state]}`).join(", ");
  const ret = m.returns.length
    ? `. Compensaciones: ${m.returns.map((r) => `${r.label} ${RET_WORD[r.state]}`).join(", ")}`
    : "";
  return `Recorrido de la SAGA. ${main}${ret}.`;
}

const STATE_WORD = { pending: "pendiente", current: "en curso", done: "completada", failed: "falló" };
const RET_WORD = { pending: "pendiente", done: "ejecutada", failed: "falló" };
