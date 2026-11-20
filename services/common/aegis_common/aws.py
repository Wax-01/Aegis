"""Fábrica de clientes boto3 apuntando a AWS real o a Floci (AWS_ENDPOINT_URL)."""

from __future__ import annotations

import boto3
from botocore.config import Config

from .config import Settings

_BOTO_CONFIG = Config(
    retries={"max_attempts": 4, "mode": "standard"},
    connect_timeout=2,
    read_timeout=5,
)


def boto_client(service: str, settings: Settings):
    return boto3.client(
        service,
        region_name=settings.region,
        endpoint_url=settings.aws_endpoint_url,
        config=_BOTO_CONFIG,
    )
