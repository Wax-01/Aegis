"""Definición de tablas DynamoDB para pruebas (moto) y para el modo standalone (docker compose / CI).

En los ambientes reales las tablas las crea EXCLUSIVAMENTE Terraform (infra/modules/dynamodb).
Este archivo replica el mismo esquema de llaves para que las pruebas usen la misma forma de datos.
"""

from __future__ import annotations

from .config import PROJECT

TABLE_SCHEMAS: dict[str, dict] = {
    "reservations": {
        "KeySchema": [
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
    },
    "billing": {
        "KeySchema": [
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
    },
    "dispatch": {
        "KeySchema": [
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
    },
    "sagas": {
        "KeySchema": [{"AttributeName": "saga_id", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "saga_id", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "status-created_at-index",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    },
    "feature-flags": {
        "KeySchema": [{"AttributeName": "flag_key", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "flag_key", "AttributeType": "S"}],
    },
}


def table_name(logical: str, env: str) -> str:
    return f"{PROJECT}-{logical}-{env}"


def create_table(client, logical: str, name: str) -> None:
    schema = TABLE_SCHEMAS[logical]
    try:
        client.create_table(TableName=name, BillingMode="PAY_PER_REQUEST", **schema)
    except client.exceptions.ResourceInUseException:
        return
    client.get_waiter("table_exists").wait(TableName=name)
