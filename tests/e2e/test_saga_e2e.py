"""E2E: flujo completo de la SAGA a través de GraphQL, verificando el estado final en DynamoDB.

Cubre los tres escenarios de la sustentación:
  1. Camino feliz (RESERVED -> CHARGE -> CHARGING).
  2. Fondos insuficientes  -> compensación en reservations.
  3. Falla física inyectada por flag -> compensación en billing y luego reservations.
"""

from __future__ import annotations

import time

import httpx
import pytest

from tests.conftest import table

pytestmark = pytest.mark.e2e

SAGA_FIELDS = """
  id status failureStep failureCode amount correlationId compensated
  steps { name type status service detail }
  flagsSnapshot { key enabled }
"""
RESERVE = f"""
mutation($input: ChargeRequestInput!) {{
  reserveAndActivateCharge(input: $input) {{ {SAGA_FIELDS} }}
}}"""
SET_FLAG = "mutation($k: String!, $e: Boolean!) { setFeatureFlag(key: $k, enabled: $e) { key enabled } }"
FLAG_CACHE_SECONDS = 4  # los servicios cachean flags ~3 s


def available_connector(gql, tier="FAST"):
    stations = gql("{ stations { id connectors { id tier status } } }")["stations"]
    for station in stations:
        for connector in station["connectors"]:
            if connector["tier"] == tier and connector["status"] == "AVAILABLE":
                return station["id"], connector["id"]
    pytest.fail(f"No hay conectores {tier} disponibles")


def run_saga(gql, fleet="FLEET-ANDES-EXPRESS", kwh=12.0):
    station_id, connector_id = available_connector(gql)
    saga = gql(
        RESERVE,
        {
            "input": {
                "fleetId": fleet,
                "vehicleId": "VAN-E2E",
                "stationId": station_id,
                "connectorId": connector_id,
                "estimatedKwh": kwh,
            }
        },
    )["reserveAndActivateCharge"]
    return saga, station_id, connector_id


def get_item(dynamo, logical, key):
    item = dynamo.get_item(TableName=table(logical), Key=key, ConsistentRead=True).get("Item")
    return item or {}


def connector_status(dynamo, station_id, connector_id):
    item = get_item(
        dynamo,
        "reservations",
        {"pk": {"S": f"STATION#{station_id}"}, "sk": {"S": f"CONNECTOR#{connector_id}"}},
    )
    return item["status"]["S"]


def wallet_balance(gql, fleet):
    return gql("query($f: ID!) { wallet(fleetId: $f) { balance } }", {"f": fleet})["wallet"]["balance"]


def compensations(saga):
    return [s["name"] for s in saga["steps"] if s["type"] == "COMPENSATION"]


def test_happy_path_reserves_charges_and_activates(gql, dynamo):
    saga, station_id, connector_id = run_saga(gql)
    assert saga["status"] == "COMPLETED", saga
    assert saga["correlationId"] == saga["id"]
    assert [s["name"] for s in saga["steps"]] == ["RESERVE_CONNECTOR", "CHARGE_WALLET", "ACTIVATE_CHARGER"]
    assert connector_status(dynamo, station_id, connector_id) == "CHARGING"

    charge = get_item(
        dynamo,
        "billing",
        {"pk": {"S": "WALLET#FLEET-ANDES-EXPRESS"}, "sk": {"S": f"TX#{saga['id']}#CHARGE"}},
    )
    assert charge["tx_type"]["S"] == "CHARGE"

    stopped = gql(
        "mutation($id: ID!) { stopChargingSession(sagaId: $id) { chargingStatus } }", {"id": saga["id"]}
    )["stopChargingSession"]
    assert stopped["chargingStatus"] == "FINISHED"
    assert connector_status(dynamo, station_id, connector_id) == "AVAILABLE"


def test_insufficient_funds_compensates_reservation(gql, dynamo):
    saga, station_id, connector_id = run_saga(gql, fleet="FLEET-SIN-FONDOS", kwh=50)
    assert saga["status"] == "COMPENSATED", saga
    assert saga["failureCode"] == "INSUFFICIENT_FUNDS"
    assert compensations(saga) == ["RELEASE_CONNECTOR"]
    assert connector_status(dynamo, station_id, connector_id) == "AVAILABLE"
    reservation = get_item(
        dynamo, "reservations", {"pk": {"S": f"RESERVATION#{saga['id']}"}, "sk": {"S": "META"}}
    )
    assert reservation["status"]["S"] == "RELEASED"


def test_hardware_fault_flag_triggers_full_rollback(gql, dynamo):
    fleet = "FLEET-PACIFICO-LOG"
    gql(SET_FLAG, {"k": "SIMULATE_CHARGER_HARDWARE_FAULT", "e": True}, admin=True)
    try:
        time.sleep(FLAG_CACHE_SECONDS)
        balance_before = wallet_balance(gql, fleet)
        saga, station_id, connector_id = run_saga(gql, fleet=fleet, kwh=10)

        assert saga["status"] == "COMPENSATED", saga
        assert saga["failureStep"] == "ACTIVATE_CHARGER"
        assert saga["failureCode"] == "CHARGER_HARDWARE_FAULT"
        assert compensations(saga) == ["REFUND_WALLET", "RELEASE_CONNECTOR"]
        assert {"key": "SIMULATE_CHARGER_HARDWARE_FAULT", "enabled": True} in saga["flagsSnapshot"]

        # Estado final en las tablas de cada servicio:
        assert wallet_balance(gql, fleet) == pytest.approx(balance_before)
        refund = get_item(
            dynamo, "billing", {"pk": {"S": f"WALLET#{fleet}"}, "sk": {"S": f"TX#{saga['id']}#REFUND"}}
        )
        assert refund["tx_type"]["S"] == "REFUND"
        assert connector_status(dynamo, station_id, connector_id) == "AVAILABLE"
        session = get_item(dynamo, "dispatch", {"pk": {"S": f"SESSION#{saga['id']}"}, "sk": {"S": "META"}})
        assert session["status"]["S"] == "FAULTED"
    finally:
        gql(SET_FLAG, {"k": "SIMULATE_CHARGER_HARDWARE_FAULT", "e": False}, admin=True)
        time.sleep(FLAG_CACHE_SECONDS)


def test_compensation_is_idempotent_when_replayed(gql):
    """Reenviar la misma compensación no reembolsa dos veces (llave de idempotencia = saga_id)."""
    import os

    billing_url = os.getenv("BILLING_URL", "http://127.0.0.1:8002")
    fleet = "FLEET-ANDES-EXPRESS"
    saga, *_ = run_saga(gql, fleet=fleet, kwh=5)
    assert saga["status"] == "COMPLETED"
    first = httpx.post(f"{billing_url}/charges/{saga['id']}/refund", json={"fleet_id": fleet}).json()
    balance = wallet_balance(gql, fleet)
    second = httpx.post(f"{billing_url}/charges/{saga['id']}/refund", json={"fleet_id": fleet}).json()
    assert first["outcome"] == "REFUNDED"
    assert second["outcome"] == "REPLAY"
    assert wallet_balance(gql, fleet) == pytest.approx(balance)
    gql("mutation($id: ID!) { stopChargingSession(sagaId: $id) { id } }", {"id": saga["id"]})
