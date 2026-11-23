# AegisVolt

Plataforma cloud-native de gestión de carga para flotas eléctricas y electrolineras B2B en Latinoamérica.
Proyecto final — Patrones Arquitectónicos Avanzados.

```
 Frontend React ──HTTPS/WSS──► API Gateway (REST, PRIVATE vía VPCE execute-api)
                                   │ VPC Link → NLB interno → NodePort
                                   ▼
        ┌──────────────── Kubernetes (EKS · kind en local) — namespace aegisvolt-<env> ────────────────┐
        │  graphql-gateway  (Strawberry GraphQL + ORQUESTADOR SAGA + reconciliador)                     │
        │     │ X-Correlation-ID = saga_id                                                               │
        │     ├──► station-reservation-service ──► aegisvolt-reservations-<env>                         │
        │     ├──► billing-wallet-service      ──► aegisvolt-billing-<env>                              │
        │     └──► energy-dispatch-service     ──► aegisvolt-dispatch-<env>   (+ simulador telemetría)  │
        │  (stable + canary por servicio)          aegisvolt-sagas-<env> · aegisvolt-feature-flags-<env>│
        └───────────────────────────────────────────────────────────────────────────────────────────────┘
              logs JSON ──► CloudWatch /aegisvolt/<env>/<servicio>  ◄── Prefect (salud + auditoría SAGA)
```

## Estructura

| Ruta | Contenido |
|---|---|
| `services/common` | Librería compartida: config por ambiente, logs JSON → CloudWatch, `correlation_id`, feature flags, helpers DynamoDB |
| `services/station-reservation` | Paso 1 SAGA (bloqueo de conector) + compensación `release` |
| `services/billing-wallet` | Paso 2 SAGA (cobro, surge pricing) + compensación `refund` |
| `services/energy-dispatch` | Paso 3 SAGA (activación física, inyección de fallos) + telemetría |
| `services/graphql-gateway` | Esquema GraphQL unificado (`schema.graphql`), orquestador SAGA, subscriptions |
| `frontend` | Consola React + Vite: estaciones en vivo, SAGA dibujada como línea de metro (paradas + ramal de retorno de compensaciones), comparador de flags por ambiente, historial con pasos y movimientos de billetera |
| `infra/bootstrap` | Bucket S3 del tfstate **con versioning** + tabla de locks |
| `infra/live` | Stack por **workspace** (`dev`/`test`/`prod`): VPC, subredes, VPCE, NLB, API Gateway, DynamoDB, flags, CloudWatch, namespace K8s |
| `infra/modules/*` | `network`, `dynamodb`, `feature_flags`, `observability`, `edge`, `eks`, `k8s_env` |
| `deploy/kind`, `deploy/floci` | Clúster local y emulador AWS persistente |
| `deploy/k8s` | Kustomize: base (stable + canary por servicio) y overlays por ambiente |
| `scripts/deploy/canary.py` | Canary 20 % → análisis CloudWatch → promote / rollback automático |
| `.github/workflows` | `pr-checks.yml` (pre-merge) y `deploy.yml` (post-merge por rama destino) |
| `.github/rulesets` | Protección de `dev`/`test`/`prod` (sin force push, sin push directo, checks obligatorios) |
| `observability/prefect` | Flujos de salud, auditoría de consistencia SAGA y traza de `correlation_id` |

## Requisitos

Docker Desktop, Python 3.12+, Node 22, kubectl, y además:

```powershell
# Terraform, kind y gh: si no tienes winget, descarga el binario oficial y agrégalo al PATH de usuario
# (Terraform se instaló así en %LOCALAPPDATA%\Programs\terraform, verificando el SHA256 publicado).
python -m venv .venv; .\.venv\Scripts\pip install -r requirements-dev.txt
```

## Modo rápido (un ambiente, sin Terraform) — desarrollo y CI

```powershell
docker compose up -d --build                       # Floci + bootstrap + 4 servicios
.\.venv\Scripts\python -m pytest tests             # integración + e2e (12 pruebas)
# GraphiQL: http://localhost:8080/graphql

cd frontend; npm install; npm run dev               # consola en http://localhost:5173 (usa public/config.js)
```

El frontend lee `/config.js` en runtime (`environment`, `graphqlHttpUrl`, `graphqlWsUrl`, `peers`): la misma
imagen se promueve dev → test → prod y cada overlay de Kustomize monta su propio `config.js`. El gateway
acepta WebSocket solo desde los orígenes de `CORS_ORIGINS` (Terraform los fija a los 3 frontends).

## Modo plataforma (3 ambientes, la demo de la sustentación)

```powershell
.\.venv\Scripts\python scripts\platform_up.py      # kind + Floci + Terraform x3 workspaces + deploy x3
```

| Ambiente | GraphQL | Frontend |
|---|---|---|
| dev | http://localhost:30080/graphql | http://localhost:30090 |
| test | http://localhost:30081/graphql | http://localhost:30091 |
| prod | http://localhost:30082/graphql | http://localhost:30092 |

Comandos de demo frecuentes:

```powershell
python scripts\flag.py test SIMULATE_CHARGER_HARDWARE_FAULT on     # inyectar fallo (sin redesplegar)
python scripts\tfstate_versions.py list --workspace dev             # versiones del tfstate en S3
python scripts\deploy\canary.py deploy --env dev --inject-canary-error-rate 0.6   # rollback automático
python scripts\deploy\canary.py status --env dev
```

## Pruebas

| Tipo | Dónde | Cómo |
|---|---|---|
| Unitarias (41) | `services/*/tests` | `cd services/<svc>; python -m pytest tests` (moto + dobles del orquestador) |
| Integración (8) | `tests/integration` | contra Floci + GraphQL reales |
| E2E (4) | `tests/e2e` | SAGA feliz, fondos insuficientes, falla física + rollback, idempotencia |
| E2E frontend (5) | `frontend/e2e` | Playwright contra el mismo stack: estaciones en vivo, SAGA feliz, falla física con ramal de retorno, historial, flags (`npm run test:e2e`) |

## CI/CD

1. Crea el repo en GitHub (público, o privado con GitHub Pro/Student Pack para que apliquen los rulesets).
2. Registra un **runner self-hosted** en esta máquina con la etiqueta `aegisvolt`
   (Settings → Actions → Runners). Ejecuta `terraform plan/apply` y el canary porque el estado y el clúster
   viven aquí. Los jobs self-hosted solo corren para PRs del mismo repo (nunca forks).
3. `bash scripts/github/setup_repo.sh` → crea `dev`/`test`/`prod`, el ruleset y los GitHub Environments.

Flujo: `feature/*` → PR → `dev` → PR → `test` → PR → `prod`.

## Emulador vs AWS real

Todo se declara para AWS real (`infra/live/aws.tfvars.example`). En Floci se ajusta con `floci.tfvars`:

| Elemento | AWS real | Floci |
|---|---|---|
| API Gateway | `PRIVATE` + resource policy `aws:SourceVpce` | `REGIONAL` (Floci no documenta APIs privadas) |
| Integración | VPC Link → NLB interno | HTTP directo al NodePort del clúster |
| PrivateLink a K8s | `aws_vpc_endpoint_service` sobre el NLB | desactivado: `CreateVpcEndpointServiceConfiguration` no soportado |
| Kubernetes | módulo `eks` | kind (namespace por ambiente) |
| Security groups / rutas | aplicados | se crean, pero Floci no los hace cumplir (metadata) |
| Credenciales de pods | IRSA | Secret `aegisvolt-app` (test/test) |
