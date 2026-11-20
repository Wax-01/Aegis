"""Configuración por ambiente estático (dev / test / prod).

El mismo artefacto (imagen Docker) se despliega en los tres ambientes; lo único que cambia es
la variable AEGIS_ENV, de la cual se derivan nombres de tablas y grupos de logs. Esto replica en la
aplicación la misma convención que Terraform aplica con ${terraform.workspace}.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass

PROJECT = "aegisvolt"
VALID_ENVS = ("dev", "test", "prod")


def env_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    service_name: str
    env: str
    region: str
    aws_endpoint_url: str | None
    version: str
    track: str  # stable | canary  (estrategia Canary en Kubernetes)
    instance_id: str
    cloudwatch_logs_enabled: bool
    seed_demo_data: bool
    log_level: str

    def table_name(self, logical_name: str) -> str:
        """aegisvolt-<logical>-<env>, ej. aegisvolt-reservations-dev.

        Se permite override explícito (TABLE_RESERVATIONS=...) para pruebas aisladas.
        """
        override = os.getenv(f"TABLE_{logical_name.upper().replace('-', '_')}")
        return override or f"{PROJECT}-{logical_name}-{self.env}"

    @property
    def log_group(self) -> str:
        """/aegisvolt/<env>/<servicio> — grupos de CloudWatch diferenciados por ambiente."""
        return f"/{PROJECT}/{self.env}/{self.service_name}"


def load_settings(service_name: str) -> Settings:
    env = os.getenv("AEGIS_ENV", "dev").strip().lower()
    if env not in VALID_ENVS:
        raise RuntimeError(f"AEGIS_ENV inválido '{env}'. Valores permitidos: {', '.join(VALID_ENVS)}")
    return Settings(
        service_name=service_name,
        env=env,
        region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
        aws_endpoint_url=os.getenv("AWS_ENDPOINT_URL") or None,
        version=os.getenv("APP_VERSION", "local"),
        track=os.getenv("DEPLOY_TRACK", "stable"),
        instance_id=os.getenv("POD_NAME") or socket.gethostname(),
        cloudwatch_logs_enabled=env_bool(os.getenv("CLOUDWATCH_LOGS_ENABLED"), True),
        seed_demo_data=env_bool(os.getenv("SEED_DEMO_DATA"), True),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
