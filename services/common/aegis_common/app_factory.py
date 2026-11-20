"""Construcción homogénea de las apps FastAPI: middleware, errores, health/readiness y logs de acceso."""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .correlation import CorrelationIdMiddleware, get_correlation_id
from .errors import DomainError
from .logging_setup import get_logger, log_event

_SILENT_PATHS = {"/health", "/ready"}


class AccessLogMiddleware:
    """Registra cada petición HTTP como evento `http.request` (insumo de la métrica de error del canary)."""

    def __init__(self, app, logger: logging.Logger):
        self.app = app
        self.logger = logger

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in _SILENT_PATHS:
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = {"code": 500}

        async def capture(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            code = status["code"]
            log_event(
                self.logger,
                "http.request",
                level=logging.ERROR if code >= 500 else logging.INFO,
                method=scope.get("method"),
                path=scope.get("path"),
                status=code,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )


class FaultInjectionMiddleware:
    """Inyección de fallos para demostrar el ROLLBACK AUTOMÁTICO del canary.

    Con FAULT_INJECTION_HTTP_500_RATE=0.5 la mitad de las peticiones (excepto health) responden 500.
    El script de canary solo lo activa en el Deployment canary cuando se pide (--inject-canary-error-rate).
    """

    def __init__(self, app, rate: float):
        self.app = app
        self.rate = rate

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") not in _SILENT_PATHS and random.random() < self.rate:
            response = JSONResponse(
                status_code=500,
                content={"error": "INJECTED_FAULT", "message": "fault injection (canary demo)"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(
    settings: Settings,
    *,
    title: str,
    description: str = "",
    lifespan=None,
    dynamo_client=None,
    ready_tables: Sequence[str] = (),
    include_ready: bool = True,
) -> FastAPI:
    app = FastAPI(title=title, description=description, version=settings.version, lifespan=lifespan)
    logger = get_logger("http")

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        log_event(
            logger,
            "domain.error",
            level=logging.WARNING,
            code=exc.code,
            status=exc.status_code,
            error=exc.message,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.code,
                "message": exc.message,
                "details": exc.details,
                "correlation_id": get_correlation_id(),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.error(
            "unhandled.exception",
            exc_info=exc,
            extra={"fields": {"event": "unhandled.exception", "path": request.url.path}},
        )
        return JSONResponse(
            status_code=500,
            content={"error": "INTERNAL_ERROR", "message": str(exc), "correlation_id": get_correlation_id()},
        )

    @app.get("/health", tags=["ops"])
    def health():
        """Liveness: el proceso responde."""
        return {
            "status": "ok",
            "service": settings.service_name,
            "environment": settings.env,
            "version": settings.version,
            "track": settings.track,
        }

    def ready():
        """Readiness: las tablas DynamoDB de este servicio son accesibles."""
        checks = {}
        healthy = True
        for table in ready_tables:
            try:
                status = dynamo_client.describe_table(TableName=table)["Table"].get("TableStatus", "UNKNOWN")
                checks[table] = status
                healthy = healthy and status == "ACTIVE"
            except Exception as exc:  # noqa: BLE001
                checks[table] = f"ERROR: {exc.__class__.__name__}"
                healthy = False
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ready" if healthy else "not_ready", "tables": checks},
        )

    if include_ready:
        app.add_api_route("/ready", ready, methods=["GET"], tags=["ops"])

    # Orden: el último agregado es el más externo -> CorrelationId envuelve al AccessLog, que envuelve
    # a la inyección de fallos (así los 500 inyectados quedan registrados como http.request status=500).
    fault_rate = float(os.getenv("FAULT_INJECTION_HTTP_500_RATE", "0") or 0)
    if fault_rate > 0:
        app.add_middleware(FaultInjectionMiddleware, rate=fault_rate)
    app.add_middleware(AccessLogMiddleware, logger=logger)
    app.add_middleware(CorrelationIdMiddleware)
    return app
