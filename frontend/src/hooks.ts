import { useCallback, useEffect, useRef, useState } from "react";
import { gql, onConnectionChange, ws } from "./api";

/** Suscripción GraphQL (graphql-transport-ws). Reabre si cambian las variables. */
export function useSubscription<T>(
  query: string,
  variables: Record<string, unknown> | null,
): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = variables === null ? null : JSON.stringify(variables);

  useEffect(() => {
    if (key === null) {
      setData(null);
      return;
    }
    setError(null);
    const dispose = ws().subscribe<T>(
      { query, variables: JSON.parse(key) },
      {
        next: (msg) => {
          if (msg.errors?.length) setError(msg.errors.map((e) => e.message).join(" · "));
          else if (msg.data) {
            setError(null);
            setData(msg.data as T);
          }
        },
        error: () => setError("Se perdió la suscripción en vivo; reintentando…"),
        complete: () => undefined,
      },
    );
    return () => dispose();
  }, [query, key]);

  return { data, error };
}

/** Consulta GraphQL con refresco opcional cada `intervalMs`. */
export function useQuery<T>(
  query: string,
  variables: Record<string, unknown> | null,
  opts: { intervalMs?: number; url?: string } = {},
): { data: T | null; error: string | null; loading: boolean; refetch: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(variables !== null);
  const [tick, setTick] = useState(0);
  const key = variables === null ? null : JSON.stringify(variables);
  const { intervalMs, url } = opts;

  useEffect(() => {
    if (key === null) {
      setData(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = () => {
      gql<T>(query, JSON.parse(key), { url, signal: controller.signal })
        .then((d) => {
          setData(d);
          setError(null);
        })
        .catch((e: Error) => {
          if (e.name !== "AbortError") setError(e.message);
        })
        .finally(() => {
          if (controller.signal.aborted) return;
          setLoading(false);
          if (intervalMs) timer = setTimeout(run, intervalMs);
        });
    };
    setLoading(true);
    run();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [query, key, intervalMs, url, tick]);

  const refetch = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, refetch };
}

export function useConnected(): boolean {
  const [connected, setConnected] = useState(false);
  useEffect(() => onConnectionChange(setConnected), []);
  return connected;
}

/** Ejecuta una mutación y expone su estado. */
export function useMutation<T, A extends unknown[]>(fn: (...args: A) => Promise<T>) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const run = useCallback(async (...args: A): Promise<T | null> => {
    setPending(true);
    setError(null);
    try {
      return await fnRef.current(...args);
    } catch (e) {
      setError((e as Error).message);
      return null;
    } finally {
      setPending(false);
    }
  }, []);
  return { run, pending, error, clearError: () => setError(null) };
}
