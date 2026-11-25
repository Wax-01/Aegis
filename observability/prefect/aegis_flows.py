"""Flujos de observabilidad de AegisVolt en Prefect.

  environment_health_check   Salud de dev/test/prod: GraphQL + microservicios, tablas DynamoDB, log groups,
                             errores recientes en CloudWatch. Publica la métrica EnvironmentHealthy.
  saga_consistency_audit     Audita la consistencia eventual: cruza la bitácora de sagas con las tablas de
                             billing y reservations para detectar sagas HUÉRFANAS, compensaciones incompletas
                             y conectores bloqueados por sagas ya terminadas. Opcionalmente las recupera.
  trace_saga                 Reconstruye en CloudWatch la línea de tiempo de un correlation_id (saga_id) a
                             través de los 4 servicios.

Variables de entorno:
  AWS_ENDPOINT_URL                (default http://localhost:4566 -> Floci)
  AEGIS_GRAPHQL_URL_<ENV>         (default http://localhost:3008x/graphql — NodePorts de kind)
  AEGIS_ADMIN_TOKEN_<ENV>         (solo para auto_recover)
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import httpx
from boto3.dynamodb.types import TypeDeserializer
from prefect import flow, get_run_logger, task
from prefect.artifacts import create_markdown_artifact, create_table_artifact

ENVIRONMENTS = ["dev", "test", "prod"]
DEFAULT_GRAPHQL = {"dev": 30080, "test": 30081, "prod": 30082}
SERVICES = [
    "station-reservation-service",
    "billing-wallet-service",
    "energy-dispatch-service",
    "graphql-gateway",
]
TABLES = ["reservations", "billing", "dispatch", "sagas", "feature-flags"]
TERMINAL = {"COMPLETED", "COMPENSATED", "FAILED", "COMPENSATION_FAILED"}

_deser = TypeDeserializer()


# ----------------------------------------------------------------------------- clientes
def _aws(service: str):
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    return boto3.client(
        service,
        endpoint_url=os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566") or None,
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )


def graphql_url(env: str) -> str:
    return os.getenv(f"AEGIS_GRAPHQL_URL_{env.upper()}", f"http://localhost:{DEFAULT_GRAPHQL[env]}/graphql")


def _scan(client, table: str, **kwargs) -> list[dict[str, Any]]:
    items, start = [], None
    while True:
        params = {"TableName": table, **kwargs}
        if start:
            params["ExclusiveStartKey"] = start
        page = client.scan(**params)
        items += [{k: _deser.deserialize(v) for k, v in i.items()} for i in page.get("Items", [])]
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def _get(client, table: str, key: dict[str, str]) -> dict[str, Any] | None:
    item = client.get_item(
        TableName=table, Key={k: {"S": v} for k, v in key.items()}, ConsistentRead=True
    ).get("Item")
    return {k: _deser.deserialize(v) for k, v in item.items()} if item else None


def _put_metric(env: str, name: str, value: float, unit: str = "Count") -> None:
    # Publicar la métrica es "best effort": nunca debe tumbar el flujo de auditoría.
    with contextlib.suppress(Exception):
        _aws("cloudwatch").put_metric_data(
            Namespace=f"AegisVolt/{env}",
            MetricData=[{"MetricName": name, "Value": value, "Unit": unit}],
        )


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ----------------------------------------------------------------------------- salud
@task(retries=1, retry_delay_seconds=3, task_run_name="graphql-{env}")
def check_graphql(env: str) -> dict[str, Any]:
    query = "{ environment { name version } serviceHealth { name status latencyMs } featureFlags { key enabled } }"
    start = time.perf_counter()
    try:
        response = httpx.post(graphql_url(env), json={"query": query}, timeout=8)
        data = response.json()["data"]
        return {
            "reachable": True,
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "version": data["environment"]["version"],
            "services": {s["name"]: s["status"] for s in data["serviceHealth"]},
            "flags": {f["key"]: f["enabled"] for f in data["featureFlags"]},
        }
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "error": str(exc)[:200], "services": {}, "flags": {}}


@task(task_run_name="dynamodb-{env}")
def check_tables(env: str) -> dict[str, str]:
    client = _aws("dynamodb")
    result = {}
    for logical in TABLES:
        name = f"aegisvolt-{logical}-{env}"
        try:
            result[name] = client.describe_table(TableName=name)["Table"]["TableStatus"]
        except Exception as exc:  # noqa: BLE001
            result[name] = f"MISSING ({exc.__class__.__name__})"
    return result


@task(task_run_name="cloudwatch-{env}")
def check_cloudwatch(env: str, window_minutes: int = 15) -> dict[str, Any]:
    logs = _aws("logs")
    groups = {
        g["logGroupName"]
        for g in logs.describe_log_groups(logGroupNamePrefix=f"/aegisvolt/{env}/")["logGroups"]
    }
    start_ms = int((time.time() - window_minutes * 60) * 1000)
    errors = 0
    for service in SERVICES:
        group = f"/aegisvolt/{env}/{service}"
        if group not in groups:
            continue
        for event in logs.filter_log_events(logGroupName=group, startTime=start_ms, limit=1000).get(
            "events", []
        ):
            try:
                if json.loads(event["message"]).get("level") == "ERROR":
                    errors += 1
            except ValueError:
                continue
    return {
        "log_groups_present": sorted(groups),
        "missing_log_groups": [s for s in SERVICES if f"/aegisvolt/{env}/{s}" not in groups],
        f"errors_last_{window_minutes}m": errors,
    }


@flow(name="aegisvolt-environment-health", log_prints=True)
def environment_health_check(environments: list[str] | None = None) -> dict[str, str]:
    logger = get_run_logger()
    environments = environments or ENVIRONMENTS
    rows, verdicts = [], {}
    for env in environments:
        api = check_graphql(env)
        tables = check_tables(env)
        cw = check_cloudwatch(env)
        tables_ok = all(v == "ACTIVE" for v in tables.values())
        services_ok = api["reachable"] and all(v == "UP" for v in api["services"].values())
        if not api["reachable"] and not tables_ok:
            verdict = "DOWN"
        elif services_ok and tables_ok and not cw["missing_log_groups"]:
            verdict = "HEALTHY"
        else:
            verdict = "DEGRADED"
        verdicts[env] = verdict
        _put_metric(env, "EnvironmentHealthy", 1 if verdict == "HEALTHY" else 0)
        logger.info("ambiente=%s estado=%s api=%s tablas=%s cloudwatch=%s", env, verdict, api, tables, cw)
        rows.append(
            {
                "ambiente": env,
                "estado": verdict,
                "graphql": "OK" if api["reachable"] else "SIN RESPUESTA",
                "latencia_ms": api.get("latency_ms", "-"),
                "microservicios": ", ".join(f"{k.split('-')[0]}={v}" for k, v in api["services"].items())
                or "-",
                "tablas_activas": f"{sum(v == 'ACTIVE' for v in tables.values())}/{len(tables)}",
                "errores_15m": cw["errors_last_15m"],
                "flags_on": ", ".join(k for k, v in api["flags"].items() if v) or "ninguna",
            }
        )
    create_table_artifact(key="aegisvolt-health", table=rows, description="Salud por ambiente estático")
    return verdicts


# ----------------------------------------------------------------------------- auditoría SAGA
@task(task_run_name="audit-{env}")
def audit_environment(env: str, orphan_minutes: int) -> dict[str, Any]:
    dynamo = _aws("dynamodb")
    sagas = _scan(dynamo, f"aegisvolt-sagas-{env}")
    now = datetime.now(UTC)
    by_status: dict[str, int] = {}
    anomalies: list[dict[str, Any]] = []
    compensations: list[dict[str, Any]] = []

    for saga in sagas:
        status = saga.get("status", "?")
        by_status[status] = by_status.get(status, 0) + 1
        saga_id, fleet = saga["saga_id"], saga.get("fleet_id", "")
        updated = _parse_ts(saga.get("updated_at"))
        age_min = round((now - updated).total_seconds() / 60, 1) if updated else None

        def anomaly(kind: str, detail: str, _saga=saga, _age=age_min) -> None:
            anomalies.append(
                {
                    "ambiente": env,
                    "saga_id": _saga["saga_id"],
                    "estado": _saga.get("status"),
                    "tipo": kind,
                    "detalle": detail,
                    "edad_min": _age,
                }
            )

        if status not in TERMINAL and age_min is not None and age_min >= orphan_minutes:
            anomaly("ORPHAN", f"atascada en {status} hace {age_min} min (sin estado terminal)")
        if status == "COMPENSATION_FAILED":
            anomaly("COMPENSATION_FAILED", "rollback incompleto: requiere recoverSaga")

        charge = _get(
            dynamo, f"aegisvolt-billing-{env}", {"pk": f"WALLET#{fleet}", "sk": f"TX#{saga_id}#CHARGE"}
        )
        refund = _get(
            dynamo, f"aegisvolt-billing-{env}", {"pk": f"WALLET#{fleet}", "sk": f"TX#{saga_id}#REFUND"}
        )
        reservation = _get(
            dynamo, f"aegisvolt-reservations-{env}", {"pk": f"RESERVATION#{saga_id}", "sk": "META"}
        )

        if status == "COMPENSATED":
            if charge and not refund:
                anomaly("MISSING_REFUND", "saga compensada con cobro pero sin reembolso")
            if reservation and reservation.get("status") not in ("RELEASED",):
                anomaly("RESERVATION_NOT_RELEASED", f"reserva en {reservation.get('status')}")

        if status in ("COMPENSATED", "COMPENSATION_FAILED"):
            # Una fila por reserva fallida: qué falló, qué compensaciones corrieron y si DynamoDB lo confirma.
            done = [
                f"{s.get('name')} {'✓' if s.get('status') == 'COMPENSATED' else '✗ ' + str(s.get('status'))}"
                for s in saga.get("steps", [])
                if s.get("type") == "COMPENSATION"
            ]
            refund_ok = (refund is not None) if charge else True
            released = reservation is None or reservation.get("status") == "RELEASED"
            compensations.append(
                {
                    "ambiente": env,
                    "fecha": (saga.get("created_at") or "")[:19].replace("T", " "),
                    "saga_id": saga_id,
                    "flota": fleet,
                    "conector": saga.get("connector_id"),
                    "falla": f"{saga.get('failure_step')}: {saga.get('failure_code')}",
                    "compensaciones": ", ".join(done) or "—",
                    "reembolso": f"{refund.get('amount')}"
                    if refund
                    else ("sin cobro" if not charge else "FALTA"),
                    "reserva": reservation.get("status") if reservation else "—",
                    "verificado": "OK" if (status == "COMPENSATED" and refund_ok and released) else "REVISAR",
                    # Campos internos (no van a la tabla): un task run por compensación en el flujo.
                    "_pasos": [
                        {"step": s.get("name"), "status": s.get("status"), "detail": s.get("detail")}
                        for s in saga.get("steps", [])
                        if s.get("type") == "COMPENSATION"
                    ],
                    "_updated": saga.get("updated_at") or saga.get("created_at"),
                }
            )
        if status == "COMPLETED" and not charge:
            anomaly("MISSING_CHARGE", "saga completada sin cobro registrado")

    # Bloqueos filtrados: conectores RESERVED/CHARGING cuya saga ya terminó sin carga activa.
    saga_index = {s["saga_id"]: s for s in sagas}
    connectors = _scan(
        dynamo,
        f"aegisvolt-reservations-{env}",
        FilterExpression="entity = :c",
        ExpressionAttributeValues={":c": {"S": "CONNECTOR"}},
    )
    for connector in connectors:
        held_by = connector.get("saga_id")
        if not held_by or connector.get("status") not in ("RESERVED", "CHARGING"):
            continue
        saga = saga_index.get(held_by)
        active = saga and saga.get("status") == "COMPLETED" and saga.get("charging_status") == "ACTIVE"
        in_flight = saga and saga.get("status") not in TERMINAL
        if not active and not in_flight:
            anomalies.append(
                {
                    "ambiente": env,
                    "saga_id": held_by,
                    "estado": saga.get("status") if saga else "DESCONOCIDA",
                    "tipo": "LEAKED_CONNECTOR_LOCK",
                    "detalle": f"{connector['connector_id']} sigue {connector['status']}",
                    "edad_min": None,
                }
            )

    compensated = by_status.get("COMPENSATED", 0)
    _put_metric(env, "SagaOrphans", sum(a["tipo"] == "ORPHAN" for a in anomalies))
    _put_metric(env, "SagaInconsistencies", len(anomalies))
    _put_metric(env, "SagaCompensatedTotal", compensated)
    compensations.sort(key=lambda c: c["fecha"], reverse=True)
    return {
        "env": env,
        "total": len(sagas),
        "by_status": by_status,
        "anomalies": anomalies,
        "compensations": compensations,
    }


@task(task_run_name="{step}-{env}-{short_id}")
def compensation_step(
    env: str, saga_id: str, short_id: str, step: str, status: str, detail: str, falla: str
) -> str:
    """Un task run por compensación ejecutada: verde si quedó COMPENSATED, rojo si no."""
    logger = get_run_logger()
    logger.info("ambiente=%s saga=%s falla=%s | %s -> %s | %s", env, saga_id, falla, step, status, detail)
    if status != "COMPENSATED":
        raise RuntimeError(f"{step} de {saga_id} quedó en {status}: {detail}")
    return f"{step} ✓ ({detail})"


@task(retries=2, retry_delay_seconds=5, task_run_name="recover-{saga_id}")
def recover_saga(env: str, saga_id: str) -> str:
    token = os.getenv(f"AEGIS_ADMIN_TOKEN_{env.upper()}", "")
    mutation = "mutation($id: ID!) { recoverSaga(sagaId: $id) { id status } }"
    response = httpx.post(
        graphql_url(env),
        json={"query": mutation, "variables": {"id": saga_id}},
        headers={"X-Admin-Token": token},
    )
    body = response.json()
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]["recoverSaga"]["status"]


@flow(name="aegisvolt-saga-consistency-audit", log_prints=True)
def saga_consistency_audit(
    environments: list[str] | None = None,
    orphan_minutes: int = 5,
    auto_recover: bool = False,
    compensation_window_minutes: int = 180,
) -> dict[str, Any]:
    logger = get_run_logger()
    environments = environments or ENVIRONMENTS
    results, all_anomalies, all_compensations = {}, [], []
    since = datetime.now(UTC) - timedelta(minutes=compensation_window_minutes)
    for env in environments:
        try:
            result = audit_environment(env, orphan_minutes)
        except Exception as exc:  # noqa: BLE001
            logger.error("no se pudo auditar %s: %s", env, exc)
            continue
        results[env] = result
        all_anomalies += result["anomalies"]
        all_compensations += result["compensations"]
        for c in result["compensations"]:
            logger.info(
                "compensación %s saga=%s falla=%s -> %s | reembolso=%s reserva=%s [%s]",
                env,
                c["saga_id"],
                c["falla"],
                c["compensaciones"],
                c["reembolso"],
                c["reserva"],
                c["verificado"],
            )
            updated = _parse_ts(c["_updated"])
            if updated and updated >= since:
                for paso in c["_pasos"]:
                    compensation_step(
                        env,
                        c["saga_id"],
                        c["saga_id"].removeprefix("saga-")[:8],
                        paso["step"] or "?",
                        paso["status"] or "?",
                        paso["detail"] or "",
                        c["falla"],
                        return_state=True,  # una compensación fallida queda en rojo sin tumbar la auditoría
                    )
        logger.info(
            "ambiente=%s sagas=%s por_estado=%s anomalías=%s",
            env,
            result["total"],
            result["by_status"],
            len(result["anomalies"]),
        )
        if auto_recover:
            for a in result["anomalies"]:
                if a["tipo"] in ("ORPHAN", "COMPENSATION_FAILED"):
                    logger.warning(
                        "recuperando %s en %s -> %s", a["saga_id"], env, recover_saga(env, a["saga_id"])
                    )

    lines = [
        "# Auditoría de consistencia SAGA",
        "",
        "| Ambiente | Total | Por estado | Anomalías |",
        "|---|---|---|---|",
    ]
    for env, r in results.items():
        states = ", ".join(f"{k}: {v}" for k, v in sorted(r["by_status"].items())) or "—"
        lines.append(f"| {env} | {r['total']} | {states} | {len(r['anomalies'])} |")
    lines += ["", "Compensadas = rollback distribuido completado (REFUND + RELEASE verificados en DynamoDB)."]
    create_markdown_artifact(key="aegisvolt-saga-audit", markdown="\n".join(lines))
    create_table_artifact(
        key="aegisvolt-saga-anomalies",
        table=all_anomalies or [{"resultado": "sin anomalías"}],
        description="Sagas huérfanas / inconsistencias detectadas",
    )
    create_table_artifact(
        key="aegisvolt-saga-compensations",
        table=[{k: v for k, v in c.items() if not k.startswith("_")} for c in all_compensations]
        or [{"resultado": "sin compensaciones"}],
        description="Reservas fallidas y su rollback distribuido (REFUND_WALLET / RELEASE_CONNECTOR)",
    )
    return {
        env: {"by_status": r["by_status"], "anomalies": len(r["anomalies"])} for env, r in results.items()
    }


# ----------------------------------------------------------------------------- trazabilidad
@flow(name="aegisvolt-trace-saga", log_prints=True)
def trace_saga(saga_id: str, environment: str = "dev", lookback_hours: int = 24) -> list[dict[str, Any]]:
    """Línea de tiempo de un correlation_id en CloudWatch Logs (equivalente al filtro
    `{ $.correlation_id = "<saga_id>" }` en los 4 log groups del ambiente)."""
    logger = get_run_logger()
    logs = _aws("logs")
    start_ms = int((datetime.now(UTC) - timedelta(hours=lookback_hours)).timestamp() * 1000)
    timeline = []
    for service in SERVICES:
        group = f"/aegisvolt/{environment}/{service}"
        kwargs: dict[str, Any] = {"logGroupName": group, "startTime": start_ms}
        while True:
            try:
                page = logs.filter_log_events(**kwargs)
            except logs.exceptions.ResourceNotFoundException:
                break
            for event in page.get("events", []):
                try:
                    body = json.loads(event["message"])
                except ValueError:
                    continue
                if body.get("correlation_id") == saga_id:
                    timeline.append(
                        {
                            "timestamp": body.get("timestamp"),
                            "servicio": body.get("service"),
                            "nivel": body.get("level"),
                            "evento": body.get("event") or body.get("message"),
                            "detalle": body.get("detail") or body.get("error") or body.get("path") or "",
                            "log_group": group,
                        }
                    )
            token = page.get("nextToken")
            if not token or token == kwargs.get("nextToken"):
                break
            kwargs["nextToken"] = token
    timeline.sort(key=lambda e: e["timestamp"] or "")
    for e in timeline:
        logger.info(
            "%s %-28s %-7s %s %s", e["timestamp"], e["servicio"], e["nivel"], e["evento"], e["detalle"]
        )
    create_table_artifact(
        key="aegisvolt-saga-trace",
        table=timeline or [{"resultado": f"sin eventos para {saga_id}"}],
        description=f"Traza CloudWatch del correlation_id {saga_id} ({environment})",
    )
    return timeline
