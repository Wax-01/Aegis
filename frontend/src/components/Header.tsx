import { config, lineOf } from "../config";
import { useConnected } from "../hooks";

export type Tab = "operacion" | "transacciones" | "flags" | "salud";

const TABS: { id: Tab; label: string }[] = [
  { id: "operacion", label: "Operación" },
  { id: "transacciones", label: "Transacciones" },
  { id: "flags", label: "Feature flags" },
  { id: "salud", label: "Salud" },
];

export function Roundel({ env, size = 36 }: { env: string; size?: number }) {
  const line = lineOf(env);
  return (
    <span className="roundel" style={{ background: line.color, width: size, height: size, fontSize: size * 0.44 }}>
      {line.letter}
    </span>
  );
}

export function Header({ tab, onTab }: { tab: Tab; onTab: (t: Tab) => void }) {
  const connected = useConnected();
  const env = config.environment;
  return (
    <header className="shell-header">
      <div className="brand">
        <Roundel env={env} />
        <div className="brand-text">
          <strong>AegisVolt</strong>
          <span>
            Línea {env} · {lineOf(env).label}
          </span>
        </div>
      </div>
      <nav className="tabs" aria-label="Secciones">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className="tab"
            aria-current={tab === t.id ? "page" : undefined}
            onClick={() => onTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <span className={`live${connected ? " is-on" : ""}`} role="status">
        <span className="live-dot" aria-hidden="true" />
        {connected ? "En vivo" : "Reconectando…"}
      </span>
    </header>
  );
}
