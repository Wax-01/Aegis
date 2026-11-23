import { Plus } from "lucide-react";
import { gql, HEALTH_QUERY, TOP_UP } from "../api";
import { money, num } from "../format";
import { useMutation, useQuery } from "../hooks";
import type { EnvironmentInfo, ServiceHealth, Wallet } from "../types";

interface Props {
  wallets: Wallet[] | null;
  onWalletsChanged: () => void;
}

export function HealthView({ wallets, onWalletsChanged }: Props) {
  const q = useQuery<{ serviceHealth: ServiceHealth[]; environment: EnvironmentInfo }>(HEALTH_QUERY, {}, {
    intervalMs: 5000,
  });
  const topUp = useMutation((id: string) => gql(TOP_UP, { id, amount: 100 }));
  const env = q.data?.environment;

  return (
    <main className="work work-split" id="contenido">
      <section aria-labelledby="svc-title">
        <div className="section-head">
          <h1 id="svc-title">Salud de servicios</h1>
          <span className="muted">Consulta cada 5 s vía gateway</span>
        </div>
        {q.error && <p className="inline-error">{q.error}</p>}
        <ul className="services svc-line">
          {(q.data?.serviceHealth ?? []).map((s) => {
            const ok = s.status === "ok" || s.status === "UP" || s.status === "healthy";
            return (
              <li key={s.name} className={ok ? "is-ok" : "is-bad"}>
                <span className="svc-dot" aria-hidden="true" />
                <span className="svc-name">{s.name}</span>
                <span className="svc-meta">
                  {s.version ?? "—"} · {s.track ?? "—"}
                </span>
                <span className="svc-lat">{s.latencyMs !== null ? `${num(s.latencyMs, 0)} ms` : "—"}</span>
                {s.error && <span className="svc-error">{s.error}</span>}
              </li>
            );
          })}
          {!q.data && !q.error && <li className="muted">Consultando…</li>}
        </ul>

        <div className="section-head spaced">
          <h2>Billeteras de flota</h2>
          <span className="muted">Datos de demostración</span>
        </div>
        {topUp.error && <p className="inline-error">{topUp.error}</p>}
        <ul className="wallets">
          {wallets?.map((w) => (
            <li key={w.fleetId}>
              <span className="w-name">
                {w.name}
                <code>{w.fleetId}</code>
              </span>
              <span className={`w-balance${w.balance < 20 ? " is-low" : ""}`}>{money(w.balance, w.currency)}</span>
              <button
                type="button"
                className="btn btn-quiet"
                disabled={topUp.pending}
                onClick={async () => {
                  await topUp.run(w.fleetId);
                  onWalletsChanged();
                }}
              >
                <Plus size={14} aria-hidden="true" />
                Recargar 100
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="detail" aria-labelledby="env-title">
        <h2 id="env-title">Ambiente</h2>
        {env ? (
          <dl className="facts facts-col">
            <div>
              <dt>Nombre</dt>
              <dd>{env.name}</dd>
            </div>
            <div>
              <dt>Versión · track</dt>
              <dd>
                {env.version} · {env.track}
              </dd>
            </div>
            <div>
              <dt>Instancia</dt>
              <dd className="serial">{env.instance}</dd>
            </div>
            <div>
              <dt>Región · backend AWS</dt>
              <dd>
                {env.region} · {env.awsBackend}
              </dd>
            </div>
            <div>
              <dt>Logs CloudWatch</dt>
              <dd>
                <code>{env.logGroupPrefix}</code>
              </dd>
            </div>
            <div>
              <dt>Tablas DynamoDB</dt>
              <dd>
                <ul className="tables">
                  {env.tables.map((t) => (
                    <li key={t}>
                      <code>{t}</code>
                    </li>
                  ))}
                </ul>
              </dd>
            </div>
          </dl>
        ) : (
          <p className="muted">Consultando…</p>
        )}
      </section>
    </main>
  );
}
