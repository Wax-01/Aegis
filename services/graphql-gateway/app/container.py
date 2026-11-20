"""Composición de dependencias del gateway (se construye una vez en el lifespan de FastAPI)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from aegis_common.aws import boto_client
from aegis_common.config import Settings
from aegis_common.flags import FeatureFlagClient

from .clients import BillingClient, DispatchClient, ReservationClient
from .reconciler import SessionReconciler
from .saga import ChargeSagaOrchestrator
from .saga_store import SagaStore


@dataclass
class Container:
    settings: Settings
    dynamo: object
    store: SagaStore
    flags: FeatureFlagClient
    reservations: ReservationClient
    billing: BillingClient
    dispatch: DispatchClient
    orchestrator: ChargeSagaOrchestrator
    reconciler: SessionReconciler
    admin_token: str | None
    background_tasks: set = field(default_factory=set)

    @property
    def services(self):
        return [self.reservations, self.billing, self.dispatch]

    async def aclose(self) -> None:
        for client in self.services:
            await client.aclose()


def build_container(settings: Settings) -> Container:
    dynamo = boto_client("dynamodb", settings)
    store = SagaStore(dynamo, settings.table_name("sagas"))
    flags = FeatureFlagClient(dynamo, settings.table_name("feature-flags"), ttl_seconds=2.0)
    timeout = float(os.getenv("SERVICE_TIMEOUT_SECONDS", "5"))
    reservations = ReservationClient(
        "station-reservation-service",
        os.getenv("RESERVATION_SERVICE_URL", "http://station-reservation-service:8000"),
        timeout=timeout,
    )
    billing = BillingClient(
        "billing-wallet-service",
        os.getenv("BILLING_SERVICE_URL", "http://billing-wallet-service:8000"),
        timeout=timeout,
    )
    dispatch = DispatchClient(
        "energy-dispatch-service",
        os.getenv("DISPATCH_SERVICE_URL", "http://energy-dispatch-service:8000"),
        timeout=timeout,
    )
    orchestrator = ChargeSagaOrchestrator(
        store=store,
        reservations=reservations,
        billing=billing,
        dispatch=dispatch,
        flags=flags,
        environment=settings.env,
        version=settings.version,
        step_delay_s=float(os.getenv("SAGA_STEP_DELAY_MS", "0")) / 1000,
    )
    reconciler = SessionReconciler(store, reservations, dispatch)
    return Container(
        settings=settings,
        dynamo=dynamo,
        store=store,
        flags=flags,
        reservations=reservations,
        billing=billing,
        dispatch=dispatch,
        orchestrator=orchestrator,
        reconciler=reconciler,
        admin_token=os.getenv("ADMIN_TOKEN") or None,
    )


_container: Container | None = None


def set_container(container: Container | None) -> None:
    global _container
    _container = container


def get_container() -> Container:
    if _container is None:
        raise RuntimeError("El contenedor de dependencias no está inicializado")
    return _container
