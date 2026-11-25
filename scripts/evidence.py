"""Evidencia de una SAGA en DynamoDB y CloudWatch Logs, lista para mostrar en vivo (sin AWS CLI).

  python scripts/evidence.py sagas --env test                    # últimas sagas del ambiente
  python scripts/evidence.py saga  --env test --last             # todo sobre la última saga:
                                                                 #   bitácora, cobro/reembolso, reserva,
                                                                 #   conector y sesión de dispatch
  python scripts/evidence.py saga  --env test --id <saga_id>
  python scripts/evidence.py wallet --env test --fleet FLEET-PACIFICO-LOG
  python scripts/evidence.py logs  --env test --last             # línea de tiempo del correlation_id
  python scripts/evidence.py logs  --env test --id <saga_id> --minutes 120

Cada tabla es la de SU microservicio y SU ambiente (aegisvolt-<tabla>-<env>): Database-per-Service.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import boto3
from boto3.dynamodb.types import TypeDeserializer

SERVICES = [
    "graphql-gateway",
    "station-reservation-service",
    "billing-wallet-service",
    "energy-dispatch-service",
]
_des = TypeDeserializer()


def client(service: str):
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    endpoint = os.getenv("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")
    return boto3.client(
        service, endpoint_url=endpoint or None, region_name=os.getenv("AWS_REGION", "us-east-1")
    )


def plain(item: dict | None) -> dict | None:
    if item is None:
        return None
    return {k: _des.deserialize(v) for k, v in item.items()}


def table(kind: str, env: str) -> str:
    return f"aegisvolt-{kind}-{env}"


def title(text: str) -> None:
    print(f"\n=== {text}")


def show(item: dict | None, keys: list[str]) -> None:
    if not item:
        print("  (no existe)")
        return
    for key in keys:
        if key in item:
            print(f"  {key:<16} {item[key]}")


def all_sagas(env: str) -> list[dict]:
    ddb, items, kwargs = client("dynamodb"), [], {"TableName": table("sagas", env)}
    while True:
        page = ddb.scan(**kwargs)
        items += [plain(i) for i in page.get("Items", [])]
        if "LastEvaluatedKey" not in page:
            return sorted(items, key=lambda s: s.get("created_at", ""), reverse=True)
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def resolve_saga_id(args) -> str:
    if args.id:
        return args.id
    sagas = all_sagas(args.env)
    if not sagas:
        sys.exit(f"No hay sagas en {table('sagas', args.env)}")
    return sagas[0]["saga_id"]


# ----------------------------------------------------------------------------- comandos
def cmd_sagas(args) -> None:
    sagas = all_sagas(args.env)[: args.limit]
    print(f"{table('sagas', args.env)} — {len(sagas)} más recientes")
    for s in sagas:
        print(
            f"  {s.get('created_at', '')[:19]}  {s['saga_id']}  {s.get('status', ''):<20} "
            f"{s.get('fleet_id', '')}  {s.get('connector_id', '')}  {s.get('failure_code') or ''}"
        )


def cmd_saga(args) -> None:
    ddb, env = client("dynamodb"), args.env
    saga_id = resolve_saga_id(args)
    saga = plain(ddb.get_item(TableName=table("sagas", env), Key={"saga_id": {"S": saga_id}}).get("Item"))

    title(f"Bitácora del orquestador — {table('sagas', env)}")
    show(
        saga,
        [
            "saga_id",
            "correlation_id",
            "status",
            "fleet_id",
            "station_id",
            "connector_id",
            "failure_step",
            "failure_code",
            "created_at",
            "updated_at",
        ],
    )
    for step in (saga or {}).get("steps", []):
        print(
            f"    {step.get('type', ''):<12} {step.get('name', ''):<20} {step.get('status', ''):<10} "
            f"{step.get('service', '')}"
        )
    if not saga:
        return

    fleet = saga["fleet_id"]
    title(f"Billetera — {table('billing', env)}  pk=WALLET#{fleet}")
    wallet = ddb.query(
        TableName=table("billing", env),
        KeyConditionExpression="pk = :pk AND begins_with(sk, :tx)",
        ExpressionAttributeValues={":pk": {"S": f"WALLET#{fleet}"}, ":tx": {"S": f"TX#{saga_id}#"}},
    )["Items"]
    for tx in map(plain, wallet):
        extra = f" reverses={tx['reverses']}" if tx.get("reverses") else ""
        print(f"  {tx['sk']:<50} amount={tx.get('amount')} {tx.get('status', '')}{extra}")
    if not wallet:
        print("  (sin movimientos: el cobro no llegó a ejecutarse)")
    meta = plain(
        ddb.get_item(
            TableName=table("billing", env), Key={"pk": {"S": f"WALLET#{fleet}"}, "sk": {"S": "META"}}
        ).get("Item")
    )
    print(f"  saldo actual     {meta.get('balance') if meta else '?'}")

    title(f"Reserva — {table('reservations', env)}  pk=RESERVATION#{saga_id}")
    reservation = plain(
        ddb.get_item(
            TableName=table("reservations", env),
            Key={"pk": {"S": f"RESERVATION#{saga_id}"}, "sk": {"S": "META"}},
        ).get("Item")
    )
    show(reservation, ["status", "station_id", "connector_id", "created_at", "updated_at"])
    connector = plain(
        ddb.get_item(
            TableName=table("reservations", env),
            Key={
                "pk": {"S": f"STATION#{saga['station_id']}"},
                "sk": {"S": f"CONNECTOR#{saga['connector_id']}"},
            },
        ).get("Item")
    )
    print(f"  conector ahora   {connector.get('status') if connector else '?'}  ({saga['connector_id']})")

    title(f"Sesión de carga — {table('dispatch', env)}  pk=SESSION#{saga_id}")
    session = plain(
        ddb.get_item(
            TableName=table("dispatch", env), Key={"pk": {"S": f"SESSION#{saga_id}"}, "sk": {"S": "META"}}
        ).get("Item")
    )
    show(session, ["status", "failure_code", "reason", "created_at", "updated_at"])


def cmd_wallet(args) -> None:
    ddb = client("dynamodb")
    items = ddb.query(
        TableName=table("billing", args.env),
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": {"S": f"WALLET#{args.fleet}"}},
    )["Items"]
    print(f"{table('billing', args.env)}  pk=WALLET#{args.fleet}")
    for item in map(plain, items):
        if item["sk"] == "META":
            print(f"  META  saldo={item.get('balance')}")
        else:
            extra = f" reverses={item['reverses']}" if item.get("reverses") else ""
            print(f"  {item['sk']:<50} amount={item.get('amount')}{extra}")


def cmd_logs(args) -> None:
    logs, saga_id = client("logs"), resolve_saga_id(args)
    start = int((time.time() - args.minutes * 60) * 1000)
    events = []
    for service in SERVICES:
        group = f"/aegisvolt/{args.env}/{service}"
        kwargs = {"logGroupName": group, "startTime": start}
        try:
            while True:
                page = logs.filter_log_events(**kwargs)
                for event in page.get("events", []):
                    if saga_id not in event["message"]:
                        continue
                    try:
                        body = json.loads(event["message"])
                    except ValueError:
                        continue
                    if body.get("correlation_id") == saga_id:
                        events.append((event["timestamp"], group, body))
                token = page.get("nextToken")
                if not token or token == kwargs.get("nextToken"):
                    break
                kwargs["nextToken"] = token
        except logs.exceptions.ResourceNotFoundException:
            print(f"  (no existe {group})")
    print(f"correlation_id = {saga_id} — {len(events)} eventos en /aegisvolt/{args.env}/*")
    for ts, group, body in sorted(events, key=lambda e: e[0]):
        when = time.strftime("%H:%M:%S", time.localtime(ts / 1000))
        if body.get("event") == "http.request":
            detail = f"{body.get('method')} {body.get('path')} -> {body.get('status')} ({body.get('duration_ms')} ms)"
        else:
            detail = body.get("detail") or body.get("error") or body.get("reason") or body.get("step") or ""
        print(
            f"  {when}  {body.get('level', ''):<7} {group.rsplit('/', 1)[-1]:<28} {body.get('event', ''):<30} {detail}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sagas", help="últimas sagas del ambiente")
    p.add_argument("--env", required=True, choices=["dev", "test", "prod"])
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_sagas)

    for name, func, help_text in (
        ("saga", cmd_saga, "evidencia de una saga en las 4 tablas"),
        ("logs", cmd_logs, "línea de tiempo del correlation_id en CloudWatch"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--env", required=True, choices=["dev", "test", "prod"])
        target = p.add_mutually_exclusive_group(required=True)
        target.add_argument("--id", help="saga_id (= correlation_id)")
        target.add_argument("--last", action="store_true", help="la saga más reciente")
        if name == "logs":
            p.add_argument("--minutes", type=int, default=60)
        p.set_defaults(func=func)

    p = sub.add_parser("wallet", help="movimientos de la billetera de una flota")
    p.add_argument("--env", required=True, choices=["dev", "test", "prod"])
    p.add_argument("--fleet", default="FLEET-PACIFICO-LOG")
    p.set_defaults(func=cmd_wallet)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
