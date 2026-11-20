"""Helpers para usar el cliente de bajo nivel de DynamoDB (necesario para TransactWriteItems)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def now_iso() -> str:
    return iso(utcnow())


def dec(value: Any, places: str = "0.0001") -> Decimal:
    """DynamoDB no acepta float: todo número pasa por Decimal."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return d.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def money(value: Any) -> Decimal:
    return dec(value, "0.01")


def _normalize(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def to_item(data: dict[str, Any]) -> dict[str, Any]:
    return {k: _serializer.serialize(_normalize(v)) for k, v in data.items() if v is not None}


def from_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {k: _deserializer.deserialize(v) for k, v in item.items()}


def to_plain(value: Any) -> Any:
    """Convierte Decimal -> int/float de forma recursiva para serializar a JSON."""
    if isinstance(value, Decimal):
        return (
            int(value)
            if value == value.to_integral_value() and value.as_tuple().exponent >= 0
            else float(value)
        )
    if isinstance(value, dict):
        return {k: to_plain(v) for k, v in value.items()}
    if isinstance(value, list | set | tuple):
        return [to_plain(v) for v in value]
    return value


def error_code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "")


def is_conditional_failure(exc: ClientError) -> bool:
    return error_code(exc) in {"ConditionalCheckFailedException", "TransactionCanceledException"}


def scan_all(client, table: str, **kwargs) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    start_key = None
    while True:
        params = {"TableName": table, **kwargs}
        if start_key:
            params["ExclusiveStartKey"] = start_key
        page = client.scan(**params)
        items.extend(from_item(i) for i in page.get("Items", []))
        start_key = page.get("LastEvaluatedKey")
        if not start_key:
            return items


def query_all(client, table: str, **kwargs) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    start_key = None
    while True:
        params = {"TableName": table, **kwargs}
        if start_key:
            params["ExclusiveStartKey"] = start_key
        page = client.query(**params)
        items.extend(from_item(i) for i in page.get("Items", []))
        start_key = page.get("LastEvaluatedKey")
        if not start_key:
            return items
