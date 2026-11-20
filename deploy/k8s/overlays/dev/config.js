// Configuración de runtime del frontend para el ambiente dev (montada por ConfigMap).
window.__AEGIS_CONFIG__ = {
  environment: "dev",
  graphqlHttpUrl: "http://localhost:30080/graphql",
  graphqlWsUrl: "ws://localhost:30080/graphql",
};
