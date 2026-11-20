"""Cambia una feature flag de UN ambiente en caliente (sin redesplegar) escribiendo en su tabla DynamoDB.

  python scripts/flag.py dev SIMULATE_CHARGER_HARDWARE_FAULT on
  python scripts/flag.py dev --list
  python scripts/flag.py prod --list        # prod no cambia al modificar dev: tabla distinta

Equivalente con AWS CLI:
  aws --endpoint-url http://localhost:4566 dynamodb update-item --table-name aegisvolt-feature-flags-dev \
    --key '{"flag_key":{"S":"SIMULATE_CHARGER_HARDWARE_FAULT"}}' \
    --update-expression "SET enabled = :e" --expression-attribute-values '{":e":{"BOOL":true}}'
Los servicios releen la tabla cada ~3 s; el frontend lo refleja por la subscription featureFlagsLive.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime

import boto3

FLAGS = ("ENABLE_DYNAMIC_SURGE_PRICING", "ENABLE_FAST_CHARGE_BOOST", "SIMULATE_CHARGER_HARDWARE_FAULT")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("env", choices=["dev", "test", "prod"])
    parser.add_argument("flag", nargs="?", choices=FLAGS)
    parser.add_argument("state", nargs="?", choices=["on", "off"])
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    dynamo = boto3.client(
        "dynamodb",
        endpoint_url=os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566"),
        region_name="us-east-1",
    )
    table = f"aegisvolt-feature-flags-{args.env}"

    if args.flag and args.state:
        dynamo.update_item(
            TableName=table,
            Key={"flag_key": {"S": args.flag}},
            UpdateExpression="SET enabled = :e, updated_at = :t, updated_by = :u",
            ExpressionAttributeValues={
                ":e": {"BOOL": args.state == "on"},
                ":t": {"S": datetime.now(UTC).isoformat(timespec="seconds")},
                ":u": {"S": "cli:scripts/flag.py"},
            },
        )
        print(f"{table}: {args.flag} = {args.state.upper()}")
    elif not args.list:
        parser.error("indica FLAG y on/off, o usa --list")

    print(f"\nFlags en {table}:")
    for item in sorted(dynamo.scan(TableName=table)["Items"], key=lambda i: i["flag_key"]["S"]):
        state = "ON " if item.get("enabled", {}).get("BOOL") else "off"
        print(f"  [{state}] {item['flag_key']['S']:<34} ({item.get('updated_by', {}).get('S', '-')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
