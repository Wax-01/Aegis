"""energy-dispatch-service: orden de activación física del cargador y registro de telemetría (SAGA paso 3)."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from aegis_common.app_factory import create_app
from aegis_common.aws import boto_client
from aegis_common.config import env_bool, load_settings
from aegis_common.dynamo import to_plain
from aegis_common.flags import SIMULATE_HARDWARE_FAULT, FeatureFlagClient
from aegis_common.logging_setup import configure_logging, get_logger, log_event
from pydantic import BaseModel, Field

from .repository import DispatchRepository

settings = load_settings("energy-dispatch-service")
configure_logging(settings)
logger = get_logger("energy-dispatch")

dynamo = boto_client("dynamodb", settings)
TABLE = settings.table_name("dispatch")
repo = DispatchRepository(dynamo, TABLE)
flags = FeatureFlagClient(dynamo, settings.table_name("feature-flags"))

TELEMETRY_ENABLED = env_bool(os.getenv("TELEMETRY_SIMULATOR_ENABLED"), True)
TELEMETRY_INTERVAL_S = float(os.getenv("TELEMETRY_INTERVAL_SECONDS", "3"))
# Acelera el tiempo simulado para que una sesión de ~40 kWh termine en ~1 minuto durante la demo.
TELEMETRY_SPEED = float(os.getenv("TELEMETRY_TIME_ACCELERATION", "20"))


async def telemetry_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(repo.telemetry_tick, TELEMETRY_INTERVAL_S, TELEMETRY_SPEED)
        except Exception as exc:  # noqa: BLE001
            log_event(logger, "telemetry.tick_failed", level=40, error=str(exc))
        await asyncio.sleep(TELEMETRY_INTERVAL_S)


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(telemetry_loop()) if TELEMETRY_ENABLED else None
    yield
    if task:
        task.cancel()


app = create_app(
    settings,
    title="energy-dispatch-service",
    description="Activación física del cargador y telemetría de consumo energético",
    lifespan=lifespan,
    dynamo_client=dynamo,
    ready_tables=[TABLE],
)


class StartSessionRequest(BaseModel):
    saga_id: str = Field(min_length=8, max_length=80)
    station_id: str
    connector_id: str
    fleet_id: str
    vehicle_id: str
    power_kw: float = Field(gt=0, le=1000)
    target_kwh: float = Field(gt=0, le=500)


class AbortRequest(BaseModel):
    reason: str = Field(default="SAGA_COMPENSATION", max_length=300)


@app.get("/sessions", tags=["sessions"])
def list_sessions(status: str | None = None, limit: int = 100):
    return {"sessions": to_plain(repo.list_sessions(status, limit))}


@app.get("/sessions/{saga_id}", tags=["sessions"])
def get_session(saga_id: str):
    return {"session": to_plain(repo.require_session(saga_id))}


@app.get("/sessions/{saga_id}/telemetry", tags=["sessions"])
def get_telemetry(saga_id: str, limit: int = 60):
    return {"telemetry": to_plain(repo.telemetry(saga_id, limit))}


@app.post("/sessions", tags=["saga"])
def start_session(body: StartSessionRequest):
    """SAGA paso 3 — idempotente por saga_id. Con la flag de fallo activa responde 409."""
    session, replayed = repo.start(
        **body.model_dump(), simulate_fault=flags.is_enabled(SIMULATE_HARDWARE_FAULT)
    )
    return {"session": to_plain(session), "replayed": replayed}


@app.post("/sessions/{saga_id}/abort", tags=["saga"])
def abort_session(saga_id: str, body: AbortRequest | None = None):
    session, outcome = repo.abort(saga_id, (body or AbortRequest()).reason)
    return {"session": to_plain(session), "outcome": outcome}


@app.post("/sessions/{saga_id}/stop", tags=["sessions"])
def stop_session(saga_id: str):
    session, replayed = repo.stop(saga_id)
    return {"session": to_plain(session), "replayed": replayed}
