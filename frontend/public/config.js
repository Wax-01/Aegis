// Configuración de runtime para desarrollo local (docker compose, gateway en :8080).
// En Kubernetes este archivo lo reemplaza el ConfigMap `frontend-config` de cada overlay.
window.__AEGIS_CONFIG__ = {
  environment: "dev",
  graphqlHttpUrl: "http://localhost:8080/graphql",
  graphqlWsUrl: "ws://localhost:8080/graphql",
  // Otros ambientes para el comparador de feature flags (solo lectura).
  peers: {},
};
