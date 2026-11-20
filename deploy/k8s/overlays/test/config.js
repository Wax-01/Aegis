// Configuración de runtime del frontend para el ambiente test (montada por ConfigMap).
window.__AEGIS_CONFIG__ = {
  environment: "test",
  graphqlHttpUrl: "http://localhost:30081/graphql",
  graphqlWsUrl: "ws://localhost:30081/graphql",
};
