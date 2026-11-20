"""Bitácora de la SAGA (saga log) — tabla aegisvolt-sagas-<env>, propiedad del orquestador.

Cada transición y cada paso/compensación queda registrado. Prefect audita esta tabla (vía el GSI
status-created_at-index) para detectar sagas huérfanas (atascadas en estados no terminales) y cruza la
información con las tablas de reservations y billing.
"""

from __future__ import annotations

from typing import Any

from aegis_common.dynamo import from_item, now_iso, query_all, scan_all, to_item

STATUS_INDEX = "status-created_at-index"


class SagaStore:
    def __init__(self, client, table: str):
        self.client = client
        self.table = table

    def create(self, saga: dict[str, Any]) -> dict[str, Any]:
        self.client.put_item(
            TableName=self.table, Item=to_item(saga), ConditionExpression="attribute_not_exists(saga_id)"
        )
        return saga

    def get(self, saga_id: str) -> dict[str, Any] | None:
        resp = self.client.get_item(
            TableName=self.table, Key=to_item({"saga_id": saga_id}), ConsistentRead=True
        )
        return from_item(resp.get("Item"))

    def update(
        self,
        saga_id: str,
        *,
        status: str | None = None,
        append_steps: list[dict[str, Any]] | None = None,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sets = ["updated_at = :now"]
        values: dict[str, Any] = {":now": now_iso()}
        names: dict[str, str] = {}
        if status:
            sets.append("#st = :status")
            names["#st"] = "status"
            values[":status"] = status
        if append_steps:
            sets.append("steps = list_append(if_not_exists(steps, :empty), :steps)")
            values[":steps"] = append_steps
            values[":empty"] = []
        for i, (key, value) in enumerate((fields or {}).items()):
            if value is None:
                continue
            names[f"#f{i}"] = key
            values[f":f{i}"] = value
            sets.append(f"#f{i} = :f{i}")
        kwargs: dict[str, Any] = {
            "TableName": self.table,
            "Key": to_item({"saga_id": saga_id}),
            "UpdateExpression": "SET " + ", ".join(sets),
            "ExpressionAttributeValues": to_item(values),
            "ReturnValues": "ALL_NEW",
        }
        if names:
            kwargs["ExpressionAttributeNames"] = names
        return from_item(self.client.update_item(**kwargs)["Attributes"]) or {}

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        items = scan_all(self.client, self.table)
        return sorted(items, key=lambda s: s.get("created_at", ""), reverse=True)[:limit]

    def list_by_status(self, status: str) -> list[dict[str, Any]]:
        return query_all(
            self.client,
            self.table,
            IndexName=STATUS_INDEX,
            KeyConditionExpression="#st = :s",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues=to_item({":s": status}),
        )
