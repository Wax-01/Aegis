# Guía de sustentación — AegisVolt

Cada respuesta indica **dónde está en el código** y **qué ejecutar** para demostrarlo en vivo.
Antes de entrar: `python scripts/platform_up.py` (deja los 3 ambientes arriba) y `prefect server start`.

---

## 1. Infraestructura como Código — 30 %

### ¿Cómo garantiza que un `apply` en `test` no sobrescriba las tablas ni el estado de `prod`?

Hay tres capas de aislamiento:

1. **Estado separado por workspace.** El backend S3 guarda cada workspace en una llave distinta:
   `env:/test/aegisvolt/terraform.tfstate` frente a `env:/prod/...` (`infra/live/versions.tf`, `workspace_key_prefix`).
   Un apply en `test` ni siquiera lee el estado de prod.
2. **Nombres derivados del workspace.** `local.env = terraform.workspace` (`infra/live/locals.tf`) y todos los
   recursos se llaman `aegisvolt-<logical>-${local.env}`. Las tablas de test son *otros recursos*.
3. **Guardia de workspace.** En `default` (o cualquier otro) el plan falla antes de crear nada (`file("ERROR: …")`
   en `locals.tf`). Además, `prod` tiene `deletion_protection_enabled` + PITR.
4. **Lock**: `use_lockfile = true` crea `…terraform.tfstate.tflock` con escritura condicional en S3. Dos applies sobre
   el mismo workspace no pueden correr a la vez.

```powershell
cd infra/live
terraform workspace select test; terraform plan -var-file=floci.tfvars   # solo recursos *-test
terraform workspace select default; terraform plan -var-file=floci.tfvars  # falla: workspace no permitido
```

### Muestre las versiones anteriores del `terraform.tfstate` de `dev` y cómo restauraría la previa

El bucket tiene `aws_s3_bucket_versioning` en `Enabled` (`infra/bootstrap/main.tf`). Cada `apply` crea una versión
nueva y la anterior queda como no-actual. La retención es de 90 días o 50 versiones.

```powershell
python scripts/tfstate_versions.py list --workspace dev
python scripts/tfstate_versions.py show --workspace dev --version-id <id>
python scripts/tfstate_versions.py restore --workspace dev --version-id <id>   # CopyObject => nueva "latest"
terraform workspace select dev; terraform plan -var-file=floci.tfvars          # ver el drift tras restaurar
```

Alternativa nativa: `download … --out prev.tfstate`, luego `terraform state push -force prev.tfstate`. Hace falta
`-force` porque el *serial* es menor. Antes de restaurar hay que confirmar que no hay un lock activo. La versión corrupta
**no se pierde**: sigue como no-actual (auditoría).

### Recorrido de un paquete: API Gateway → pod, a través del VPCE

1. El cliente, dentro de la VPC, resuelve `<api-id>.execute-api.us-east-1.amazonaws.com`. Con `private_dns_enabled`,
   el nombre apunta a las **ENIs del Interface VPCE `execute-api`** en las subredes privadas (`modules/network`).
2. El **SG `vpce`** solo admite 443 desde el CIDR de la VPC.
3. La API es **PRIVATE**. Su resource policy niega todo `execute-api:Invoke` cuya `aws:SourceVpce` no sea ese
   endpoint (`modules/edge`, `aws_iam_policy_document.private_api`).
4. La integración `HTTP_PROXY` sale por el **VPC Link** hacia el **NLB interno** (subredes privadas) en el puerto 80.
5. El target group TCP reenvía al **NodePort** del `graphql-gateway` en los nodos (dev 30080, test 30081, prod 30082).
   El **SG `k8s-nodes`** permite 30000-32767 solo desde la VPC.
6. kube-proxy envía el paquete al `Service graphql-gateway`, que elige un pod (stable o canary).
   La NetworkPolicy `allow-edge-to-gateway-and-frontend` lo admite.
7. De vuelta hacia los datos: pod → DynamoDB por el **Gateway VPCE**. Su ruta *prefix-list* está en la **route table
   privada** y su política limita el acceso a `aegisvolt-*-<env>`. Los logs van por el **Interface VPCE `logs`**.
   Nada sale a internet.

En Floci el plano de datos de VPC no se emula: API `REGIONAL` con integración directa. Ver la tabla del README.

---

## 2. CI/CD, Git y Canary — 25 %

### Intente `git push --force` o push directo a `test`

```bash
git checkout test && git commit --allow-empty -m "directo" && git push origin test          # rechazado
git push --force origin test                                                                  # rechazado
```

