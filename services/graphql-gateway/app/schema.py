"""Esquema GraphQL unificado de AegisVolt (capa de agregación).

Queries        -> estaciones/conectores en tiempo real, telemetría, billeteras, sagas, feature flags, ambiente.
Mutations      -> reserveAndActivateCharge (dispara la SAGA), stopChargingSession, recoverSaga, topUpWallet,
                  setFeatureFlag (admin).
Subscriptions  -> stationsLive, sagasLive, sagaLive, featureFlagsLive (graphql-transport-ws sobre WSS).

Este módulo no tiene efectos secundarios al importarse (se puede exportar el SDL en CI sin AWS).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from collections.abc import AsyncGenerator
from enum import Enum

import strawberry
from strawberry.types import Info

from .container import get_container
from .saga import ALL_STATUSES, TERMINAL_STATUSES, ChargeRequest


# --------------------------------------------------------------------------- enums
@strawberry.enum(description="Estado operativo de un conector de carga")
class ConnectorStatus(Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    CHARGING = "CHARGING"
    FAULTED = "FAULTED"
    OFFLINE = "OFFLINE"


@strawberry.enum(description="Nivel de potencia del conector")
class ConnectorTier(Enum):
    STANDARD = "STANDARD"
    FAST = "FAST"
    ULTRA = "ULTRA"


SagaStatus = strawberry.enum(
    Enum("SagaStatus", {s: s for s in ALL_STATUSES}),
    description="Estado de la transacción distribuida SAGA",
)


def _enum(enum_cls, value, default):
    try:
        return enum_cls(value)
    except ValueError:
        return default


def _f(value, default: float = 0.0) -> float:
    return float(value) if value is not None else default


# --------------------------------------------------------------------------- tipos
@strawberry.type
class LiveSession:
    saga_id: strawberry.ID
    status: str
    power_kw: float
    energy_kwh: float
    target_kwh: float
    soc: float


@strawberry.type
class Connector:
    id: strawberry.ID
    station_id: str
    connector_type: str
    power_kw: float
    tier: ConnectorTier
    status: ConnectorStatus
    saga_id: str | None
    fleet_id: str | None
    hold_expires_at: str | None
    updated_at: str | None
    live_session: LiveSession | None


@strawberry.type
class Station:
    id: strawberry.ID
    name: str
    city: str
    country: str
    address: str
    latitude: float
    longitude: float
    connectors: list[Connector]

    @strawberry.field
    def available_connectors(self) -> int:
        return sum(1 for c in self.connectors if c.status == ConnectorStatus.AVAILABLE)

    @strawberry.field
    def total_connectors(self) -> int:
        return len(self.connectors)


@strawberry.type
class SagaStep:
    name: str
    service: str
    type: str
    status: str
    detail: str
    error_code: str | None
    at: str


@strawberry.type
class FlagSnapshot:
    key: str
    enabled: bool


@strawberry.type
class TelemetryPoint:
    timestamp: str
    power_kw: float
    energy_kwh: float
    soc: float
    voltage_v: float
    current_a: float
    temperature_c: float


@strawberry.type
class ChargingSession:
    saga_id: strawberry.ID
    status: str
    station_id: str | None
    connector_id: str | None
    power_kw: float
    current_power_kw: float
    energy_kwh: float
    target_kwh: float
    soc: float
    soc_start: float
    fault_code: str | None
    fault_message: str | None
    started_at: str | None
    ended_at: str | None

    @strawberry.field
    async def telemetry(self, limit: int = 40) -> list[TelemetryPoint]:
        points = await get_container().dispatch.telemetry(str(self.saga_id), limit)
        return [
            TelemetryPoint(
                timestamp=p["timestamp"],
                power_kw=_f(p.get("power_kw")),
                energy_kwh=_f(p.get("energy_kwh")),
                soc=_f(p.get("soc")),
                voltage_v=_f(p.get("voltage_v")),
                current_a=_f(p.get("current_a")),
                temperature_c=_f(p.get("temperature_c")),
            )
            for p in points
        ]


@strawberry.type
class SagaTransaction:
    id: strawberry.ID
    correlation_id: str
    environment: str
    status: SagaStatus  # type: ignore[valid-type]
    fleet_id: str
    vehicle_id: str
    station_id: str
    station_name: str | None
    connector_id: str
    connector_power_kw: float
    estimated_kwh: float
    fast_charge_boost: bool
    amount: float | None
    currency: str | None
    surge_multiplier: float | None
    failure_step: str | None
    failure_code: str | None
    failure_reason: str | None
    charging_status: str | None
    energy_delivered_kwh: float | None
    flags_snapshot: list[FlagSnapshot]
    steps: list[SagaStep]
    created_at: str
    updated_at: str

    @strawberry.field
    def is_terminal(self) -> bool:
        return self.status.value in TERMINAL_STATUSES

    @strawberry.field
    def compensated(self) -> bool:
        return any(s.type == "COMPENSATION" for s in self.steps)

    @strawberry.field
    async def session(self) -> ChargingSession | None:
        if not any(s.name == "ACTIVATE_CHARGER" for s in self.steps):
            return None
        try:
            return to_session(await get_container().dispatch.session(str(self.id)))
        except Exception:  # noqa: BLE001
            return None


@strawberry.type
class WalletTransaction:
    id: str
    type: str
    saga_id: str | None
    amount: float
    currency: str
    balance_after: float | None
    reason: str | None
    tombstone: bool
    created_at: str


@strawberry.type
class Wallet:
    fleet_id: strawberry.ID
    name: str
    balance: float
    currency: str
    updated_at: str | None

    @strawberry.field
    async def transactions(self, limit: int = 20) -> list[WalletTransaction]:
        items = await get_container().billing.transactions(str(self.fleet_id), limit)
        return [
            WalletTransaction(
                id=t["tx_id"],
                type=t["tx_type"],
                saga_id=t.get("saga_id"),
                amount=_f(t.get("amount")),
                currency=t.get("currency", "USD"),
                balance_after=t.get("balance_after"),
                reason=t.get("reason"),
                tombstone=bool(t.get("tombstone", False)),
                created_at=t["created_at"],
            )
            for t in items
        ]


@strawberry.type
class FeatureFlag:
    key: str
    enabled: bool
    description: str
    environment: str
    updated_at: str | None
    updated_by: str | None
    source: str


@strawberry.type
class PriceQuote:
    tier: str
    rate_per_kwh: float
    estimated_kwh: float
    surge_pricing_enabled: bool
    peak_hour: bool
    surge_multiplier: float
    energy_cost: float
    boost_fee: float
    total: float
    currency: str
    local_time: str


@strawberry.type
class EnvironmentInfo:
    name: str
    version: str
    track: str
    instance: str
    region: str
    aws_backend: str
    tables: list[str]
    log_group_prefix: str


@strawberry.type
class ServiceHealth:
    name: str
    status: str
    version: str | None
    track: str | None
    latency_ms: float | None
    error: str | None


@strawberry.input
class ChargeRequestInput:
    fleet_id: str
    vehicle_id: str
    station_id: str
    connector_id: str
    estimated_kwh: float = 40.0
    fast_charge_boost: bool = False


# --------------------------------------------------------------------------- mapeos
def to_session(s: dict) -> ChargingSession:
    return ChargingSession(
        saga_id=strawberry.ID(s["saga_id"]),
        status=s["status"],
        station_id=s.get("station_id"),
        connector_id=s.get("connector_id"),
        power_kw=_f(s.get("power_kw")),
        current_power_kw=_f(s.get("current_power_kw")),
        energy_kwh=_f(s.get("energy_kwh")),
        target_kwh=_f(s.get("target_kwh")),
        soc=_f(s.get("soc")),
        soc_start=_f(s.get("soc_start")),
        fault_code=s.get("fault_code"),
        fault_message=s.get("fault_message"),
        started_at=s.get("started_at"),
        ended_at=s.get("ended_at"),
    )


def to_station(s: dict, live: dict[str, dict]) -> Station:
    connectors = []
    for c in s.get("connectors", []):
        session = live.get(c.get("saga_id") or "")
        connectors.append(
            Connector(
                id=strawberry.ID(c["connector_id"]),
                station_id=c["station_id"],
                connector_type=c.get("connector_type", "CCS2"),
                power_kw=_f(c.get("power_kw")),
                tier=_enum(ConnectorTier, c.get("tier"), ConnectorTier.FAST),
                status=_enum(ConnectorStatus, c.get("status"), ConnectorStatus.OFFLINE),
                saga_id=c.get("saga_id"),
                fleet_id=c.get("fleet_id"),
                hold_expires_at=c.get("hold_expires_at"),
                updated_at=c.get("updated_at"),
                live_session=LiveSession(
                    saga_id=strawberry.ID(session["saga_id"]),
                    status=session["status"],
                    power_kw=_f(session.get("current_power_kw")),
                    energy_kwh=_f(session.get("energy_kwh")),
                    target_kwh=_f(session.get("target_kwh")),
                    soc=_f(session.get("soc")),
                )
                if session
                else None,
            )
        )
    return Station(
        id=strawberry.ID(s["station_id"]),
        name=s["name"],
        city=s["city"],
        country=s["country"],
        address=s.get("address", ""),
        latitude=_f(s.get("latitude")),
        longitude=_f(s.get("longitude")),
        connectors=connectors,
    )


def to_saga(s: dict) -> SagaTransaction:
    snapshot = s.get("flags_snapshot") or {}
    return SagaTransaction(
        id=strawberry.ID(s["saga_id"]),
        correlation_id=s.get("correlation_id", s["saga_id"]),
        environment=s.get("environment", ""),
        status=SagaStatus(s["status"]),
        fleet_id=s["fleet_id"],
        vehicle_id=s["vehicle_id"],
        station_id=s["station_id"],
        station_name=s.get("station_name"),
        connector_id=s["connector_id"],
        connector_power_kw=_f(s.get("connector_power_kw")),
        estimated_kwh=_f(s.get("estimated_kwh")),
        fast_charge_boost=bool(s.get("fast_charge_boost")),
        amount=_f(s["amount"]) if s.get("amount") is not None else None,
        currency=s.get("currency"),
        surge_multiplier=_f(s["surge_multiplier"]) if s.get("surge_multiplier") is not None else None,
        failure_step=s.get("failure_step"),
        failure_code=s.get("failure_code"),
        failure_reason=s.get("failure_reason"),
        charging_status=s.get("charging_status"),
        energy_delivered_kwh=_f(s["energy_delivered_kwh"])
        if s.get("energy_delivered_kwh") is not None
        else None,
        flags_snapshot=[FlagSnapshot(key=k, enabled=bool(v)) for k, v in sorted(snapshot.items())],
        steps=[
            SagaStep(
                name=st["name"],
                service=st["service"],
                type=st["type"],
                status=st["status"],
                detail=st.get("detail", ""),
                error_code=st.get("error_code"),
                at=st["at"],
            )
            for st in s.get("steps", [])
        ],
        created_at=s["created_at"],
        updated_at=s["updated_at"],
    )


def to_wallet(w: dict) -> Wallet:
    return Wallet(
        fleet_id=strawberry.ID(w["fleet_id"]),
        name=w.get("name", w["fleet_id"]),
        balance=_f(w.get("balance")),
        currency=w.get("currency", "USD"),
        updated_at=w.get("updated_at"),
    )


def to_flags(env: str, states: dict) -> list[FeatureFlag]:
    return [
        FeatureFlag(
            key=st.key,
            enabled=st.enabled,
            description=st.description,
            environment=env,
            updated_at=st.updated_at,
            updated_by=st.updated_by,
            source=st.source,
        )
        for st in sorted(states.values(), key=lambda x: x.key)
    ]


# --------------------------------------------------------------------------- loaders
async def load_stations(city: str | None = None) -> list[Station]:
    c = get_container()
    stations, sessions = await asyncio.gather(c.reservations.list_stations(), c.dispatch.sessions("CHARGING"))
    live = {s["saga_id"]: s for s in sessions}
    result = [to_station(s, live) for s in stations]
    if city:
        result = [s for s in result if s.city.lower() == city.lower()]
    return result


async def load_flags(force: bool = False) -> list[FeatureFlag]:
    c = get_container()
    states = await asyncio.to_thread(c.flags.all, force)
    return to_flags(c.settings.env, states)


async def load_sagas(limit: int) -> list[SagaTransaction]:
    c = get_container()
    return [to_saga(s) for s in await asyncio.to_thread(c.store.list_recent, limit)]


def _signature(value) -> str:
    """Huella del payload para que las subscriptions solo emitan cuando algo cambió."""
    items = value if isinstance(value, list) else [value]
    return json.dumps([dataclasses.asdict(v) for v in items], default=str, sort_keys=True)


# --------------------------------------------------------------------------- Query
@strawberry.type
class Query:
    @strawberry.field(description="Ambiente estático al que está conectado este endpoint")
    def environment(self) -> EnvironmentInfo:
        c = get_container()
        s = c.settings
        return EnvironmentInfo(
            name=s.env,
            version=s.version,
            track=s.track,
            instance=s.instance_id,
            region=s.region,
            aws_backend="floci-emulator" if s.aws_endpoint_url else "aws",
            tables=[
                s.table_name(t) for t in ("reservations", "billing", "dispatch", "sagas", "feature-flags")
            ],
            log_group_prefix=f"/aegisvolt/{s.env}/",
        )

    @strawberry.field(description="Salud de los microservicios detrás del gateway")
    async def service_health(self) -> list[ServiceHealth]:
        c = get_container()

        async def probe(client) -> ServiceHealth:
            start = time.perf_counter()
            try:
                body = await client.health()
                return ServiceHealth(
                    name=client.name,
                    status="UP",
                    version=body.get("version"),
                    track=body.get("track"),
                    latency_ms=round((time.perf_counter() - start) * 1000, 1),
                    error=None,
                )
            except Exception as exc:  # noqa: BLE001
                return ServiceHealth(
                    name=client.name, status="DOWN", version=None, track=None, latency_ms=None, error=str(exc)
                )

        return list(await asyncio.gather(*(probe(cl) for cl in c.services)))

    @strawberry.field(description="Electrolineras con disponibilidad de conectores y sesiones en vivo")
    async def stations(self, city: str | None = None) -> list[Station]:
        return await load_stations(city)

    @strawberry.field
    async def station(self, id: strawberry.ID) -> Station | None:
        for station in await load_stations():
            if station.id == id:
                return station
        return None

    @strawberry.field(description="Feature flags del ambiente actual (cada ambiente tiene su propia tabla)")
    async def feature_flags(self) -> list[FeatureFlag]:
        return await load_flags()

    @strawberry.field(description="Historial de transacciones SAGA (más recientes primero)")
    async def sagas(self, limit: int = 30) -> list[SagaTransaction]:
        return await load_sagas(min(max(limit, 1), 200))

    @strawberry.field
    async def saga(self, id: strawberry.ID) -> SagaTransaction | None:
        item = await asyncio.to_thread(get_container().store.get, str(id))
        return to_saga(item) if item else None

    @strawberry.field
    async def wallets(self) -> list[Wallet]:
        return [to_wallet(w) for w in await get_container().billing.list_wallets()]

    @strawberry.field
    async def wallet(self, fleet_id: strawberry.ID) -> Wallet:
        return to_wallet(await get_container().billing.wallet(str(fleet_id)))

    @strawberry.field(description="Cotización (aplica ENABLE_DYNAMIC_SURGE_PRICING del ambiente)")
    async def price_quote(
        self, station_id: str, connector_id: str, estimated_kwh: float = 40.0, fast_charge_boost: bool = False
    ) -> PriceQuote:
        c = get_container()
        station = await c.reservations.get_station(station_id)
        connector = next((x for x in station["connectors"] if x["connector_id"] == connector_id), None)
        if connector is None:
            raise ValueError(f"Conector {connector_id} no existe en {station_id}")
        q = await c.billing.quote(
            power_kw=float(connector["power_kw"]),
            estimated_kwh=estimated_kwh,
            fast_charge_boost=fast_charge_boost,
        )
        return PriceQuote(**{k: q[k] for k in PriceQuote.__annotations__})

    @strawberry.field
    async def charging_session(self, saga_id: strawberry.ID) -> ChargingSession | None:
        try:
            return to_session(await get_container().dispatch.session(str(saga_id)))
        except Exception:  # noqa: BLE001
            return None


# --------------------------------------------------------------------------- Mutation
def _require_admin(info: Info) -> str:
    c = get_container()
    request = info.context.get("request")
    token = request.headers.get("x-admin-token") if request is not None else None
    if not c.admin_token or token != c.admin_token:
        raise PermissionError("Operación administrativa: header X-Admin-Token inválido o ausente")
    return request.headers.get("x-actor", "admin") if request is not None else "admin"


@strawberry.type
class Mutation:
    @strawberry.mutation(
        description=(
            "Dispara la SAGA Reservar -> Cobrar -> Activar. Con waitForCompletion=false responde de inmediato "
            "(estado STARTED) y el progreso se sigue con la subscription sagaLive."
        )
    )
    async def reserve_and_activate_charge(
        self, input: ChargeRequestInput, wait_for_completion: bool = True
    ) -> SagaTransaction:
        c = get_container()
        request = ChargeRequest(
            fleet_id=input.fleet_id,
            vehicle_id=input.vehicle_id,
            station_id=input.station_id,
            connector_id=input.connector_id,
            estimated_kwh=input.estimated_kwh,
            fast_charge_boost=input.fast_charge_boost,
        )
        saga = await c.orchestrator.start(request)
        if wait_for_completion:
            return to_saga(await c.orchestrator.execute(saga))
        task = asyncio.create_task(c.orchestrator.execute(saga))
        c.background_tasks.add(task)
        task.add_done_callback(c.background_tasks.discard)
        return to_saga(saga)

    @strawberry.mutation(description="Detiene la sesión de carga y libera el conector")
    async def stop_charging_session(self, saga_id: strawberry.ID) -> SagaTransaction:
        c = get_container()
        result = await c.dispatch.stop(str(saga_id))
        updated = await c.reconciler.finish(str(saga_id), result["session"])
        return to_saga(updated)

    @strawberry.mutation(description="Re-ejecuta compensaciones de una saga huérfana o COMPENSATION_FAILED")
    async def recover_saga(self, saga_id: strawberry.ID) -> SagaTransaction:
        return to_saga(await get_container().orchestrator.recover(str(saga_id)))

    @strawberry.mutation
    async def top_up_wallet(self, fleet_id: strawberry.ID, amount: float) -> Wallet:
        return to_wallet(await get_container().billing.top_up(str(fleet_id), amount))

    @strawberry.mutation(
        description="Cambia una flag del ambiente actual sin redesplegar (requiere X-Admin-Token)"
    )
    async def set_feature_flag(self, info: Info, key: str, enabled: bool) -> FeatureFlag:
        actor = _require_admin(info)
        c = get_container()
        state = await asyncio.to_thread(c.flags.set, key, enabled, f"graphql:{actor}")
        return to_flags(c.settings.env, {state.key: state})[0]


# --------------------------------------------------------------------------- Subscription
@strawberry.type
class Subscription:
    @strawberry.subscription(description="Estado de conectores en tiempo real (emite solo cuando cambia)")
    async def stations_live(self, interval_ms: int = 2000) -> AsyncGenerator[list[Station], None]:
        last = None
        while True:
            stations = await load_stations()
            sig = _signature(stations)
            if sig != last:
                last = sig
                yield stations
            await asyncio.sleep(max(interval_ms, 500) / 1000)

    @strawberry.subscription(description="Historial de sagas en tiempo real")
    async def sagas_live(
        self, limit: int = 20, interval_ms: int = 1500
    ) -> AsyncGenerator[list[SagaTransaction], None]:
        last = None
        while True:
            sagas = await load_sagas(limit)
            sig = _signature(sagas)
            if sig != last:
                last = sig
                yield sagas
            await asyncio.sleep(max(interval_ms, 500) / 1000)

    @strawberry.subscription(description="Progreso de una saga hasta su estado terminal")
    async def saga_live(self, saga_id: strawberry.ID) -> AsyncGenerator[SagaTransaction, None]:
        last = None
        while True:
            item = await asyncio.to_thread(get_container().store.get, str(saga_id))
            if item is None:
                return
            if item["updated_at"] != last:
                last = item["updated_at"]
                yield to_saga(item)
            if item["status"] in TERMINAL_STATUSES:
                return
            await asyncio.sleep(0.4)

    @strawberry.subscription(description="Feature flags del ambiente (emite al cambiar)")
    async def feature_flags_live(self, interval_ms: int = 2000) -> AsyncGenerator[list[FeatureFlag], None]:
        last = None
        while True:
            flags = await load_flags(force=True)
            sig = _signature(flags)
            if sig != last:
                last = sig
                yield flags
            await asyncio.sleep(max(interval_ms, 1000) / 1000)


schema = strawberry.Schema(query=Query, mutation=Mutation, subscription=Subscription)
