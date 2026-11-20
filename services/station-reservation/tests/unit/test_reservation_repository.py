import pytest
from aegis_common.errors import ConflictError, DomainError
from aegis_common.tables import create_table
from app.repository import ReservationRepository
from app.seed import STATIONS

TABLE = "aegisvolt-reservations-unittest"


@pytest.fixture
def repo(dynamo):
    create_table(dynamo, "reservations", TABLE)
    repository = ReservationRepository(dynamo, TABLE)
    repository.seed(STATIONS)
    return repository


def reserve(
    repo, saga="saga-test-0001", connector="BOG-NORTE-C1", station="BOG-NORTE", boost=False, enabled=False
):
    return repo.reserve(
        saga_id=saga,
        station_id=station,
        connector_id=connector,
        fleet_id="FLEET-ANDES-EXPRESS",
        vehicle_id="VAN-001",
        fast_charge_boost=boost,
        boost_feature_enabled=enabled,
    )


def test_seed_is_idempotent(repo):
    assert repo.seed(STATIONS) == 0
    assert len(repo.list_stations()) == len(STATIONS)


def test_reserve_locks_connector(repo):
    reservation, replayed = reserve(repo)
    assert reservation["status"] == "RESERVED"
    assert replayed is False
    connector = repo.get_connector("BOG-NORTE", "BOG-NORTE-C1")
    assert connector["status"] == "RESERVED"
    assert connector["saga_id"] == "saga-test-0001"


def test_reserve_is_idempotent_for_same_saga(repo):
    reserve(repo)
    _, replayed = reserve(repo)
    assert replayed is True
    assert repo.get_connector("BOG-NORTE", "BOG-NORTE-C1")["version"] == 1  # se bloqueó una sola vez


def test_other_saga_cannot_take_reserved_connector(repo):
    reserve(repo)
    with pytest.raises(ConflictError) as exc:
        reserve(repo, saga="saga-test-0002")
    assert exc.value.code == "CONNECTOR_UNAVAILABLE"


def test_faulted_connector_is_not_reservable(repo):
    with pytest.raises(ConflictError) as exc:
        reserve(repo, station="SCL-PUDAHUEL", connector="SCL-PUDAHUEL-C3")
    assert exc.value.code == "CONNECTOR_UNAVAILABLE"


def test_release_compensation_frees_connector_and_is_idempotent(repo):
    reserve(repo)
    reservation, outcome = repo.release("saga-test-0001", "CHARGE_WALLET:INSUFFICIENT_FUNDS")
    assert outcome == "RELEASED"
    assert reservation["status"] == "RELEASED"
    connector = repo.get_connector("BOG-NORTE", "BOG-NORTE-C1")
    assert connector["status"] == "AVAILABLE"
    assert "saga_id" not in connector

    _, outcome_again = repo.release("saga-test-0001", "retry")
    assert outcome_again == "REPLAY"


def test_release_before_reserve_writes_tombstone_that_blocks_late_reserve(repo):
    _, outcome = repo.release("saga-late-0001", "timeout")
    assert outcome == "TOMBSTONE"
    reservation, replayed = reserve(repo, saga="saga-late-0001")
    assert replayed is True
    assert reservation["status"] == "RELEASED"
    assert repo.get_connector("BOG-NORTE", "BOG-NORTE-C1")["status"] == "AVAILABLE"


def test_ultra_connector_requires_boost(repo):
    with pytest.raises(DomainError) as exc:
        reserve(repo, connector="BOG-NORTE-C3")
    assert exc.value.code == "ULTRA_REQUIRES_BOOST"


def test_boost_rejected_when_flag_disabled(repo):
    with pytest.raises(DomainError) as exc:
        reserve(repo, connector="BOG-NORTE-C3", boost=True, enabled=False)
    assert exc.value.code == "FEATURE_DISABLED"


def test_boost_allows_ultra_when_flag_enabled(repo):
    reservation, _ = reserve(repo, connector="BOG-NORTE-C3", boost=True, enabled=True)
    assert reservation["status"] == "RESERVED"


def test_activate_and_complete_lifecycle(repo):
    reserve(repo)
    activated, _ = repo.activate("saga-test-0001")
    assert activated["status"] == "ACTIVE"
    assert repo.get_connector("BOG-NORTE", "BOG-NORTE-C1")["status"] == "CHARGING"
    _, replayed = repo.activate("saga-test-0001")
    assert replayed is True

    completed, _ = repo.complete("saga-test-0001")
    assert completed["status"] == "COMPLETED"
    assert repo.get_connector("BOG-NORTE", "BOG-NORTE-C1")["status"] == "AVAILABLE"
