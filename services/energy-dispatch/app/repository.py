"""Persistencia del energy-dispatch-service (tabla aegisvolt-dispatch-<env>).

  pk=SESSION#<saga>  sk=META                -> sesión de carga (CHARGING|FAULTED|COMPLETED|STOPPED|ABORTED)
  pk=SESSION#<saga>  sk=TELEMETRY#<ts>      -> puntos de telemetría (TTL expires_at, 24 h)

SAGA paso 3: la sesión se crea con attribute_not_exists(pk) -> idempotente. Si la flag
SIMULATE_CHARGER_HARDWARE_FAULT está activa, el cargador "reporta" una falla física: la sesión queda FAULTED
y se responde 409 CHARGER_HARDWARE_FAULT, lo que dispara las compensaciones en billing y reservations.
"""

from __future__ import annotations

import hashlib
import random
import time
from datetime import datetime
from typing import Any

from aegis_common.dynamo import (
    dec,
    from_item,
    is_conditional_failure,
    iso,
    now_iso,
    query_all,
    scan_all,
    to_item,
    utcnow,
)
from aegis_common.errors import ConflictError, NotFoundError
from aegis_common.logging_setup import get_logger, log_event
from botocore.exceptions import ClientError

logger = get_logger("dispatch")

CHARGING, FAULTED, COMPLETED, STOPPED, ABORTED = "CHARGING", "FAULTED", "COMPLETED", "STOPPED", "ABORTED"
BATTERY_KWH = 120.0
TELEMETRY_TTL_SECONDS = 24 * 3600


def session_key(saga_id: str) -> dict[str, str]:
    return {"pk": f"SESSION#{saga_id}", "sk": "META"}


def initial_soc(saga_id: str) -> float:
    digest = int(hashlib.sha256(saga_id.encode()).hexdigest()[:8], 16)
    return 15 + digest % 26  # 15..40 %


