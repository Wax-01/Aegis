"""Logs estructurados en JSON enviados a stdout y a Amazon CloudWatch Logs.

Cada línea incluye: timestamp, level, service, environment, version, track (stable|canary),
correlation_id (= saga_id en el flujo de carga), event y campos adicionales.

Grupo de logs: /aegisvolt/<env>/<servicio>  (creado por Terraform, módulo observability).
Stream:        <track>-<pod>

El canary deployment usa exactamente estos campos: filtra en CloudWatch por
{ $.track = "canary" && $.event = "http.request" } para calcular la tasa de error de la versión nueva.
"""

from __future__ import annotations

import contextlib
import json
import logging
import queue
import sys
import threading
import time
from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .correlation import get_correlation_id

ROOT_LOGGER = "aegisvolt"


class JsonFormatter(logging.Formatter):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.settings.service_name,
            "environment": self.settings.env,
            "version": self.settings.version,
            "track": self.settings.track,
            "instance": self.settings.instance_id,
            "correlation_id": getattr(record, "correlation_id", None) or get_correlation_id(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            # Los campos base (service, environment, track, correlation_id...) no se pueden sobrescribir:
            # son las dimensiones de búsqueda en CloudWatch.
            payload = {**fields, **payload}
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class CloudWatchLogsHandler(logging.Handler):
    """Envía logs a CloudWatch en lotes desde un hilo en segundo plano (no bloquea las peticiones)."""

    def __init__(self, client, log_group: str, log_stream: str, flush_interval: float = 2.0):
        super().__init__()
        self.client = client
        self.log_group = log_group
        self.log_stream = log_stream
        self.flush_interval = flush_interval
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=20_000)
        self._stream_ready = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="cloudwatch-logs", daemon=True)
        self._thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._queue.put_nowait({"timestamp": int(record.created * 1000), "message": self.format(record)})
        except queue.Full:
            pass  # Preferimos perder logs antes que tumbar el servicio.
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def _ensure_stream(self) -> None:
        if self._stream_ready:
            return
        try:
            self.client.create_log_stream(logGroupName=self.log_group, logStreamName=self.log_stream)
        except self.client.exceptions.ResourceAlreadyExistsException:
            pass
        except self.client.exceptions.ResourceNotFoundException:
            # El grupo debería existir (Terraform). Si no, lo creamos para no perder trazas en modo local.
            with contextlib.suppress(self.client.exceptions.ResourceAlreadyExistsException):
                self.client.create_log_group(logGroupName=self.log_group)
            self.client.create_log_stream(logGroupName=self.log_group, logStreamName=self.log_stream)
        self._stream_ready = True

    def _drain(self, max_items: int = 500) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []
        while len(batch) < max_items:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def _send(self, batch: list[dict[str, Any]]) -> None:
        if not batch:
            return
        batch.sort(key=lambda e: e["timestamp"])
        for attempt in range(2):
            try:
                self._ensure_stream()
                self.client.put_log_events(
                    logGroupName=self.log_group, logStreamName=self.log_stream, logEvents=batch
                )
                return
            except Exception as exc:  # noqa: BLE001
                self._stream_ready = False
                if attempt == 1:
                    sys.stderr.write(f"[cloudwatch-logs] no se pudieron enviar {len(batch)} eventos: {exc}\n")

    def _run(self) -> None:
        while not self._stop.is_set():
            time.sleep(self.flush_interval)
            self._send(self._drain())

    def flush(self) -> None:
        while not self._queue.empty():
            self._send(self._drain())

    def close(self) -> None:
        self._stop.set()
        self.flush()
        super().close()


def configure_logging(settings: Settings, cloudwatch_client=None) -> logging.Logger:
    logger = logging.getLogger(ROOT_LOGGER)
    logger.handlers.clear()
    logger.setLevel(settings.log_level)
    logger.propagate = False

    formatter = JsonFormatter(settings)
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(formatter)
    logger.addHandler(stdout)

    if settings.cloudwatch_logs_enabled:
        if cloudwatch_client is None:
            from .aws import boto_client

            cloudwatch_client = boto_client("logs", settings)
        stream = f"{settings.track}-{settings.instance_id}".replace(":", "-").replace("*", "-")
        cw = CloudWatchLogsHandler(cloudwatch_client, settings.log_group, stream)
        cw.setFormatter(formatter)
        logger.addHandler(cw)

    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Log estructurado: `event` es un nombre estable (ej. saga.compensated) usado por filtros métricos."""
    logger.log(level, event, extra={"fields": {"event": event, **fields}})
