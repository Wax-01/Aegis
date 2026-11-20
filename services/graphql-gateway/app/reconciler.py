"""Cierre del ciclo de vida de la carga (fuera de la SAGA).

Cuando la sesión de energía termina (COMPLETED por telemetría o STOPPED por el usuario) el conector debe
volver a AVAILABLE. Este proceso revisa periódicamente las sagas COMPLETED con carga ACTIVE.
Todas las llamadas son idempotentes, así que varias réplicas del gateway pueden ejecutarlo en paralelo.
"""

from __future__ import annotations

import asyncio

from aegis_common.correlation import correlation_id_var
from aegis_common.dynamo import now_iso
from aegis_common.logging_setup import get_logger, log_event

from .clients import ServiceCallError
from .saga import COMPLETED

logger = get_logger("reconciler")
FINISHED_SESSION_STATES = {"COMPLETED", "STOPPED", "ABORTED"}


class SessionReconciler:
    def __init__(self, store, reservations, dispatch, interval_s: float = 5.0):
        self.store = store
        self.reservations = reservations
        self.dispatch = dispatch
        self.interval_s = interval_s

    async def finish(self, saga_id: str, session: dict) -> dict:
        try:
            await self.reservations.complete(saga_id)
        except ServiceCallError as err:
            if err.code not in ("RESERVATION_NOT_COMPLETABLE",):
                raise
        updated = await asyncio.to_thread(
            self.store.update,
            saga_id,
            fields={
                "charging_status": "FINISHED",
                "energy_delivered_kwh": session.get("energy_kwh"),
                "session_final_status": session.get("status"),
                "charging_finished_at": now_iso(),
            },
        )
        log_event(
            logger,
            "saga.charging_finished",
            saga_id=saga_id,
            energy_kwh=session.get("energy_kwh"),
            session_status=session.get("status"),
        )
        return updated

    async def reconcile_once(self) -> int:
        finished = 0
        sagas = await asyncio.to_thread(self.store.list_by_status, COMPLETED)
        for saga in sagas:
            if saga.get("charging_status") != "ACTIVE":
                continue
            token = correlation_id_var.set(saga["saga_id"])
            try:
                session = await self.dispatch.session(saga["saga_id"])
                if session.get("status") in FINISHED_SESSION_STATES:
                    await self.finish(saga["saga_id"], session)
                    finished += 1
            except ServiceCallError as err:
                log_event(logger, "reconciler.error", level=30, saga_id=saga["saga_id"], error=str(err))
            finally:
                correlation_id_var.reset(token)
        return finished

    async def run_forever(self) -> None:
        while True:
            try:
                await self.reconcile_once()
            except Exception as exc:  # noqa: BLE001
                log_event(logger, "reconciler.tick_failed", level=40, error=str(exc))
            await asyncio.sleep(self.interval_s)
