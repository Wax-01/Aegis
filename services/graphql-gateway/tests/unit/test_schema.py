from pathlib import Path

from app.schema import schema

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "schema.graphql"


def test_schema_exposes_contract():
    sdl = schema.as_str()
    for fragment in (
        "reserveAndActivateCharge(",
        "stationsLive(",
        "sagaLive(",
        "featureFlags:",
        "enum SagaStatus",
        "COMPENSATION_FAILED",
    ):
        assert fragment in sdl


def test_committed_schema_is_up_to_date():
    """El SDL versionado (contrato con el frontend) debe coincidir con el generado por el código."""
    assert SCHEMA_FILE.exists(), (
        "Genera el SDL: strawberry export-schema app.schema:schema --output schema.graphql"
    )
    assert SCHEMA_FILE.read_text(encoding="utf-8").strip() == schema.as_str().strip()
