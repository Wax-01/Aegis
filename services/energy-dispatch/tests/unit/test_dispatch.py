import random
from datetime import timedelta

import pytest
from aegis_common.dynamo import utcnow
from aegis_common.errors import ConflictError
from aegis_common.tables import create_table
from app.repository import DispatchRepository

TABLE = "aegisvolt-dispatch-unittest"


@pytest.fixture
def repo(dynamo):
    create_table(dynamo, "dispatch", TABLE)
    return DispatchRepository(dynamo, TABLE, rng=random.Random(7))


def start(repo, saga="saga-test-0001", fault=False, target=40):
    return repo.start(
        saga_id=saga,
        station_id="BOG-NORTE",
        connector_id="BOG-NORTE-C1",
        fleet_id="FLEET-TEST",
        vehicle_id="VAN-001",
        power_kw=150,
        target_kwh=target,
        simulate_fault=fault,
    )


def test_start_session_is_charging_and_idempotent(repo):
    session, replayed = start(repo)
    assert session["status"] == "CHARGING"
    assert replayed is False
    _, replayed = start(repo)
    assert replayed is True


def test_hardware_fault_flag_faults_session(repo):
    with pytest.raises(ConflictError) as exc:
        start(repo, fault=True)
    assert exc.value.code == "CHARGER_HARDWARE_FAULT"
    assert repo.get_session("saga-test-0001")["status"] == "FAULTED"
    # Reintento idempotente: misma decisión aunque la flag ya no esté activa.
    with pytest.raises(ConflictError):
        start(repo, fault=False)


def test_abort_before_start_blocks_late_activation(repo):
    _, outcome = repo.abort("saga-late-0001", "timeout")
    assert outcome == "TOMBSTONE"
    with pytest.raises(ConflictError) as exc:
        start(repo, saga="saga-late-0001")
    assert exc.value.code == "SESSION_ABORTED"


def test_abort_active_session(repo):
    start(repo)
    session, outcome = repo.abort("saga-test-0001", "recovery")
    assert outcome == "ABORTED"
    assert session["status"] == "ABORTED"


def test_telemetry_tick_accumulates_energy_until_completed(repo):
    start(repo, target=40)
    written = repo.telemetry_tick(interval_s=3, speed=20, now=utcnow() + timedelta(seconds=30))
    assert written == 1
    mid = repo.get_session("saga-test-0001")
    assert 0 < float(mid["energy_kwh"]) < 40
    assert mid["status"] == "CHARGING"

    repo.telemetry_tick(interval_s=3, speed=20, now=utcnow() + timedelta(seconds=120))
    done = repo.get_session("saga-test-0001")
    assert done["status"] == "COMPLETED"
    assert float(done["energy_kwh"]) == pytest.approx(40, abs=0.01)
    assert len(repo.telemetry("saga-test-0001")) == 2


def test_stop_session(repo):
    start(repo)
    session, replayed = repo.stop("saga-test-0001")
    assert session["status"] == "STOPPED"
    assert replayed is False
