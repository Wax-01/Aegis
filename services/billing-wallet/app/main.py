"""billing-wallet-service: verificación de fondos, cobro y reembolso (SAGA paso 2 + compensación)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from aegis_common.app_factory import create_app
from aegis_common.aws import boto_client
from aegis_common.config import load_settings
from aegis_common.dynamo import to_plain
from aegis_common.flags import SURGE_PRICING, FeatureFlagClient
from aegis_common.logging_setup import configure_logging, get_logger, log_event
from pydantic import BaseModel, Field

from . import pricing
from .repository import BillingRepository

settings = load_settings("billing-wallet-service")
configure_logging(settings)
logger = get_logger("billing-wallet")

dynamo = boto_client("dynamodb", settings)
TABLE = settings.table_name("billing")
repo = BillingRepository(dynamo, TABLE)
flags = FeatureFlagClient(dynamo, settings.table_name("feature-flags"))

DEMO_WALLETS = [
    {"fleet_id": "FLEET-ANDES-EXPRESS", "name": "Andes Express (reparto urbano)", "balance": 850},
    {"fleet_id": "FLEET-PACIFICO-LOG", "name": "Pacífico Logística", "balance": 240},
    {"fleet_id": "FLEET-SIN-FONDOS", "name": "Reparto Demo (saldo bajo)", "balance": 4.5},
]


@asynccontextmanager
async def lifespan(_app):
    if settings.seed_demo_data:
        try:
            await asyncio.to_thread(repo.seed, DEMO_WALLETS)
        except Exception as exc:  # noqa: BLE001
            log_event(logger, "seed.failed", level=30, error=str(exc))
    yield


app = create_app(
    settings,
    title="billing-wallet-service",
    description="Billeteras de flota: cotización, cobro y reembolso idempotentes",
    lifespan=lifespan,
    dynamo_client=dynamo,
    ready_tables=[TABLE],
)


class QuoteRequest(BaseModel):
    power_kw: float = Field(gt=0, le=1000)
    estimated_kwh: float = Field(gt=0, le=500)
    fast_charge_boost: bool = False


class ChargeRequest(QuoteRequest):
    saga_id: str = Field(min_length=8, max_length=80)
    fleet_id: str


class RefundRequest(BaseModel):
    fleet_id: str
    reason: str = Field(default="SAGA_COMPENSATION", max_length=300)


class TopUpRequest(BaseModel):
    amount: float = Field(gt=0, le=100_000)


def _quote(body: QuoteRequest) -> dict:
    return pricing.quote(
        power_kw=body.power_kw,
        estimated_kwh=body.estimated_kwh,
        fast_charge_boost=body.fast_charge_boost,
        surge_enabled=flags.is_enabled(SURGE_PRICING),
    )


@app.get("/wallets", tags=["wallets"])
def list_wallets():
    return {"wallets": to_plain(repo.list_wallets())}


@app.get("/wallets/{fleet_id}", tags=["wallets"])
def get_wallet(fleet_id: str):
    return {"wallet": to_plain(repo.get_wallet(fleet_id))}


@app.get("/wallets/{fleet_id}/transactions", tags=["wallets"])
def list_transactions(fleet_id: str, limit: int = 50):
    return {"transactions": to_plain(repo.list_transactions(fleet_id, limit))}


@app.get("/wallets/{fleet_id}/sagas/{saga_id}", tags=["wallets"])
def saga_transactions(fleet_id: str, saga_id: str):
    return to_plain(repo.get_saga_transactions(fleet_id, saga_id))


@app.post("/wallets/{fleet_id}/topup", tags=["wallets"])
def top_up(fleet_id: str, body: TopUpRequest):
    return {"wallet": to_plain(repo.top_up(fleet_id, body.amount))}


@app.post("/quotes", tags=["pricing"])
def quote(body: QuoteRequest):
    return {"quote": to_plain(_quote(body))}


@app.post("/charges", tags=["saga"])
def charge(body: ChargeRequest):
    """SAGA paso 2 — idempotente por saga_id."""
    price = _quote(body)
    tx, replayed = repo.charge(
        saga_id=body.saga_id, fleet_id=body.fleet_id, amount=price["total"], pricing=price
    )
    return {"charge": to_plain(tx), "replayed": replayed}


@app.post("/charges/{saga_id}/refund", tags=["saga"])
def refund(saga_id: str, body: RefundRequest):
    """SAGA compensación — reembolso + evento de reversión. Idempotente (REPLAY / TOMBSTONE)."""
    tx, outcome = repo.refund(saga_id=saga_id, fleet_id=body.fleet_id, reason=body.reason)
    return {"refund": to_plain(tx), "outcome": outcome}
