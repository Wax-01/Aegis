import json
import logging

from aegis_common.config import Settings
from aegis_common.correlation import correlation_id_var
from aegis_common.logging_setup import JsonFormatter

SETTINGS = Settings(
    service_name="graphql-gateway",
    env="test",
    region="us-east-1",
    aws_endpoint_url=None,
    version="abc123",
    track="canary",
    instance_id="pod-1",
    cloudwatch_logs_enabled=False,
    seed_demo_data=False,
    log_level="INFO",
)


def format_record(fields: dict) -> dict:
    record = logging.LogRecord("aegisvolt.test", logging.INFO, __file__, 1, "saga.step.succeeded", None, None)
    record.fields = fields
    return json.loads(JsonFormatter(SETTINGS).format(record))


def test_log_line_has_traceability_fields():
    token = correlation_id_var.set("saga-123")
    try:
        line = format_record({"event": "saga.step.succeeded", "step": "CHARGE_WALLET"})
    finally:
        correlation_id_var.reset(token)
    assert line["correlation_id"] == "saga-123"
    assert line["environment"] == "test"
    assert line["service"] == "graphql-gateway"
    assert line["track"] == "canary"
    assert line["event"] == "saga.step.succeeded"
    assert line["step"] == "CHARGE_WALLET"


def test_extra_fields_cannot_override_base_dimensions():
    line = format_record({"event": "x", "service": "otro-servicio", "environment": "prod", "track": "stable"})
    assert line["service"] == "graphql-gateway"
    assert line["environment"] == "test"
    assert line["track"] == "canary"
