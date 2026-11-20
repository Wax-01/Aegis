"""Orquestador de la SAGA "Reservar y Activar Carga" (patrón SAGA por ORQUESTACIÓN).

    Paso 1  RESERVE_CONNECTOR  station-reservation-service   compensación: RELEASE_CONNECTOR
    Paso 2  CHARGE_WALLET      billing-wallet-service        compensación: REFUND_WALLET
    Paso 3  ACTIVATE_CHARGER   energy-dispatch-service       compensación: ABORT_CHARGER (solo si fue incierto)

Reglas:
* Error de NEGOCIO (4xx) en el paso N  -> el paso N no se aplicó: se compensan los pasos 1..N-1 en orden inverso.
* Error TRANSITORIO (timeout/5xx) en N -> no se sabe si se aplicó: se compensan 1..N (las compensaciones son
  idempotentes y escriben "tombstones", por lo que compensar algo que nunca ocurrió es seguro).
* Fallo del paso 3 (falla física / flag SIMULATE_CHARGER_HARDWARE_FAULT) -> REFUND_WALLET y luego RELEASE_CONNECTOR.
* Fallo del paso 2 (fondos insuficientes)                                 -> RELEASE_CONNECTOR.
* Si una compensación falla tras N reintentos la saga queda COMPENSATION_FAILED (Prefect la detecta y
  `recoverSaga` la reintenta).

El correlation_id de todos los logs de la transacción es el saga_id.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from aegis_common.correlation import correlation_id_var
from aegis_common.dynamo import now_iso
from aegis_common.logging_setup import get_logger, log_event

from .clients import ServiceCallError

logger = get_logger("saga")

STARTED = "STARTED"
CONNECTOR_RESERVED = "CONNECTOR_RESERVED"
PAYMENT_CAPTURED = "PAYMENT_CAPTURED"
COMPLETED = "COMPLETED"
COMPENSATING = "COMPENSATING"
COMPENSATED = "COMPENSATED"
FAILED = "FAILED"
COMPENSATION_FAILED = "COMPENSATION_FAILED"
TERMINAL_STATUSES = frozenset({COMPLETED, COMPENSATED, FAILED, COMPENSATION_FAILED})
ALL_STATUSES = (
    STARTED,
    CONNECTOR_RESERVED,
    PAYMENT_CAPTURED,
    COMPLETED,
    COMPENSATING,
    COMPENSATED,
    FAILED,
    COMPENSATION_FAILED,
)

RESERVE, CHARGE, ACTIVATE = "RESERVE_CONNECTOR", "CHARGE_WALLET", "ACTIVATE_CHARGER"
STEP_ORDER = (RESERVE, CHARGE, ACTIVATE)
SERVICE_OF = {
    RESERVE: "station-reservation-service",
    CHARGE: "billing-wallet-service",
    ACTIVATE: "energy-dispatch-service",
}
COMPENSATION_OF = {RESERVE: "RELEASE_CONNECTOR", CHARGE: "REFUND_WALLET", ACTIVATE: "ABORT_CHARGER"}


@dataclass(frozen=True)
class ChargeRequest:
    fleet_id: str
    vehicle_id: str
    station_id: str
    connector_id: str
    estimated_kwh: float
    fast_charge_boost: bool = False


class SagaValidationError(ValueError):
    pass


def _step(
    name: str, service: str, kind: str, status: str, detail: str, error_code: str | None = None
) -> dict:
    return {
        "name": name,
        "service": service,
        "type": kind,
        "status": status,
        "detail": detail,
        "error_code": error_code,
        "at": now_iso(),
    }


class ChargeSagaOrchestrator:
    def __init__(
        self,
        *,
        store,
        reservations,
        billing,
        dispatch,
        flags,
        environment: str,
        version: str = "local",
        step_delay_s: float = 0.0,
        compensation_attempts: int = 5,
        compensation_backoff_s: float = 0.3,
    ):
        self.store = store
        self.reservations = reservations
        self.billing = billing
        self.dispatch = dispatch
        self.flags = flags
        self.environment = environment
        self.version = version
        self.step_delay_s = step_delay_s
        self.compensation_attempts = compensation_attempts
        self.compensation_backoff_s = compensation_backoff_s

    # ------------------------------------------------------------------ helpers
    @staticmethod
    async def _io(fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _pause(self) -> None:
        if self.step_delay_s > 0:
            await asyncio.sleep(self.step_delay_s)

    # ------------------------------------------------------------------ API pública
    async def start(self, request: ChargeRequest) -> dict[str, Any]:
        """Valida, registra la saga en STARTED y la devuelve (sin ejecutar pasos)."""
        if not 1 <= request.estimated_kwh <= 200:
            raise SagaValidationError("estimatedKwh debe estar entre 1 y 200")
        station = await self.reservations.get_station(request.station_id)
        connector = next(
            (c for c in station["connectors"] if c["connector_id"] == request.connector_id), None
        )
        if connector is None:
            raise SagaValidationError(
                f"El conector {request.connector_id} no pertenece a {request.station_id}"
            )

        saga_id = f"saga-{uuid.uuid4()}"
        now = now_iso()
        flags_snapshot = await self._io(self.flags.snapshot)
        saga = {
            "saga_id": saga_id,
            "correlation_id": saga_id,
            "saga_type": "RESERVE_AND_ACTIVATE_CHARGE",
            "environment": self.environment,
            "status": STARTED,
            "fleet_id": request.fleet_id,
            "vehicle_id": request.vehicle_id,
            "station_id": request.station_id,
            "station_name": station.get("name"),
            "connector_id": request.connector_id,
            "connector_power_kw": connector["power_kw"],
            "connector_tier": connector.get("tier"),
            "estimated_kwh": request.estimated_kwh,
            "fast_charge_boost": request.fast_charge_boost,
            "flags_snapshot": flags_snapshot,
            "orchestrator_version": self.version,
            "steps": [],
            "created_at": now,
            "updated_at": now,
        }
        await self._io(self.store.create, saga)
        token = correlation_id_var.set(saga_id)
        try:
            log_event(
                logger,
                "saga.started",
                saga_id=saga_id,
                fleet_id=request.fleet_id,
                station_id=request.station_id,
                connector_id=request.connector_id,
                flags=flags_snapshot,
            )
        finally:
            correlation_id_var.reset(token)
        return saga

    async def run(self, request: ChargeRequest) -> dict[str, Any]:
        saga = await self.start(request)
        return await self.execute(saga)

    async def execute(self, saga: dict[str, Any]) -> dict[str, Any]:
        saga_id = saga["saga_id"]
        token = correlation_id_var.set(saga_id)
        done: list[str] = []
        try:
            # ---------------- Paso 1: reservar conector
            await self._pause()
            try:
                result = await self.reservations.reserve(
                    saga_id=saga_id,
                    station_id=saga["station_id"],
                    connector_id=saga["connector_id"],
                    fleet_id=saga["fleet_id"],
                    vehicle_id=saga["vehicle_id"],
                    fast_charge_boost=saga["fast_charge_boost"],
                )
                reservation_status = result["reservation"]["status"]
                if reservation_status not in ("RESERVED", "ACTIVE"):
                    raise ServiceCallError(
                        SERVICE_OF[RESERVE],
                        409,
                        "RESERVATION_ALREADY_RELEASED",
                        f"La reserva ya fue liberada previamente (estado {reservation_status})",
                    )
            except ServiceCallError as err:
                return await self._on_step_failure(saga, RESERVE, err, done)
            done.append(RESERVE)
            await self._record(
                saga_id,
                RESERVE,
                "SUCCEEDED",
                f"Conector {saga['connector_id']} -> RESERVED"
                + (" (replay idempotente)" if result["replayed"] else ""),
                status=CONNECTOR_RESERVED,
            )

            # ---------------- Paso 2: cobrar billetera
            await self._pause()
            try:
                result = await self.billing.charge(
                    saga_id=saga_id,
                    fleet_id=saga["fleet_id"],
                    power_kw=float(saga["connector_power_kw"]),
                    estimated_kwh=float(saga["estimated_kwh"]),
                    fast_charge_boost=saga["fast_charge_boost"],
                )
            except ServiceCallError as err:
                return await self._on_step_failure(saga, CHARGE, err, done)
            done.append(CHARGE)
            charge = result["charge"]
            pricing = charge.get("pricing", {})
            await self._record(
                saga_id,
                CHARGE,
                "SUCCEEDED",
                f"Cobro de {charge['amount']} {charge.get('currency', 'USD')} "
                f"(surge x{pricing.get('surge_multiplier', 1)}; saldo restante {charge.get('balance_after')})",
                status=PAYMENT_CAPTURED,
                fields={
                    "amount": charge["amount"],
                    "currency": charge.get("currency", "USD"),
                    "surge_multiplier": pricing.get("surge_multiplier"),
                    "pricing": pricing,
                },
            )

            # ---------------- Paso 3: activar cargador (pivote)
            await self._pause()
            try:
                result = await self.dispatch.start(
                    saga_id=saga_id,
                    station_id=saga["station_id"],
                    connector_id=saga["connector_id"],
                    fleet_id=saga["fleet_id"],
                    vehicle_id=saga["vehicle_id"],
                    power_kw=float(saga["connector_power_kw"]),
                    target_kwh=float(saga["estimated_kwh"]),
                )
            except ServiceCallError as err:
                return await self._on_step_failure(saga, ACTIVATE, err, done)
            done.append(ACTIVATE)

            # Post-pivote (reintentable, sin compensación): el conector pasa a CHARGING.
            try:
                await self.reservations.activate(saga_id)
            except ServiceCallError as err:
                log_event(logger, "saga.post_step_failed", level=30, saga_id=saga_id, error=str(err))

            final = await self._record(
                saga_id,
                ACTIVATE,
                "SUCCEEDED",
                f"Flujo eléctrico iniciado a {saga['connector_power_kw']} kW (sesión {result['session']['status']})",
                status=COMPLETED,
                fields={"charging_status": "ACTIVE", "completed_at": now_iso()},
            )
            log_event(logger, "saga.completed", saga_id=saga_id, amount=final.get("amount"))
            return final
        finally:
            correlation_id_var.reset(token)

    async def recover(self, saga_id: str) -> dict[str, Any]:
        """Re-ejecuta las compensaciones de una saga atascada (huérfana) o COMPENSATION_FAILED."""
        saga = await self._io(self.store.get, saga_id)
        if saga is None:
            raise SagaValidationError(f"La saga {saga_id} no existe")
        if saga["status"] in TERMINAL_STATUSES and saga["status"] != COMPENSATION_FAILED:
            return saga
        token = correlation_id_var.set(saga_id)
        try:
            log_event(
                logger, "saga.recovery.started", level=30, saga_id=saga_id, previous_status=saga["status"]
            )
            return await self._compensate(saga, list(STEP_ORDER), reason=f"RECOVERY_FROM_{saga['status']}")
        finally:
            correlation_id_var.reset(token)

    # ------------------------------------------------------------------ fallos y compensación
    async def _record(
        self,
        saga_id: str,
        step: str,
        outcome: str,
        detail: str,
        *,
        status: str | None = None,
        fields: dict[str, Any] | None = None,
        kind: str = "ACTION",
        error_code: str | None = None,
    ) -> dict[str, Any]:
        name = step if kind == "ACTION" else COMPENSATION_OF[step]
        entry = _step(name, SERVICE_OF[step], kind, outcome, detail, error_code)
        log_event(
            logger,
            f"saga.{'step' if kind == 'ACTION' else 'compensation'}.{outcome.lower()}",
            level=30 if outcome == "FAILED" else 20,
            saga_id=saga_id,
            step=name,
            target_service=SERVICE_OF[step],
            detail=detail,
            error_code=error_code,
        )
        return await self._io(self.store.update, saga_id, status=status, append_steps=[entry], fields=fields)

    async def _on_step_failure(
        self, saga: dict[str, Any], step: str, err: ServiceCallError, done: list[str]
    ) -> dict[str, Any]:
        await self._record(
            saga["saga_id"],
            step,
            "FAILED",
            f"{err.message}" + (" (resultado incierto: error transitorio)" if err.transient else ""),
            error_code=err.code,
        )
        to_compensate = [*done, step] if err.transient else list(done)
        failure = {"failure_step": step, "failure_code": err.code, "failure_reason": err.message}
        if not to_compensate:
            final = await self._io(self.store.update, saga["saga_id"], status=FAILED, fields=failure)
            log_event(logger, "saga.failed", level=30, saga_id=saga["saga_id"], **failure)
            return final
        return await self._compensate(saga, to_compensate, reason=f"{step}:{err.code}", failure=failure)

    async def _compensate(
        self, saga: dict[str, Any], steps: list[str], *, reason: str, failure: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        saga_id = saga["saga_id"]
        await self._io(self.store.update, saga_id, status=COMPENSATING, fields=failure)
        log_event(
            logger,
            "saga.compensation.started",
            level=30,
            saga_id=saga_id,
            reason=reason,
            steps=[COMPENSATION_OF[s] for s in reversed(steps)],
        )
        all_ok = True
        for step in reversed(steps):
            ok, detail = await self._run_compensation(saga, step, reason)
            all_ok = all_ok and ok
            await self._record(saga_id, step, "COMPENSATED" if ok else "FAILED", detail, kind="COMPENSATION")

        final_status = COMPENSATED if all_ok else COMPENSATION_FAILED
        final = await self._io(
            self.store.update, saga_id, status=final_status, fields={"compensated_at": now_iso()}
        )
        log_event(
            logger,
            "saga.compensated" if all_ok else "saga.compensation_failed",
            level=30 if all_ok else 40,
            saga_id=saga_id,
            reason=reason,
        )
        return final

    async def _run_compensation(self, saga: dict[str, Any], step: str, reason: str) -> tuple[bool, str]:
        saga_id = saga["saga_id"]
        last_error: Exception | None = None
        for attempt in range(1, self.compensation_attempts + 1):
            try:
                if step == RESERVE:
                    res = await self.reservations.release(saga_id, reason)
                    return True, f"Conector {saga['connector_id']} liberado -> AVAILABLE ({res['outcome']})"
                if step == CHARGE:
                    res = await self.billing.refund(saga_id, saga["fleet_id"], reason)
                    refund = res["refund"]
                    return True, f"Reembolso de {refund.get('amount')} USD registrado ({res['outcome']})"
                if step == ACTIVATE:
                    res = await self.dispatch.abort(saga_id, reason)
                    return True, f"Sesión de carga abortada ({res['outcome']})"
                raise ValueError(step)
            except ServiceCallError as err:
                last_error = err
                log_event(
                    logger,
                    "saga.compensation.retry",
                    level=30,
                    saga_id=saga_id,
                    step=COMPENSATION_OF[step],
                    attempt=attempt,
                    error=str(err),
                )
                if attempt < self.compensation_attempts:
                    await asyncio.sleep(self.compensation_backoff_s * 2 ** (attempt - 1))
        return False, f"Compensación falló tras {self.compensation_attempts} intentos: {last_error}"
