// Configuración de runtime del frontend para el ambiente prod (montada por ConfigMap).
window.__AEGIS_CONFIG__ = {
  environment: "prod",
  graphqlHttpUrl: "http://localhost:30082/graphql",
  graphqlWsUrl: "ws://localhost:30082/graphql",
  // Otros ambientes: solo lectura, para el comparador de feature flags.
  peers: { dev: "http://localhost:30080/graphql", test: "http://localhost:30081/graphql" },
};
