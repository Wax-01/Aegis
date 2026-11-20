from datetime import datetime
from decimal import Decimal

import pytest
from aegis_common.errors import ConflictError, DomainError
from aegis_common.tables import create_table
from app import pricing
from app.repository import BillingRepository

TABLE = "aegisvolt-billing-unittest"
FLEET = "FLEET-TEST"


@pytest.fixture
def repo(dynamo):
    create_table(dynamo, "billing", TABLE)
    repository = BillingRepository(dynamo, TABLE)
    repository.seed(
        [
            {"fleet_id": FLEET, "name": "Test", "balance": 100},
            {"fleet_id": "FLEET-POOR", "name": "Poor", "balance": 4.5},
        ]
    )
    return repository


def charge(repo, saga="saga-test-0001", fleet=FLEET, amount="25.50"):
    return repo.charge(saga_id=saga, fleet_id=fleet, amount=Decimal(amount), pricing={"currency": "USD"})


def test_charge_debits_wallet(repo):
    tx, replayed = charge(repo)
    assert replayed is False
    assert tx["amount"] == Decimal("25.50")
    assert repo.get_wallet(FLEET)["balance"] == Decimal("74.50")


def test_charge_is_idempotent(repo):
    charge(repo)
    _, replayed = charge(repo)
    assert replayed is True
    assert repo.get_wallet(FLEET)["balance"] == Decimal("74.50")  # solo se descontó una vez


def test_insufficient_funds_does_not_touch_balance(repo):
    with pytest.raises(DomainError) as exc:
        charge(repo, fleet="FLEET-POOR", amount="10")
    assert exc.value.code == "INSUFFICIENT_FUNDS"
    assert exc.value.status_code == 402
    assert repo.get_wallet("FLEET-POOR")["balance"] == Decimal("4.50")


def test_refund_restores_balance_and_is_idempotent(repo):
    charge(repo)
    refund, outcome = repo.refund(saga_id="saga-test-0001", fleet_id=FLEET, reason="ACTIVATE_CHARGER:FAULT")
    assert outcome == "REFUNDED"
    assert refund["amount"] == Decimal("25.50")
    assert repo.get_wallet(FLEET)["balance"] == Decimal("100.00")

    _, outcome_again = repo.refund(saga_id="saga-test-0001", fleet_id=FLEET, reason="retry")
    assert outcome_again == "REPLAY"
    assert repo.get_wallet(FLEET)["balance"] == Decimal("100.00")  # no se reembolsa dos veces


def test_refund_before_charge_writes_tombstone_and_blocks_late_charge(repo):
    _, outcome = repo.refund(saga_id="saga-late-0001", fleet_id=FLEET, reason="timeout")
    assert outcome == "TOMBSTONE"
    with pytest.raises(ConflictError) as exc:
        charge(repo, saga="saga-late-0001")
    assert exc.value.code == "SAGA_ALREADY_COMPENSATED"
    assert repo.get_wallet(FLEET)["balance"] == Decimal("100.00")


def test_transactions_history_contains_charge_and_refund(repo):
    charge(repo)
    repo.refund(saga_id="saga-test-0001", fleet_id=FLEET, reason="x")
    types = {t["tx_type"] for t in repo.list_transactions(FLEET)}
    assert types == {"CHARGE", "REFUND"}


@pytest.mark.parametrize(
    ("hour", "surge_enabled", "expected"),
    [(18, True, Decimal("1.50")), (11, True, Decimal("1.15")), (18, False, Decimal("1.00"))],
)
def test_surge_pricing_flag(hour, surge_enabled, expected):
    now = datetime(2026, 11, 10, hour, 0, tzinfo=pricing.TZ)
    q = pricing.quote(
        power_kw=150, estimated_kwh=40, fast_charge_boost=False, surge_enabled=surge_enabled, now=now
    )
    assert q["surge_multiplier"] == expected
    assert q["total"] == (Decimal("0.28") * 40 * expected).quantize(Decimal("0.01"))


def test_boost_fee_applied():
    now = datetime(2026, 11, 10, 11, 0, tzinfo=pricing.TZ)
    q = pricing.quote(power_kw=350, estimated_kwh=10, fast_charge_boost=True, surge_enabled=False, now=now)
    assert q["tier"] == "ULTRA"
    assert q["boost_fee"] == Decimal("1.20")
    assert q["total"] == Decimal("4.80")
