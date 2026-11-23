// Configuración de runtime del frontend para el ambiente dev (montada por ConfigMap).
window.__AEGIS_CONFIG__ = {
  environment: "dev",
  graphqlHttpUrl: "http://localhost:30080/graphql",
  graphqlWsUrl: "ws://localhost:30080/graphql",
  // Otros ambientes: solo lectura, para el comparador de feature flags.
  peers: { test: "http://localhost:30081/graphql", prod: "http://localhost:30082/graphql" },
};
