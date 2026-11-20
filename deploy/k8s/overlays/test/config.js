// Configuración de runtime del frontend para el ambiente test (montada por ConfigMap).
window.__AEGIS_CONFIG__ = {
  environment: "test",
  graphqlHttpUrl: "http://localhost:30081/graphql",
  graphqlWsUrl: "ws://localhost:30081/graphql",
  // Otros ambientes: solo lectura, para el comparador de feature flags.
  peers: { dev: "http://localhost:30080/graphql", prod: "http://localhost:30082/graphql" },
};
