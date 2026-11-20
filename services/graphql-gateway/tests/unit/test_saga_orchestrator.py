import asyncio

import pytest
from app.clients import ServiceCallError
from app.saga import ChargeRequest, ChargeSagaOrchestrator, SagaValidationError

from .fakes import FakeBilling, FakeDispatch, FakeFlags, FakeReservations, FakeStore

REQUEST = ChargeRequest(
    fleet_id="FLEET-TEST",
    vehicle_id="VAN-001",
    station_id="BOG-NORTE",
    connector_id="BOG-NORTE-C1",
    estimated_kwh=40,
)

INSUFFICIENT = ServiceCallError("billing-wallet-service", 402, "INSUFFICIENT_FUNDS", "saldo insuficiente")
HW_FAULT = ServiceCallError("energy-dispatch-service", 409, "CHARGER_HARDWARE_FAULT", "ground fault")
TIMEOUT = ServiceCallError("billing-wallet-service", 503, "SERVICE_UNREACHABLE", "timeout", transient=True)


def build(reservations=None, billing=None, dispatch=None):
    store = FakeStore()
    orchestrator = ChargeSagaOrchestrator(
        store=store,
        reservations=reservations or FakeReservations(),
        billing=billing or FakeBilling(),
        dispatch=dispatch or FakeDispatch(),
        flags=FakeFlags(SIMULATE_CHARGER_HARDWARE_FAULT=False),
        environment="test",
        compensation_attempts=3,
        compensation_backoff_s=0,
    )
    return orchestrator, store


def run(orchestrator, request=REQUEST):
    return asyncio.run(orchestrator.run(request))


def actions(saga):
    return [(s["name"], s["status"]) for s in saga["steps"] if s["type"] == "ACTION"]


def compensations(saga):
    return [s["name"] for s in saga["steps"] if s["type"] == "COMPENSATION"]


def test_happy_path_completes_three_steps():
    reservations = FakeReservations()
    orchestrator, _ = build(reservations=reservations)
    saga = run(orchestrator)
    assert saga["status"] == "COMPLETED"
    assert actions(saga) == [
        ("RESERVE_CONNECTOR", "SUCCEEDED"),
        ("CHARGE_WALLET", "SUCCEEDED"),
        ("ACTIVATE_CHARGER", "SUCCEEDED"),
    ]
    assert compensations(saga) == []
    assert saga["charging_status"] == "ACTIVE"
    assert "activate" in reservations.names()


def test_correlation_id_is_saga_id_in_every_call():
    reservations, billing, dispatch = FakeReservations(), FakeBilling(), FakeDispatch()
    orchestrator, _ = build(reservations, billing, dispatch)
    saga = run(orchestrator)
    for recorder in (reservations, billing, dispatch):
        assert {cid for _, cid in recorder.calls} == {saga["saga_id"]}


def test_insufficient_funds_releases_connector_only():
    billing = FakeBilling(fail_charge=INSUFFICIENT)
    dispatch = FakeDispatch()
    orchestrator, _ = build(billing=billing, dispatch=dispatch)
    saga = run(orchestrator)
    assert saga["status"] == "COMPENSATED"
    assert saga["failure_code"] == "INSUFFICIENT_FUNDS"
    assert compensations(saga) == ["RELEASE_CONNECTOR"]
    assert "refund" not in billing.names()
    assert dispatch.calls == []


def test_hardware_fault_refunds_then_releases():
    reservations, billing, dispatch = FakeReservations(), FakeBilling(), FakeDispatch(fail_start=HW_FAULT)
    orchestrator, _ = build(reservations=reservations, billing=billing, dispatch=dispatch)
    saga = run(orchestrator)
    assert saga["status"] == "COMPENSATED"
    assert saga["failure_step"] == "ACTIVATE_CHARGER"
    # Orden inverso: primero billing (reembolso) y luego reservations (liberar conector).
    assert compensations(saga) == ["REFUND_WALLET", "RELEASE_CONNECTOR"]
    # Falla de negocio (409) = el cargador NO arrancó: no hace falta abortar la sesión.
    assert "abort" not in dispatch.names()
    assert "activate" not in reservations.names()


def test_transient_failure_also_compensates_the_uncertain_step():
    billing = FakeBilling(fail_charge=TIMEOUT)
    orchestrator, _ = build(billing=billing)
    saga = run(orchestrator)
    assert saga["status"] == "COMPENSATED"
    assert compensations(saga) == ["REFUND_WALLET", "RELEASE_CONNECTOR"]


def test_business_failure_on_first_step_needs_no_compensation():
    unavailable = ServiceCallError("station-reservation-service", 409, "CONNECTOR_UNAVAILABLE", "ocupado")
    orchestrator, _ = build(reservations=FakeReservations(fail_reserve=unavailable))
    saga = run(orchestrator)
    assert saga["status"] == "FAILED"
    assert compensations(saga) == []


def test_compensation_exhausted_then_recovered():
    reservations = FakeReservations(release_failures=3)
    orchestrator, store = build(reservations=reservations, billing=FakeBilling(fail_charge=INSUFFICIENT))
    saga = run(orchestrator)
    assert saga["status"] == "COMPENSATION_FAILED"

    recovered = asyncio.run(orchestrator.recover(saga["saga_id"]))
    assert recovered["status"] == "COMPENSATED"


def test_recover_is_noop_for_completed_saga():
    orchestrator, _ = build()
    saga = run(orchestrator)
    assert asyncio.run(orchestrator.recover(saga["saga_id"]))["status"] == "COMPLETED"


def test_validation_rejects_invalid_energy():
    orchestrator, _ = build()
    bad = ChargeRequest(**{**REQUEST.__dict__, "estimated_kwh": 0})
    with pytest.raises(SagaValidationError):
        run(orchestrator, bad)


def test_flags_snapshot_is_recorded():
    orchestrator, _ = build()
    saga = run(orchestrator)
    assert saga["flags_snapshot"] == {"SIMULATE_CHARGER_HARDWARE_FAULT": False}
