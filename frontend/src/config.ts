export interface AegisConfig {
  environment: string;
  graphqlHttpUrl: string;
  graphqlWsUrl?: string;
  /** Endpoints GraphQL de los otros ambientes, solo para comparar feature flags. */
  peers?: Record<string, string>;
}

declare global {
  interface Window {
    __AEGIS_CONFIG__?: AegisConfig;
  }
}

const fallback: AegisConfig = {
  environment: "dev",
  graphqlHttpUrl: "http://localhost:8080/graphql",
};

function wsFromHttp(url: string): string {
  return url.replace(/^http/, "ws");
}

const raw = window.__AEGIS_CONFIG__ ?? fallback;

export const config: Required<AegisConfig> = {
  environment: raw.environment,
  graphqlHttpUrl: raw.graphqlHttpUrl,
  graphqlWsUrl: raw.graphqlWsUrl ?? wsFromHttp(raw.graphqlHttpUrl),
  peers: raw.peers ?? {},
};

export const ENVIRONMENTS = ["dev", "test", "prod"] as const;

/** Cada ambiente es una "línea" con su color, como en un plano de metro. */
export const LINE: Record<string, { color: string; letter: string; label: string }> = {
  dev: { color: "#0072CE", letter: "D", label: "Desarrollo" },
  test: { color: "#7A4FBF", letter: "T", label: "Pruebas" },
  prod: { color: "#00838F", letter: "P", label: "Producción" },
};

export function lineOf(env: string) {
  return LINE[env] ?? { color: "#596080", letter: env.slice(0, 1).toUpperCase(), label: env };
}
