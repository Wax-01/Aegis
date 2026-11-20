"""Bootstrap SOLO para el modo standalone (docker compose local y jobs de CI integration/e2e).

En los ambientes dev/test/prod las tablas, flags y log groups los crea Terraform (infra/). Este script replica
el mismo estado inicial para poder levantar el stack completo sin Terraform en un runner efímero.

Uso:  python scripts/bootstrap_standalone.py --env dev [--env test ...]
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import time

import boto3
from aegis_common.flags import FLAG_DESCRIPTIONS
from aegis_common.tables import TABLE_SCHEMAS, create_table, table_name

SERVICES = (
    "station-reservation-service",
    "billing-wallet-service",
    "energy-dispatch-service",
    "graphql-gateway",
)

# Mismo estado inicial que infra/live/locals.tf (env_config.*.feature_flags)
DEFAULT_FLAGS = {
    "dev": {
        "ENABLE_DYNAMIC_SURGE_PRICING": True,
        "ENABLE_FAST_CHARGE_BOOST": True,
        "SIMULATE_CHARGER_HARDWARE_FAULT": False,
    },
    "test": {
        "ENABLE_DYNAMIC_SURGE_PRICING": True,
        "ENABLE_FAST_CHARGE_BOOST": True,
        "SIMULATE_CHARGER_HARDWARE_FAULT": False,
    },
    "prod": {
        "ENABLE_DYNAMIC_SURGE_PRICING": False,
        "ENABLE_FAST_CHARGE_BOOST": False,
        "SIMULATE_CHARGER_HARDWARE_FAULT": False,
    },
}


def wait_for_endpoint(client, timeout_s: int = 90) -> None:
    deadline = time.time() + timeout_s
    while True:
        try:
            client.list_tables(Limit=1)
            return
        except Exception as exc:  # noqa: BLE001
            if time.time() > deadline:
                raise SystemExit(f"El endpoint AWS no respondió en {timeout_s}s: {exc}") from exc
            time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", action="append", choices=list(DEFAULT_FLAGS), required=True)
    args = parser.parse_args()

    kwargs = {
        "region_name": os.getenv("AWS_REGION", "us-east-1"),
        "endpoint_url": os.getenv("AWS_ENDPOINT_URL"),
    }
    dynamo = boto3.client("dynamodb", **kwargs)
    logs = boto3.client("logs", **kwargs)
    wait_for_endpoint(dynamo)

    for env in args.env:
        for logical in TABLE_SCHEMAS:
            create_table(dynamo, logical, table_name(logical, env))
        flags_table = table_name("feature-flags", env)
        for key, enabled in DEFAULT_FLAGS[env].items():
            with contextlib.suppress(dynamo.exceptions.ConditionalCheckFailedException):
                dynamo.put_item(
                    TableName=flags_table,
                    Item={
                        "flag_key": {"S": key},
                        "enabled": {"BOOL": enabled},
                        "description": {"S": FLAG_DESCRIPTIONS[key]},
                        "environment": {"S": env},
                        "updated_by": {"S": "bootstrap-standalone"},
                    },
                    ConditionExpression="attribute_not_exists(flag_key)",
                )
        for service in SERVICES:
            with contextlib.suppress(logs.exceptions.ResourceAlreadyExistsException):
                logs.create_log_group(logGroupName=f"/aegisvolt/{env}/{service}")
        print(f"[bootstrap] ambiente {env} listo: {len(TABLE_SCHEMAS)} tablas, flags y log groups")
    return 0


if __name__ == "__main__":
    sys.exit(main())