class DispatchRepository:
    def __init__(self, client, table: str, rng: random.Random | None = None):
        self.client = client
        self.table = table
        self.rng = rng or random.Random()

    def get_session(self, saga_id: str) -> dict[str, Any] | None:
        resp = self.client.get_item(
            TableName=self.table, Key=to_item(session_key(saga_id)), ConsistentRead=True
        )
        return from_item(resp.get("Item"))

    def require_session(self, saga_id: str) -> dict[str, Any]:
        session = self.get_session(saga_id)
        if session is None:
            raise NotFoundError(f"Sesión {saga_id} no existe", code="SESSION_NOT_FOUND")
        return session

    def list_sessions(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        expr = "entity = :e"
        values: dict[str, Any] = {":e": "SESSION"}
        names = None
        if status:
            expr += " AND #st = :st"
            values[":st"] = status
            names = {"#st": "status"}
        kwargs: dict[str, Any] = {"FilterExpression": expr, "ExpressionAttributeValues": to_item(values)}
        if names:
            kwargs["ExpressionAttributeNames"] = names
        items = scan_all(self.client, self.table, **kwargs)
        return sorted(items, key=lambda s: s.get("started_at", ""), reverse=True)[:limit]

    def telemetry(self, saga_id: str, limit: int = 60) -> list[dict[str, Any]]:
        items = query_all(
            self.client,
            self.table,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :t)",
            ExpressionAttributeValues=to_item({":pk": f"SESSION#{saga_id}", ":t": "TELEMETRY#"}),
        )
        return items[-limit:]

    # ------------------------------------------------------------------ SAGA paso 3
    def start(
        self,
        *,
        saga_id: str,
        station_id: str,
        connector_id: str,
        fleet_id: str,
        vehicle_id: str,
        power_kw: float,
        target_kwh: float,
        simulate_fault: bool,
    ) -> tuple[dict[str, Any], bool]:
        existing = self.get_session(saga_id)
        if existing is None:
            now = now_iso()
            soc = initial_soc(saga_id)
            session = {
                **session_key(saga_id),
                "entity": "SESSION",
                "saga_id": saga_id,
                "station_id": station_id,
                "connector_id": connector_id,
                "fleet_id": fleet_id,
                "vehicle_id": vehicle_id,
                "power_kw": dec(power_kw, "0.1"),
                "target_kwh": dec(target_kwh, "0.01"),
                "energy_kwh": dec(0),
                "current_power_kw": dec(0),
                "soc_start": dec(soc, "0.1"),
                "soc": dec(soc, "0.1"),
                "started_at": now,
                "updated_at": now,
                "last_telemetry_at": now,
            }
            if simulate_fault:
                session.update(
                    status=FAULTED,
                    fault_code="CHARGER_HARDWARE_FAULT",
                    fault_message=(
                        f"Falla de aislamiento (ground fault) en {connector_id}: el contactor de potencia no cerró"
                    ),
                    fault_injected_by="SIMULATE_CHARGER_HARDWARE_FAULT",
                )
            else:
                session["status"] = CHARGING
            try:
                self.client.put_item(
                    TableName=self.table,
                    Item=to_item(session),
                    ConditionExpression="attribute_not_exists(pk)",
                )
                replayed = False
                result = session
                log_event(
                    logger,
                    "session.faulted" if simulate_fault else "session.started",
                    level=40 if simulate_fault else 20,
                    saga_id=saga_id,
                    connector_id=connector_id,
                    power_kw=power_kw,
                    target_kwh=target_kwh,
                )
            except ClientError as exc:
                if not is_conditional_failure(exc):
                    raise
                result, replayed = self.require_session(saga_id), True
        else:
            result, replayed = existing, True

        if result["status"] == FAULTED:
            raise ConflictError(
                result.get("fault_message", "El cargador reportó una falla física"),
                code="CHARGER_HARDWARE_FAULT",
                details={"session_status": FAULTED, "replayed": replayed},
            )
        if result["status"] == ABORTED:
            raise ConflictError(f"La sesión {saga_id} fue abortada por compensación", code="SESSION_ABORTED")
        return result, replayed

    # ------------------------------------------------------------------ SAGA compensación 3
    def abort(self, saga_id: str, reason: str) -> tuple[dict[str, Any], str]:
        """Compensación del paso 3 (solo se usa si el resultado del paso 3 fue incierto)."""
        now = now_iso()
        existing = self.get_session(saga_id)
        if existing is None:
            tombstone = {
                **session_key(saga_id),
                "entity": "SESSION",
                "saga_id": saga_id,
                "status": ABORTED,
                "tombstone": True,
                "abort_reason": reason,
                "started_at": now,
                "updated_at": now,
            }
            try:
                self.client.put_item(
                    TableName=self.table,
                    Item=to_item(tombstone),
                    ConditionExpression="attribute_not_exists(pk)",
                )
                return tombstone, "TOMBSTONE"
            except ClientError as exc:
                if not is_conditional_failure(exc):
                    raise
                existing = self.require_session(saga_id)
        if existing["status"] != CHARGING:
            return existing, "REPLAY"
        self._transition(saga_id, CHARGING, ABORTED, {"abort_reason": reason, "ended_at": now})
        log_event(logger, "session.aborted", saga_id=saga_id, reason=reason)
        return self.require_session(saga_id), "ABORTED"

    def stop(self, saga_id: str) -> tuple[dict[str, Any], bool]:
        session = self.require_session(saga_id)
        if session["status"] != CHARGING:
            return session, True
        try:
            self._transition(saga_id, CHARGING, STOPPED, {"ended_at": now_iso()})
        except ClientError as exc:
            if not is_conditional_failure(exc):
                raise
            return self.require_session(saga_id), True
        log_event(logger, "session.stopped", saga_id=saga_id, energy_kwh=str(session.get("energy_kwh")))
        return self.require_session(saga_id), False

    def _transition(self, saga_id: str, from_status: str, to_status: str, extra: dict[str, Any]) -> None:
        sets = ", ".join(f"{k} = :{k}" for k in extra)
        values = {
            ":from": from_status,
            ":to": to_status,
            ":now": now_iso(),
            **{f":{k}": v for k, v in extra.items()},
        }
        self.client.update_item(
            TableName=self.table,
            Key=to_item(session_key(saga_id)),
            UpdateExpression=f"SET #st = :to, updated_at = :now{', ' + sets if sets else ''}, current_power_kw = :zero",
            ConditionExpression="#st = :from",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues=to_item({**values, ":zero": 0}),
        )

    # ------------------------------------------------------------------ simulador de telemetría
    def telemetry_tick(self, interval_s: float, speed: float, now: datetime | None = None) -> int:
        """Genera un punto de telemetría por sesión activa.

        Concurrencia optimista: el update exige `last_telemetry_at = :prev`, así con N réplicas
        (stable + canary) solo una escribe cada punto.
        """
        now = now or utcnow()
        written = 0
        for session in self.list_sessions(status=CHARGING, limit=500):
            prev = session.get("last_telemetry_at")
            last = datetime.fromisoformat(prev.replace("Z", "+00:00")) if prev else now
            elapsed = (now - last).total_seconds()
            if elapsed < interval_s * 0.8:
                continue

            soc = float(session["soc"])
            energy = float(session["energy_kwh"])
            target = float(session["target_kwh"])
            max_power = float(session["power_kw"])
            taper = 1.0 if soc < 80 else max(0.25, (100 - soc) / 20)
            power = max_power * taper * self.rng.uniform(0.90, 0.99)
            delta = min(power * elapsed / 3600 * speed, max(target - energy, 0))
            energy += delta
            soc = min(100.0, soc + delta / BATTERY_KWH * 100)
            done = energy >= target - 1e-6 or soc >= 100
            platform_v = 800 if max_power >= 300 else 400
            voltage = platform_v * (0.92 + soc / 100 * 0.08)
            current = power * 1000 / voltage
            temperature = 27 + (power / max_power) * 12 + self.rng.uniform(-0.8, 0.8)
            ts = iso(now)

            values: dict[str, Any] = {
                ":prev": prev,
                ":charging": CHARGING,
                ":status": COMPLETED if done else CHARGING,
                ":energy": dec(energy, "0.001"),
                ":soc": dec(soc, "0.1"),
                ":power": dec(0 if done else power, "0.1"),
                ":ts": ts,
            }
            update = (
                "SET energy_kwh = :energy, soc = :soc, current_power_kw = :power, "
                "last_telemetry_at = :ts, updated_at = :ts, #st = :status"
            )
            if done:
                update += ", ended_at = :ts"
            try:
                self.client.update_item(
                    TableName=self.table,
                    Key=to_item(session_key(session["saga_id"])),
                    UpdateExpression=update,
                    ConditionExpression="last_telemetry_at = :prev AND #st = :charging",
                    ExpressionAttributeNames={"#st": "status"},
                    ExpressionAttributeValues=to_item(values),
                )
            except ClientError as exc:
                if is_conditional_failure(exc):
                    continue  # otra réplica escribió este punto
                raise
            self.client.put_item(
                TableName=self.table,
                Item=to_item(
                    {
                        "pk": f"SESSION#{session['saga_id']}",
                        "sk": f"TELEMETRY#{ts}",
                        "entity": "TELEMETRY",
                        "saga_id": session["saga_id"],
                        "timestamp": ts,
                        "power_kw": dec(power, "0.1"),
                        "energy_kwh": dec(energy, "0.001"),
                        "soc": dec(soc, "0.1"),
                        "voltage_v": dec(voltage, "0.1"),
                        "current_a": dec(current, "0.1"),
                        "temperature_c": dec(temperature, "0.1"),
                        "expires_at": int(time.time()) + TELEMETRY_TTL_SECONDS,
                    }
                ),
            )
            written += 1
            if done:
                log_event(
                    logger, "session.completed", saga_id=session["saga_id"], energy_kwh=round(energy, 3)
                )
        return written
