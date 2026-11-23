import { useEffect, useState } from "react";
import { FLAGS_LIVE, SAGA_LIVE, SAGAS_LIVE, STATIONS_LIVE, WALLETS_QUERY } from "./api";
import { config, lineOf } from "./config";
import { FlagsView } from "./components/FlagsView";
import { Header, type Tab } from "./components/Header";
import { HealthView } from "./components/HealthView";
import { OperationView, type Selection } from "./components/OperationView";
import { StationsRail } from "./components/StationsRail";
import { TransactionsView } from "./components/TransactionsView";
import { useQuery, useSubscription } from "./hooks";
import type { FeatureFlag, Saga, Station, Wallet } from "./types";

const TAB_KEY = "aegisvolt.tab";

function initialTab(): Tab {
  try {
    const t = localStorage.getItem(TAB_KEY);
    if (t === "operacion" || t === "transacciones" || t === "flags" || t === "salud") return t;
  } catch {
    /* sin almacenamiento */
  }
  return "operacion";
}

export function App() {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  const stations = useSubscription<{ stationsLive: Station[] }>(STATIONS_LIVE, {});
  const sagas = useSubscription<{ sagasLive: Saga[] }>(SAGAS_LIVE, { limit: 30 });
  const flags = useSubscription<{ featureFlagsLive: FeatureFlag[] }>(FLAGS_LIVE, {});
  const live = useSubscription<{ sagaLive: Saga }>(SAGA_LIVE, activeId ? { id: activeId } : null);
  const wallets = useQuery<{ wallets: Wallet[] }>(WALLETS_QUERY, {}, { intervalMs: 5000 });

  useEffect(() => {
    try {
      localStorage.setItem(TAB_KEY, tab);
    } catch {
      /* sin almacenamiento */
    }
  }, [tab]);

  useEffect(() => {
    document.documentElement.style.setProperty("--line", lineOf(config.environment).color);
    document.title = `AegisVolt · ${config.environment}`;
  }, []);

  const sagaList = sagas.data?.sagasLive ?? null;
  const fromList = sagaList?.find((s) => s.id === activeId) ?? null;
  const liveSaga = live.data?.sagaLive?.id === activeId ? live.data.sagaLive : null;
  // La subscription sagaLive termina al llegar a estado terminal: la lista en vivo puede ser más nueva.
  const activeSaga = newest(liveSaga, fromList);

  return (
    <div className="shell">
      <a className="skip" href="#contenido">
        Saltar al contenido
      </a>
      <Header tab={tab} onTab={setTab} />
      {tab === "operacion" && (
        <div className="layout-rail">
          <StationsRail
            stations={stations.data?.stationsLive ?? null}
            error={stations.error}
            selected={selection?.connectorId ?? null}
            onSelect={(s, c) => setSelection({ stationId: s.id, connectorId: c.id })}
          />
          <OperationView
            stations={stations.data?.stationsLive ?? null}
            sagas={sagaList}
            wallets={wallets.data?.wallets ?? null}
            flags={flags.data?.featureFlagsLive ?? null}
            selection={selection}
            onSelection={setSelection}
            activeSaga={activeSaga}
            onActivate={setActiveId}
            onWalletsChanged={wallets.refetch}
          />
        </div>
      )}
      {tab === "transacciones" && (
        <TransactionsView sagas={sagaList} error={sagas.error} selectedId={detailId} onSelect={setDetailId} />
      )}
      {tab === "flags" && <FlagsView flags={flags.data?.featureFlagsLive ?? null} error={flags.error} />}
      {tab === "salud" && <HealthView wallets={wallets.data?.wallets ?? null} onWalletsChanged={wallets.refetch} />}
    </div>
  );
}

function newest(a: Saga | null, b: Saga | null): Saga | null {
  if (!a) return b;
  if (!b) return a;
  return a.updatedAt >= b.updatedAt && a.steps.length >= b.steps.length ? a : b;
}
