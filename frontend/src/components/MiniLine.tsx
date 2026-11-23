import { buildModel } from "../saga-model";
import type { Saga } from "../types";

const XS = [6, 30, 54, 78];

/** Miniatura del recorrido para filas del historial: misma gramática que el diagrama grande. */
export function MiniLine({ saga }: { saga: Saga }) {
  const m = buildModel(saga);
  const start = Math.max(0, Math.min(m.reached, 2));
  const end = m.returns.length ? Math.min(...m.returns.map((r) => r.undoes)) : 0;
  return (
    <svg className="mini-line" viewBox="0 0 84 26" width="84" height="26" aria-hidden="true">
      <line x1={XS[0]} x2={XS[3]} y1={8} y2={8} className="mini-base" />
      {m.reached >= 0 && <line x1={XS[0]} x2={XS[m.reached]} y1={8} y2={8} className="mini-run" />}
      {m.returning && (
        <path d={`M ${XS[start]} 8 V 20 H ${XS[end]}`} className="mini-return" pathLength={1}
          style={{ strokeDashoffset: 1 - m.returnProgress }} />
      )}
      {m.stops.map((s, i) => (
        <circle key={s.key} cx={XS[i]} cy={8} r={3.6} className={`mini-dot is-${s.state}`} />
      ))}
      {m.returns.map((r) => (
        <circle key={r.key} cx={XS[r.undoes]} cy={20} r={3} className={`mini-dot ret is-${r.state}`} />
      ))}
    </svg>
  );
}
