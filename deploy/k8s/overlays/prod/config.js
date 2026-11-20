// Configuración de runtime del frontend para el ambiente prod (montada por ConfigMap).
window.__AEGIS_CONFIG__ = {
  environment: "prod",
  graphqlHttpUrl: "http://localhost:30082/graphql",
  graphqlWsUrl: "ws://localhost:30082/graphql",
};
