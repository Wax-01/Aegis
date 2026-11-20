import { CONNECTOR_STATUS, num } from "../format";
import type { Connector, Station } from "../types";

interface Props {
  stations: Station[] | null;
  error: string | null;
  selected: string | null;
  onSelect: (station: Station, connector: Connector) => void;
}

/** Estaciones y conectores en tiempo real (subscription stationsLive). */
export function StationsRail({ stations: raw, error, selected, onSelect }: Props) {
  // Las estaciones con un conector en falla van primero: es el estado que el operador debe ver sin desplazarse.
  const stations = raw
    ? [...raw].sort((a, b) => Number(hasFault(b)) - Number(hasFault(a)) || a.id.localeCompare(b.id))
    : null;
  return (
    <aside className="rail" aria-labelledby="rail-title">
      <div className="rail-head">
        <h2 id="rail-title">Estaciones</h2>
        {stations && (
          <span className="muted">
            {stations.reduce((a, s) => a + s.availableConnectors, 0)} de{" "}
            {stations.reduce((a, s) => a + s.totalConnectors, 0)} libres
          </span>
        )}
      </div>
      <dl className="legend" aria-label="Leyenda">
        {(["AVAILABLE", "RESERVED", "CHARGING", "FAULTED"] as const).map((st) => (
          <div key={st}>
            <dt className={`c-dot is-${st.toLowerCase()}`} />
            <dd>{CONNECTOR_STATUS[st]}</dd>
          </div>
        ))}
      </dl>
      {error && <p className="inline-error">{error}</p>}
      {!stations && !error && <RailSkeleton />}
      <ul className="station-list">
        {stations?.map((s) => (
          <li key={s.id} className="station">
            <div className="station-head">
              <span className="station-name">{s.name}</span>
              <span className="station-code">{s.id}</span>
            </div>
            <span className="station-city">
              {s.city}, {s.country}
            </span>
            <div className="connectors">
              {s.connectors.map((c) => (
                <ConnectorChip
                  key={c.id}
                  connector={c}
                  selected={selected === c.id}
                  onClick={() => onSelect(s, c)}
                />
              ))}
            </div>
          </li>
        ))}
      </ul>
    </aside>
  );
}

function hasFault(s: Station): boolean {
  return s.connectors.some((c) => c.status === "FAULTED");
}

function ConnectorChip({ connector: c, selected, onClick }: { connector: Connector; selected: boolean; onClick: () => void }) {
  const free = c.status === "AVAILABLE";
  const label = c.id.split("-").at(-1);
  const live = c.liveSession;
  return (
    <button
      type="button"
      className={`connector is-${c.status.toLowerCase()}${selected ? " is-selected" : ""}`}
      onClick={onClick}
      disabled={!free}
      aria-pressed={selected}
      title={`${c.id} · ${c.tier} ${c.powerKw} kW · ${CONNECTOR_STATUS[c.status] ?? c.status}`}
    >
      <span className={`c-dot is-${c.status.toLowerCase()}`} aria-hidden="true" />
      <span className="c-id">{label}</span>
      <span className="c-kw">
        {live ? `${num(live.powerKw, 0)} kW · ${num(live.soc, 0)} %` : `${c.tier.slice(0, 1)}${c.tier.slice(1).toLowerCase()} ${c.powerKw}`}
      </span>
      <span className="sr-only">{CONNECTOR_STATUS[c.status] ?? c.status}</span>
    </button>
  );
}

function RailSkeleton() {
  return (
    <ul className="station-list" aria-hidden="true">
      {[0, 1, 2, 3].map((i) => (
        <li key={i} className="station skeleton">
          <span className="sk sk-title" />
          <span className="sk sk-line" />
          <div className="connectors">
            <span className="sk sk-chip" />
            <span className="sk sk-chip" />
            <span className="sk sk-chip" />
          </div>
        </li>
      ))}
    </ul>
  );
}