Ruleset `protect-environment-branches` (`.github/rulesets/environment-branches.json`, sin `bypass_actors`):
* `non_fast_forward` → bloquea el force push.
* `pull_request` → bloquea el push directo (solo se puede fusionar vía PR).
* `required_status_checks` → `promotion-guard`, `lint-build`, `unit-tests`, `integration-tests`, `e2e-tests`, `terraform-plan`.
* `deletion` → no se pueden borrar las ramas.

El job **`promotion-guard`** (`pr-checks.yml`) hace cumplir la cadena: a `test` solo se entra desde `dev`, y a
`prod` solo desde `test`. Un PR `feature/x → prod` queda en rojo y no se puede fusionar.

### ¿Cómo se determina el ambiente de `terraform apply` tras el merge?

`deploy.yml` se dispara con `on: push: branches: [dev, test, prod]`. Por el ruleset, ese push solo puede ser el merge
de un PR. El job `resolve-environment` toma `github.ref_name` (la rama destino) y lo publica como output. Después
`terraform-apply` ejecuta `terraform workspace select "$TARGET_ENV"`, comprueba que `terraform workspace show` coincida
y aplica. El canary despliega en el namespace `aegisvolt-$TARGET_ENV`.
En el PR, `terraform-plan` usa `github.base_ref`, que también es la rama destino.

### ¿Qué métrica evalúa el Canary antes de pasar de 20 % a 100 %?

`scripts/deploy/canary.py`:
* **20 % del tráfico**: 1 pod canary y 4 stable detrás del mismo Service (el selector solo usa `app`).
* Durante 45 s genera tráfico sintético por GraphQL y luego lee de **CloudWatch Logs**
  (`/aegisvolt/<env>/<svc>`) los eventos `http.request` con `track = "canary"`.
* **Criterios** (todos deben cumplirse): tasa de 5xx ≤ 5 %, p95 ≤ 1000 ms, ≥ 10 peticiones (muestra válida),
  0 reinicios del pod canary y readiness OK.
* Si cumple → **PROMOTE**: `set image` en el Deployment stable (rolling update) y el canary vuelve a 0.
  Si no → **ROLLBACK**: canary a 0, stable intacto y exit 1 (el pipeline queda en rojo).
* Publica `CanaryErrorRate`, `CanaryP95Latency` y `CanaryRequests` en CloudWatch Metrics.

```powershell
python scripts/deploy/canary.py deploy --env dev --inject-canary-error-rate 0.6   # demo de rollback
```

---

## 3. Backend, SAGA y Feature Flags — 25 %

### Active la flag de fallo en `test`, dispare la mutación y muestre la compensación en DynamoDB

```powershell
python scripts/flag.py test SIMULATE_CHARGER_HARDWARE_FAULT on
```

