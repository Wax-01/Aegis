"""Dobles de prueba en memoria para aislar la lógica del orquestador SAGA."""

from __future__ import annotations

import copy

from aegis_common.correlation import get_correlation_id
from aegis_common.dynamo import now_iso
from app.clients import ServiceCallError

STATION = {
    "station_id": "BOG-NORTE",
    "name": "Electrolinera Calle 100",
    "connectors": [{"connector_id": "BOG-NORTE-C1", "power_kw": 150, "tier": "FAST"}],
}


class FakeStore:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def create(self, saga):
        self.items[saga["saga_id"]] = copy.deepcopy(saga)
        return saga

    def get(self, saga_id):
        return copy.deepcopy(self.items.get(saga_id))

    def update(self, saga_id, *, status=None, append_steps=None, fields=None):
        item = self.items[saga_id]
        if status:
            item["status"] = status
        if append_steps:
            item.setdefault("steps", []).extend(copy.deepcopy(append_steps))
        for k, v in (fields or {}).items():
            if v is not None:
                item[k] = v
        item["updated_at"] = now_iso()
        return copy.deepcopy(item)

    def list_recent(self, limit=50):
        return list(self.items.values())[:limit]

    def list_by_status(self, status):
        return [copy.deepcopy(i) for i in self.items.values() if i["status"] == status]


class Recorder:
    def __init__(self):
        self.calls: list[tuple[str, str | None]] = []

    def record(self, name):
        self.calls.append((name, get_correlation_id()))

    def names(self):
        return [c[0] for c in self.calls]


class FakeReservations(Recorder):
    name = "station-reservation-service"

    def __init__(self, fail_reserve: ServiceCallError | None = None, release_failures: int = 0):
        super().__init__()
        self.fail_reserve = fail_reserve
        self.release_failures = release_failures

    async def get_station(self, station_id):
        return copy.deepcopy(STATION)

    async def reserve(self, **kw):
        self.record("reserve")
        if self.fail_reserve:
            raise self.fail_reserve
        return {"reservation": {"status": "RESERVED"}, "replayed": False}

    async def release(self, saga_id, reason):
        self.record("release")
        if self.release_failures > 0:
            self.release_failures -= 1
            raise ServiceCallError(self.name, 503, "SERVICE_UNREACHABLE", "down", transient=True)
        return {"reservation": {"status": "RELEASED"}, "outcome": "RELEASED"}

    async def activate(self, saga_id):
        self.record("activate")
        return {"reservation": {"status": "ACTIVE"}, "replayed": False}

    async def complete(self, saga_id):
        self.record("complete")
        return {"reservation": {"status": "COMPLETED"}, "replayed": False}


class FakeBilling(Recorder):
    name = "billing-wallet-service"

    def __init__(self, fail_charge: ServiceCallError | None = None):
        super().__init__()
        self.fail_charge = fail_charge

    async def charge(self, **kw):
        self.record("charge")
        if self.fail_charge:
            raise self.fail_charge
        return {
            "charge": {
                "amount": 11.2,
                "currency": "USD",
                "balance_after": 88.8,
                "pricing": {"surge_multiplier": 1},
            },
            "replayed": False,
        }

    async def refund(self, saga_id, fleet_id, reason):
        self.record("refund")
        return {"refund": {"amount": 11.2}, "outcome": "REFUNDED"}


class FakeDispatch(Recorder):
    name = "energy-dispatch-service"

    def __init__(self, fail_start: ServiceCallError | None = None):
        super().__init__()
        self.fail_start = fail_start

    async def start(self, **kw):
        self.record("start")
        if self.fail_start:
            raise self.fail_start
        return {"session": {"status": "CHARGING"}, "replayed": False}

    async def abort(self, saga_id, reason):
        self.record("abort")
        return {"session": {"status": "ABORTED"}, "outcome": "ABORTED"}


class FakeFlags:
    def __init__(self, **flags):
        self.flags = flags

    def snapshot(self):
        return dict(self.flags)
