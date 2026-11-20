"""station-reservation-service: disponibilidad y bloqueo temporal de bahías de carga (SAGA paso 1)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from aegis_common.app_factory import create_app
from aegis_common.aws import boto_client
from aegis_common.config import load_settings
from aegis_common.dynamo import to_plain
from aegis_common.flags import FAST_CHARGE_BOOST, FeatureFlagClient
from aegis_common.logging_setup import configure_logging, get_logger, log_event
from pydantic import BaseModel, Field

from .repository import ReservationRepository
from .seed import STATIONS

settings = load_settings("station-reservation-service")
configure_logging(settings)
logger = get_logger("station-reservation")

dynamo = boto_client("dynamodb", settings)
TABLE = settings.table_name("reservations")
repo = ReservationRepository(dynamo, TABLE)
flags = FeatureFlagClient(dynamo, settings.table_name("feature-flags"))


@asynccontextmanager
async def lifespan(_app):
    if settings.seed_demo_data:
        try:
            await asyncio.to_thread(repo.seed, STATIONS)
        except Exception as exc:  # noqa: BLE001
            log_event(logger, "seed.failed", level=30, error=str(exc))
    yield


app = create_app(
    settings,
    title="station-reservation-service",
    description="Gestión de disponibilidad y bloqueo temporal de conectores de carga",
    lifespan=lifespan,
    dynamo_client=dynamo,
    ready_tables=[TABLE],
)


class ReserveRequest(BaseModel):
    saga_id: str = Field(min_length=8, max_length=80)
    station_id: str
    connector_id: str
    fleet_id: str
    vehicle_id: str
    fast_charge_boost: bool = False


class ReleaseRequest(BaseModel):
    reason: str = Field(default="SAGA_COMPENSATION", max_length=300)


@app.get("/stations", tags=["stations"])
def list_stations():
    return {"stations": to_plain(repo.list_stations())}


@app.get("/stations/{station_id}", tags=["stations"])
def get_station(station_id: str):
    return {"station": to_plain(repo.get_station(station_id))}


@app.get("/reservations", tags=["reservations"])
def list_reservations(limit: int = 100):
    return {"reservations": to_plain(repo.list_reservations(limit))}


@app.get("/reservations/{saga_id}", tags=["reservations"])
def get_reservation(saga_id: str):
    reservation = repo.get_reservation(saga_id)
    if reservation is None:
        from aegis_common.errors import NotFoundError

        raise NotFoundError(f"Reserva {saga_id} no existe", code="RESERVATION_NOT_FOUND")
    return {"reservation": to_plain(reservation)}


@app.post("/reservations", tags=["saga"])
def reserve(body: ReserveRequest):
    """SAGA paso 1 — idempotente por saga_id."""
    reservation, replayed = repo.reserve(
        **body.model_dump(),
        boost_feature_enabled=flags.is_enabled(FAST_CHARGE_BOOST),
    )
    return {"reservation": to_plain(reservation), "replayed": replayed}


@app.post("/reservations/{saga_id}/release", tags=["saga"])
def release(saga_id: str, body: ReleaseRequest | None = None):
    """SAGA compensación — libera el conector. Idempotente (REPLAY / TOMBSTONE)."""
    reservation, outcome = repo.release(saga_id, (body or ReleaseRequest()).reason)
    return {"reservation": to_plain(reservation), "outcome": outcome}


@app.post("/reservations/{saga_id}/activate", tags=["lifecycle"])
def activate(saga_id: str):
    reservation, replayed = repo.activate(saga_id)
    return {"reservation": to_plain(reservation), "replayed": replayed}


@app.post("/reservations/{saga_id}/complete", tags=["lifecycle"])
def complete(saga_id: str):
    reservation, replayed = repo.complete(saga_id)
    return {"reservation": to_plain(reservation), "replayed": replayed}
