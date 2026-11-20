"""Pruebas de integración: contrato GraphQL + tablas DynamoDB + CloudWatch Logs reales (Floci)."""

import pytest

from tests.conftest import table

pytestmark = pytest.mark.integration


def test_environment_matches_tables(gql, env):
    data = gql("{ environment { name awsBackend tables logGroupPrefix } }")["environment"]
    assert data["name"] == env
    assert f"aegisvolt-reservations-{env}" in data["tables"]
    assert data["logGroupPrefix"] == f"/aegisvolt/{env}/"


def test_all_services_up(gql):
    health = gql("{ serviceHealth { name status } }")["serviceHealth"]
    assert {h["name"]: h["status"] for h in health} == {
        "station-reservation-service": "UP",
        "billing-wallet-service": "UP",
        "energy-dispatch-service": "UP",
    }


def test_database_per_service_tables_exist(dynamo):
    for logical in ("reservations", "billing", "dispatch", "sagas", "feature-flags"):
        status = dynamo.describe_table(TableName=table(logical))["Table"]["TableStatus"]
        assert status == "ACTIVE"


def test_stations_query_returns_connectors(gql):
    stations = gql("{ stations { id name availableConnectors connectors { id tier status powerKw } } }")[
        "stations"
    ]
    assert len(stations) >= 6
    tiers = {c["tier"] for s in stations for c in s["connectors"]}
    assert {"STANDARD", "FAST", "ULTRA"} <= tiers


def test_feature_flags_are_per_environment(gql, env):
    flags = gql("{ featureFlags { key enabled environment source } }")["featureFlags"]
    keys = {f["key"] for f in flags}
    assert keys == {
        "ENABLE_DYNAMIC_SURGE_PRICING",
        "ENABLE_FAST_CHARGE_BOOST",
        "SIMULATE_CHARGER_HARDWARE_FAULT",
    }
    assert all(f["environment"] == env for f in flags)


def test_price_quote_uses_billing(gql):
    quote = gql(
        '{ priceQuote(stationId: "BOG-NORTE", connectorId: "BOG-NORTE-C1", estimatedKwh: 10) '
        "{ tier total currency surgeMultiplier } }"
    )["priceQuote"]
    assert quote["tier"] == "FAST"
    assert quote["total"] > 0


def test_set_feature_flag_requires_admin_token(gql):
    import httpx

    from tests.conftest import GRAPHQL_URL

    body = httpx.post(
        GRAPHQL_URL,
        json={"query": 'mutation { setFeatureFlag(key: "ENABLE_FAST_CHARGE_BOOST", enabled: true) { key } }'},
    ).json()
    assert body.get("errors"), "sin X-Admin-Token la mutación debe fallar"


def test_logs_shipped_to_cloudwatch(gql, logs, env):
    gql("{ stations { id } }")
    import time

    time.sleep(3)  # el handler envía lotes cada 2 s
    group = f"/aegisvolt/{env}/station-reservation-service"
    streams = logs.describe_log_streams(logGroupName=group)["logStreams"]
    assert streams, f"no hay streams en {group}"