En el frontend de test (http://localhost:30091), o en GraphiQL (http://localhost:30081/graphql):

```graphql
mutation {
  reserveAndActivateCharge(input: {fleetId: "FLEET-PACIFICO-LOG", vehicleId: "VAN-7",
    stationId: "BOG-NORTE", connectorId: "BOG-NORTE-C1", estimatedKwh: 20}) {
    id status failureStep failureCode
    steps { name type status service detail }
  }
}
```

El resultado es `COMPENSATED`, con los pasos RESERVE ✓ → CHARGE ✓ → ACTIVATE ✗ → **REFUND_WALLET → RELEASE_CONNECTOR**.
Evidencia en las tablas:

```powershell
aws --endpoint-url http://localhost:4566 dynamodb query --table-name aegisvolt-billing-test `
  --key-condition-expression "pk = :p" --expression-attribute-values '{\":p\":{\"S\":\"WALLET#FLEET-PACIFICO-LOG\"}}'
#  -> TX#<saga>#CHARGE  y  TX#<saga>#REFUND (evento de reversión con reverses=<charge>)
aws --endpoint-url http://localhost:4566 dynamodb get-item --table-name aegisvolt-reservations-test `
  --key '{\"pk\":{\"S\":\"RESERVATION#<saga>\"},\"sk\":{\"S\":\"META\"}}'      # status RELEASED
```

El conector vuelve a `AVAILABLE` y la sesión de dispatch queda `FAULTED`. Si el fallo es por **fondos insuficientes**
(`FLEET-SIN-FONDOS`), solo se ejecuta `RELEASE_CONNECTOR`.

### ¿Cómo evita problemas de idempotencia si una compensación se procesa dos veces?

* **Llave de idempotencia = `saga_id`.** Cada paso y cada compensación escribe un registro con
  `ConditionExpression attribute_not_exists(pk)` *en la misma transacción* (`TransactWriteItems`) que el efecto:
  * reserva `RESERVATION#<saga>` junto con el bloqueo del conector;
  * cobro `TX#<saga>#CHARGE` junto con `balance = balance - :amt` (condición `balance >= :amt`);
  * reembolso `TX#<saga>#REFUND` junto con `balance + :amt`.
  Si la petición se repite, la transacción se cancela y se devuelve el registro existente (`outcome: REPLAY`).
  **No se reembolsa dos veces.** La prueba `test_compensation_is_idempotent_when_replayed` lo demuestra.
* **Compensación antes que la acción (timeouts).** Si el reembolso llega antes que el cobro, se escribe un
  *tombstone* `REFUND` de monto 0, y el cobro tardío verifica que no exista (`ConditionCheck`) y es rechazado.
  Lo mismo aplica a la reserva (tombstone `RELEASED`) y a dispatch (`ABORTED`).
* **Reintentos seguros.** El orquestador reintenta con backoff solo los errores transitorios (`clients.py`). Si el
  error es transitorio, también compensa el paso incierto, porque compensar algo que no ocurrió es un no-op.
* **Concurrencia.** Los conectores usan concurrencia optimista (`saga_id = :saga`, `version + 1`). La telemetría usa
  `last_telemetry_at = :prev`, así que varias réplicas no escriben el mismo punto.

### Preguntas probables adicionales

* **¿Orquestación o coreografía?** Orquestación (`services/graphql-gateway/app/saga.py`). El flujo es explícito, tiene
  un único dueño del estado (`aegisvolt-sagas-<env>`), el orden inverso de compensación es claro y se puede auditar.
* **¿Qué pasa si el orquestador muere a mitad?** La saga queda en un estado no terminal. Prefect la detecta como
  `ORPHAN` y `recoverSaga` re-ejecuta todas las compensaciones (idempotentes).
* **¿Por qué el conector pasa a CHARGING después de la saga?** Es un paso *post-pivote*: reintentable, no compensable.
* **¿Cómo están aisladas las flags?** Cada ambiente tiene su tabla `aegisvolt-feature-flags-<env>`, cuyo estado inicial
  declara Terraform con `ignore_changes = [item]`. Los servicios releen la tabla cada 3 s. La saga guarda un
  `flagsSnapshot` de las flags vigentes al iniciar.

---

## 4. Observabilidad — 12 %

### Muestre el flujo de Prefect y rastree en CloudWatch el `correlation_id` de una saga fallida

```powershell
prefect server start                                           # http://127.0.0.1:4200
$env:PREFECT_API_URL="http://127.0.0.1:4200/api"; python observability/prefect/serve.py
```

* `aegisvolt-environment-health` (cada 2 min): GraphQL y microservicios, tablas, log groups y errores de los últimos
  15 min. Artefacto `aegisvolt-health` y métrica `EnvironmentHealthy`.
* `aegisvolt-saga-consistency-audit` (cada 5 min): huérfanas, `COMPENSATION_FAILED`, `MISSING_REFUND`,
  `RESERVATION_NOT_RELEASED` y `LEAKED_CONNECTOR_LOCK`. Artefactos y métricas `SagaOrphans` y `SagaInconsistencies`.
* `aegisvolt-trace-saga` (bajo demanda, parámetro `saga_id`): la línea de tiempo del `correlation_id` en los 4 log
  groups.

En CloudWatch: grupo `/aegisvolt/test/graphql-gateway`, filtro `{ $.correlation_id = "saga-…" }`. Cada línea JSON
incluye `service`, `environment`, `version`, `track` y `event`. El `correlation_id` viaja en el header
`X-Correlation-ID` (`aegis_common/correlation.py`).

```powershell
aws --endpoint-url http://localhost:4566 logs filter-log-events --log-group-name /aegisvolt/test/billing-wallet-service `
  --filter-pattern '{ $.correlation_id = \"saga-...\" }'
```

---

## 5. Frontend — 8 %

### Cambie una flag en `dev` sin redesplegar y muestre que `prod` no cambia

```powershell
python scripts/flag.py dev ENABLE_FAST_CHARGE_BOOST off     # http://localhost:30090 cambia en ~3 s
python scripts/flag.py prod --list                          # prod conserva su propio valor
```

El frontend se suscribe a `featureFlagsLive` (WebSocket) y oculta o muestra la opción de ultra-carga prioritaria.
Las tarifas cambian con el surge. El mismo bundle se promueve entre ambientes: `/config.js` (ConfigMap del overlay)
indica a qué endpoint GraphQL conectarse.
