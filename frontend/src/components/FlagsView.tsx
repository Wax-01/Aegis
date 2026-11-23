import { KeyRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { FLAGS_QUERY, getAdminToken, gql, SET_FLAG, setAdminToken } from "../api";
import { config, ENVIRONMENTS, lineOf } from "../config";
import { dateTime, FLAG_LABEL } from "../format";
import { useMutation, useQuery } from "../hooks";
import type { FeatureFlag } from "../types";
import { Roundel } from "./Header";

const FLAG_ORDER = ["ENABLE_DYNAMIC_SURGE_PRICING", "ENABLE_FAST_CHARGE_BOOST", "SIMULATE_CHARGER_HARDWARE_FAULT"];

/** Política esperada por ambiente según el enunciado (null = libre). */
const POLICY: Record<string, Record<string, boolean> | null> = {
  ENABLE_DYNAMIC_SURGE_PRICING: { dev: true, test: true, prod: false },
  ENABLE_FAST_CHARGE_BOOST: null,
  SIMULATE_CHARGER_HARDWARE_FAULT: { prod: false },
};

interface Props {
  flags: FeatureFlag[] | null;
  error: string | null;
}

export function FlagsView({ flags, error }: Props) {
  const current = config.environment;
  // Una consulta por ambiente (los hooks no cambian de número: ENVIRONMENTS es fijo).
  const peerDev = usePeer("dev");
  const peerTest = usePeer("test");
  const peerProd = usePeer("prod");
  const peers: Record<string, PeerState> = { dev: peerDev, test: peerTest, prod: peerProd };

  const [askToken, setAskToken] = useState<{ key: string; enabled: boolean } | null>(null);
  const toggle = useMutation((key: string, enabled: boolean) =>
    gql<{ setFeatureFlag: FeatureFlag }>(SET_FLAG, { key, enabled }, { admin: true }),
  );

  const flip = async (key: string, enabled: boolean) => {
    if (!getAdminToken()) {
      setAskToken({ key, enabled });
      return;
    }
    const res = await toggle.run(key, enabled);
    if (!res && /token/i.test(toggle.error ?? "")) setAskToken({ key, enabled });
  };

  const valueOf = (env: string, key: string): boolean | undefined => {
    const list = env === current ? flags : peers[env].flags;
    return list?.find((f) => f.key === key)?.enabled;
  };

  const keys = [...FLAG_ORDER, ...(flags ?? []).map((f) => f.key).filter((k) => !FLAG_ORDER.includes(k))];

  return (
    <main className="work" id="contenido">
      <div className="section-head">
        <h1>Feature flags por ambiente</h1>
        <span className="muted">
          Cada línea lee su propia tabla <code>aegisvolt-feature-flags-&lt;env&gt;</code>. Cambiar una no toca las otras.
        </span>
      </div>

      {askToken && (
        <TokenForm
          onCancel={() => setAskToken(null)}
          onSave={async (token) => {
            setAdminToken(token);
            const pending = askToken;
            setAskToken(null);
            await toggle.run(pending.key, pending.enabled);
          }}
        />
      )}
      {toggle.error && !askToken && <p className="inline-error">{toggle.error}</p>}
      {error && <p className="inline-error">{error}</p>}

      <div className="table-wrap">
        <table className="flag-matrix">
          <thead>
            <tr>
              <th scope="col">Flag</th>
              {ENVIRONMENTS.map((env) => (
                <th key={env} scope="col" className={env === current ? "is-current" : undefined}>
                  <span className="env-head">
                    <Roundel env={env} size={26} />
                    <span>
                      {env}
                      <small>{env === current ? "esta consola · en vivo" : peers[env].note}</small>
                    </span>
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => {
              const flag = flags?.find((f) => f.key === key);
              const policy = POLICY[key];
              return (
                <tr key={key}>
                  <th scope="row">
                    <span className="flag-name">{FLAG_LABEL[key] ?? key}</span>
                    <code className="flag-key">{key}</code>
                    {flag?.description && <span className="flag-desc">{flag.description}</span>}
                  </th>
                  {ENVIRONMENTS.map((env) => {
                    const v = valueOf(env, key);
                    const expected = policy?.[env];
                    const off = expected !== undefined && v !== undefined && v !== expected;
                    return (
                      <td key={env} className={env === current ? "is-current" : undefined}>
                        {env === current && flag ? (
                          <button
                            type="button"
                            role="switch"
                            aria-checked={flag.enabled}
                            aria-label={`${FLAG_LABEL[key] ?? key} en ${env}`}
                            className="switch"
                            disabled={toggle.pending}
                            onClick={() => flip(key, !flag.enabled)}
                            style={{ ["--line" as string]: lineOf(env).color }}
                          >
                            <span className="switch-knob" />
                            <span className="switch-text">{flag.enabled ? "ON" : "OFF"}</span>
                          </button>
                        ) : v === undefined ? (
                          expected !== undefined ? (
                            <span className="expected">
                              <span className={`pill-state ghost ${expected ? "on" : "off"}`}>{expected ? "ON" : "OFF"}</span>
                              <small>política esperada · sin conexión</small>
                            </span>
                          ) : (
                            <span className="muted">libre por ambiente · sin conexión</span>
                          )
                        ) : (
                          <span className={`pill-state ${v ? "on" : "off"}`}>{v ? "ON" : "OFF"}</span>
                        )}
                        {off && <span className="policy-off">Distinto a la política ({expected ? "ON" : "OFF"})</span>}
                        {env === current && flag?.updatedBy && (
                          <span className="flag-audit">
                            {flag.updatedBy} · {dateTime(flag.updatedAt)}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted note">
        Los servicios releen las flags cada ~3 s: el cambio aplica sin redesplegar. Política del enunciado: tarifa
        dinámica activa en dev y test, apagada en prod.
      </p>
    </main>
  );
}

interface PeerState {
  flags: FeatureFlag[] | null;
  note: string;
}

function usePeer(env: string): PeerState {
  const url = config.peers[env];
  const isPeer = env !== config.environment && Boolean(url);
  const q = useQuery<{ featureFlags: FeatureFlag[] }>(FLAGS_QUERY, isPeer ? {} : null, { url, intervalMs: 5000 });
  if (env === config.environment) return { flags: null, note: "" };
  if (!url) return { flags: null, note: "sin endpoint configurado" };
  if (q.error) return { flags: null, note: "sin conexión" };
  return { flags: q.data?.featureFlags ?? null, note: "solo lectura · cada 5 s" };
}

function TokenForm({ onSave, onCancel }: { onSave: (t: string) => void; onCancel: () => void }) {
  const [token, setToken] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (token.trim()) onSave(token.trim());
  };
  return (
    <form className="token-form" onSubmit={submit}>
      <KeyRound size={18} aria-hidden="true" />
      <label className="field">
        <span>Token de administrador</span>
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          autoFocus
          autoComplete="off"
          placeholder="ADMIN_TOKEN del Secret aegisvolt-app"
        />
      </label>
      <button type="submit" className="btn btn-primary">
        Guardar y aplicar
      </button>
      <button type="button" className="btn-link" onClick={onCancel}>
        Cancelar
      </button>
    </form>
  );
}
