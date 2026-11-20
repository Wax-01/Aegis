"""Persistencia del station-reservation-service (tabla aegisvolt-reservations-<env>).

Modelo single-table:
  pk=STATION#<id>      sk=META              -> datos de la electrolinera
  pk=STATION#<id>      sk=CONNECTOR#<id>    -> estado del conector (AVAILABLE|RESERVED|CHARGING|FAULTED)
  pk=RESERVATION#<saga> sk=META             -> registro de la reserva = llave de idempotencia del paso SAGA

Idempotencia: el registro RESERVATION#<saga_id> se escribe con `attribute_not_exists(pk)` en la MISMA
transacción que bloquea el conector. Si la petición llega dos veces, la segunda transacción se cancela y
se devuelve el registro existente (replay) sin volver a bloquear nada.

Compensación antes que acción: si la liberación (compensación) llega ANTES que la reserva (p.ej. timeout
de red), se escribe un "tombstone" RELEASED; una reserva tardía con ese saga_id encontrará el registro y
no bloqueará el conector.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from aegis_common.domain import connector_tier
from aegis_common.dynamo import (
    from_item,
    is_conditional_failure,
    iso,
    now_iso,
    scan_all,
    to_item,
    utcnow,
)
from aegis_common.errors import ConflictError, DomainError, NotFoundError
from aegis_common.logging_setup import get_logger, log_event
from botocore.exceptions import ClientError

logger = get_logger("reservations")

AVAILABLE, RESERVED, CHARGING, FAULTED = "AVAILABLE", "RESERVED", "CHARGING", "FAULTED"
HOLD_FIELDS = "saga_id, fleet_id, vehicle_id, reserved_at, hold_expires_at"


def station_key(station_id: str) -> dict[str, str]:
    return {"pk": f"STATION#{station_id}", "sk": "META"}


def connector_key(station_id: str, connector_id: str) -> dict[str, str]:
    return {"pk": f"STATION#{station_id}", "sk": f"CONNECTOR#{connector_id}"}


def reservation_key(saga_id: str) -> dict[str, str]:
    return {"pk": f"RESERVATION#{saga_id}", "sk": "META"}


class ReservationRepository:
    def __init__(self, client, table: str, hold_minutes: int = 15):
        self.client = client
        self.table = table
        self.hold_minutes = hold_minutes

    # ------------------------------------------------------------------ lecturas
    def _get(self, key: dict[str, str]) -> dict[str, Any] | None:
        resp = self.client.get_item(TableName=self.table, Key=to_item(key), ConsistentRead=True)
        return from_item(resp.get("Item"))

    def get_connector(self, station_id: str, connector_id: str) -> dict[str, Any] | None:
        return self._get(connector_key(station_id, connector_id))

    def get_reservation(self, saga_id: str) -> dict[str, Any] | None:
        return self._get(reservation_key(saga_id))

    def list_stations(self) -> list[dict[str, Any]]:
        stations: dict[str, dict[str, Any]] = {}
        connectors: dict[str, list[dict[str, Any]]] = {}
        for item in scan_all(self.client, self.table, ConsistentRead=True):
            entity = item.get("entity")
            if entity == "STATION":
                stations[item["station_id"]] = {**item, "connectors": []}
            elif entity == "CONNECTOR":
                connectors.setdefault(item["station_id"], []).append(item)
        for station_id, items in connectors.items():
            if station_id in stations:
                stations[station_id]["connectors"] = sorted(items, key=lambda c: c["connector_id"])
        return sorted(stations.values(), key=lambda s: s["station_id"])

    def get_station(self, station_id: str) -> dict[str, Any]:
        for station in self.list_stations():
            if station["station_id"] == station_id:
                return station
        raise NotFoundError(f"Estación {station_id} no existe", code="STATION_NOT_FOUND")

    def list_reservations(self, limit: int = 100) -> list[dict[str, Any]]:
        items = scan_all(
            self.client,
            self.table,
            FilterExpression="entity = :e",
            ExpressionAttributeValues=to_item({":e": "RESERVATION"}),
        )
        return sorted(items, key=lambda r: r.get("created_at", ""), reverse=True)[:limit]

    # ------------------------------------------------------------------ SAGA paso 1
    def reserve(
        self,
        *,
        saga_id: str,
        station_id: str,
        connector_id: str,
        fleet_id: str,
        vehicle_id: str,
        fast_charge_boost: bool,
        boost_feature_enabled: bool,
    ) -> tuple[dict[str, Any], bool]:
        """Bloquea el conector (AVAILABLE -> RESERVED). Devuelve (reserva, replayed)."""
        existing = self.get_reservation(saga_id)
        if existing:
            log_event(logger, "reservation.replayed", saga_id=saga_id, status=existing["status"])
            return existing, True

        connector = self.get_connector(station_id, connector_id)
        if connector is None:
            raise NotFoundError(
                f"Conector {connector_id} no existe en {station_id}", code="CONNECTOR_NOT_FOUND"
            )
        if fast_charge_boost and not boost_feature_enabled:
            raise DomainError(
                "La reserva prioritaria de ultra-carga está deshabilitada en este ambiente "
                "(flag ENABLE_FAST_CHARGE_BOOST=false)",
                code="FEATURE_DISABLED",
                status_code=403,
            )
        if connector.get("tier") == "ULTRA" and not fast_charge_boost:
            raise DomainError(
                "Los conectores ULTRA (>= 300 kW) solo admiten reserva prioritaria (fastChargeBoost=true)",
                code="ULTRA_REQUIRES_BOOST",
                status_code=422,
            )

        now = utcnow()
        reservation = {
            **reservation_key(saga_id),
            "entity": "RESERVATION",
            "saga_id": saga_id,
            "station_id": station_id,
            "connector_id": connector_id,
            "fleet_id": fleet_id,
            "vehicle_id": vehicle_id,
            "fast_charge_boost": fast_charge_boost,
            "status": RESERVED,
            "created_at": iso(now),
            "updated_at": iso(now),
            "hold_expires_at": iso(now + timedelta(minutes=self.hold_minutes)),
        }
        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.table,
                            "Key": to_item(connector_key(station_id, connector_id)),
                            "UpdateExpression": (
                                "SET #st = :reserved, saga_id = :saga, fleet_id = :fleet, vehicle_id = :veh, "
                                "reserved_at = :now, hold_expires_at = :exp, updated_at = :now, "
                                "version = if_not_exists(version, :zero) + :one"
                            ),
                            "ConditionExpression": "attribute_exists(pk) AND (#st = :available OR saga_id = :saga)",
                            "ExpressionAttributeNames": {"#st": "status"},
                            "ExpressionAttributeValues": to_item(
                                {
                                    ":reserved": RESERVED,
                                    ":available": AVAILABLE,
                                    ":saga": saga_id,
                                    ":fleet": fleet_id,
                                    ":veh": vehicle_id,
                                    ":now": reservation["created_at"],
                                    ":exp": reservation["hold_expires_at"],
                                    ":zero": 0,
                                    ":one": 1,
                                }
                            ),
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": to_item(reservation),
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                ]
            )
        except ClientError as exc:
            if not is_conditional_failure(exc):
                raise
            existing = self.get_reservation(saga_id)
            if existing:  # carrera con un reintento concurrente o tombstone de compensación
                log_event(logger, "reservation.replayed", saga_id=saga_id, status=existing["status"])
                return existing, True
            current = self.get_connector(station_id, connector_id) or {}
            raise ConflictError(
                f"El conector {connector_id} no está disponible (estado {current.get('status', '?')})",
                code="CONNECTOR_UNAVAILABLE",
                details={"current_status": current.get("status")},
            ) from exc

        log_event(
            logger,
            "reservation.created",
            saga_id=saga_id,
            station_id=station_id,
            connector_id=connector_id,
            fleet_id=fleet_id,
        )
        return reservation, False

    # ------------------------------------------------------------------ SAGA compensación 1
    def release(self, saga_id: str, reason: str) -> tuple[dict[str, Any], str]:
        """Libera el conector (-> AVAILABLE). Idempotente. Devuelve (reserva, outcome)."""
        now = now_iso()
        existing = self.get_reservation(saga_id)
        if existing is None:
            tombstone = {
                **reservation_key(saga_id),
                "entity": "RESERVATION",
                "saga_id": saga_id,
                "status": "RELEASED",
                "tombstone": True,
                "release_reason": reason,
                "created_at": now,
                "updated_at": now,
                "released_at": now,
            }
            try:
                self.client.put_item(
                    TableName=self.table,
                    Item=to_item(tombstone),
                    ConditionExpression="attribute_not_exists(pk)",
                )
                log_event(logger, "reservation.release_tombstone", saga_id=saga_id, reason=reason)
                return tombstone, "TOMBSTONE"
            except ClientError as exc:
                if not is_conditional_failure(exc):
                    raise
                existing = self.get_reservation(saga_id)

        assert existing is not None
        if existing["status"] == "RELEASED":
            log_event(logger, "reservation.release_replayed", saga_id=saga_id)
            return existing, "REPLAY"

        release_update = {
            "Update": {
                "TableName": self.table,
                "Key": to_item(reservation_key(saga_id)),
                "UpdateExpression": "SET #st = :released, released_at = :now, release_reason = :r, updated_at = :now",
                "ConditionExpression": "#st <> :released",
                "ExpressionAttributeNames": {"#st": "status"},
                "ExpressionAttributeValues": to_item({":released": "RELEASED", ":now": now, ":r": reason}),
            }
        }
        try:
            self.client.transact_write_items(
                TransactItems=[
                    release_update,
                    {
                        "Update": {
                            "TableName": self.table,
                            "Key": to_item(connector_key(existing["station_id"], existing["connector_id"])),
                            "UpdateExpression": (
                                f"SET #st = :available, updated_at = :now, version = version + :one REMOVE {HOLD_FIELDS}"
                            ),
                            "ConditionExpression": "saga_id = :saga",
                            "ExpressionAttributeNames": {"#st": "status"},
                            "ExpressionAttributeValues": to_item(
                                {":available": AVAILABLE, ":now": now, ":saga": saga_id, ":one": 1}
                            ),
                        }
                    },
                ]
            )
            outcome = "RELEASED"
        except ClientError as exc:
            if not is_conditional_failure(exc):
                raise
            fresh = self.get_reservation(saga_id) or existing
            if fresh["status"] == "RELEASED":
                return fresh, "REPLAY"
            # El conector ya no pertenece a esta saga: solo cerramos el registro de reserva.
            self.client.update_item(**release_update["Update"])
            outcome = "RELEASED_RECORD_ONLY"

        released = self.get_reservation(saga_id) or existing
        log_event(logger, "reservation.released", saga_id=saga_id, reason=reason, outcome=outcome)
        return released, outcome

    # ------------------------------------------------------------------ ciclo de vida post-SAGA
    def activate(self, saga_id: str) -> tuple[dict[str, Any], bool]:
        """RESERVED -> CHARGING una vez el cargador confirmó el flujo de energía."""
        reservation = self.get_reservation(saga_id)
        if reservation is None or reservation.get("tombstone"):
            raise NotFoundError(f"Reserva {saga_id} no existe", code="RESERVATION_NOT_FOUND")
        if reservation["status"] == "ACTIVE":
            return reservation, True
        now = now_iso()
        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.table,
                            "Key": to_item(
                                connector_key(reservation["station_id"], reservation["connector_id"])
                            ),
                            "UpdateExpression": "SET #st = :charging, updated_at = :now, version = version + :one",
                            "ConditionExpression": "saga_id = :saga AND #st IN (:reserved, :charging)",
                            "ExpressionAttributeNames": {"#st": "status"},
                            "ExpressionAttributeValues": to_item(
                                {
                                    ":charging": CHARGING,
                                    ":reserved": RESERVED,
                                    ":saga": saga_id,
                                    ":now": now,
                                    ":one": 1,
                                }
                            ),
                        }
                    },
                    {
                        "Update": {
                            "TableName": self.table,
                            "Key": to_item(reservation_key(saga_id)),
                            "UpdateExpression": "SET #st = :active, activated_at = :now, updated_at = :now",
                            "ConditionExpression": "#st = :reserved",
                            "ExpressionAttributeNames": {"#st": "status"},
                            "ExpressionAttributeValues": to_item(
                                {":active": "ACTIVE", ":reserved": RESERVED, ":now": now}
                            ),
                        }
                    },
                ]
            )
        except ClientError as exc:
            if not is_conditional_failure(exc):
                raise
            fresh = self.get_reservation(saga_id) or {}
            if fresh.get("status") == "ACTIVE":
                return fresh, True
            raise ConflictError(
                f"La reserva {saga_id} no se puede activar (estado {fresh.get('status')})",
                code="RESERVATION_NOT_ACTIVABLE",
            ) from exc
        log_event(logger, "reservation.activated", saga_id=saga_id)
        return self.get_reservation(saga_id) or reservation, False

    def complete(self, saga_id: str) -> tuple[dict[str, Any], bool]:
        """CHARGING -> AVAILABLE al terminar la sesión de carga."""
        reservation = self.get_reservation(saga_id)
        if reservation is None or reservation.get("tombstone"):
            raise NotFoundError(f"Reserva {saga_id} no existe", code="RESERVATION_NOT_FOUND")
        if reservation["status"] == "COMPLETED":
            return reservation, True
        now = now_iso()
        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.table,
                            "Key": to_item(
                                connector_key(reservation["station_id"], reservation["connector_id"])
                            ),
                            "UpdateExpression": (
                                f"SET #st = :available, updated_at = :now, version = version + :one REMOVE {HOLD_FIELDS}"
                            ),
                            "ConditionExpression": "saga_id = :saga",
                            "ExpressionAttributeNames": {"#st": "status"},
                            "ExpressionAttributeValues": to_item(
                                {":available": AVAILABLE, ":saga": saga_id, ":now": now, ":one": 1}
                            ),
                        }
                    },
                    {
                        "Update": {
                            "TableName": self.table,
                            "Key": to_item(reservation_key(saga_id)),
                            "UpdateExpression": "SET #st = :completed, completed_at = :now, updated_at = :now",
                            "ConditionExpression": "#st IN (:active, :reserved)",
                            "ExpressionAttributeNames": {"#st": "status"},
                            "ExpressionAttributeValues": to_item(
                                {
                                    ":completed": "COMPLETED",
                                    ":active": "ACTIVE",
                                    ":reserved": RESERVED,
                                    ":now": now,
                                }
                            ),
                        }
                    },
                ]
            )
        except ClientError as exc:
            if not is_conditional_failure(exc):
                raise
            fresh = self.get_reservation(saga_id) or {}
            if fresh.get("status") == "COMPLETED":
                return fresh, True
            raise ConflictError(
                f"La reserva {saga_id} no se puede completar (estado {fresh.get('status')})",
                code="RESERVATION_NOT_COMPLETABLE",
            ) from exc
        log_event(logger, "reservation.completed", saga_id=saga_id)
        return self.get_reservation(saga_id) or reservation, False

    # ------------------------------------------------------------------ datos demo
    def seed(self, stations: list[dict[str, Any]]) -> int:
        created = 0
        now = now_iso()
        for station in stations:
            items = [
                {
                    **station_key(station["station_id"]),
                    "entity": "STATION",
                    **{k: v for k, v in station.items() if k != "connectors"},
                    "created_at": now,
                }
            ]
            for connector in station["connectors"]:
                cid, ctype, power, *rest = connector
                connector_id = f"{station['station_id']}-{cid}"
                items.append(
                    {
                        **connector_key(station["station_id"], connector_id),
                        "entity": "CONNECTOR",
                        "station_id": station["station_id"],
                        "connector_id": connector_id,
                        "connector_type": ctype,
                        "power_kw": power,
                        "tier": connector_tier(power),
                        "status": rest[0] if rest else AVAILABLE,
                        "version": 0,
                        "updated_at": now,
                    }
                )
            for item in items:
                try:
                    self.client.put_item(
                        TableName=self.table,
                        Item=to_item(item),
                        ConditionExpression="attribute_not_exists(pk)",
                    )
                    created += 1
                except ClientError as exc:
                    if not is_conditional_failure(exc):
                        raise
        if created:
            log_event(logger, "seed.completed", items_created=created)
        return created
