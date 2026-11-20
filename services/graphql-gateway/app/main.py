"""graphql-gateway: capa de agregación GraphQL + orquestador SAGA."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from aegis_common.app_factory import create_app
from aegis_common.config import load_settings
from aegis_common.logging_setup import configure_logging, get_logger, log_event
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from strawberry.fastapi import GraphQLRouter
from strawberry.subscriptions import GRAPHQL_TRANSPORT_WS_PROTOCOL, GRAPHQL_WS_PROTOCOL

from .container import build_container, get_container, set_container
from .schema import schema

settings = load_settings("graphql-gateway")
configure_logging(settings)
logger = get_logger("gateway")


@asynccontextmanager
async def lifespan(_app):
    container = build_container(settings)
    set_container(container)
    reconciler = asyncio.create_task(container.reconciler.run_forever())
    log_event(
        logger, "gateway.started", environment=settings.env, version=settings.version, track=settings.track
    )
    yield
    reconciler.cancel()
    await container.aclose()
    set_container(None)


app = create_app(
    settings,
    title="AegisVolt GraphQL Gateway",
    description="Esquema unificado + orquestación SAGA",
    lifespan=lifespan,
    include_ready=False,  # el gateway define su propio /ready (tabla de sagas + microservicios)
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID"],
)

graphql_router = GraphQLRouter(
    schema,
    subscription_protocols=[GRAPHQL_TRANSPORT_WS_PROTOCOL, GRAPHQL_WS_PROTOCOL],
    graphql_ide="graphiql",
)
app.include_router(graphql_router, prefix="/graphql")


@app.get("/ready", tags=["ops"], include_in_schema=False)
async def gateway_ready():
    """Readiness del gateway: su tabla de sagas + los tres microservicios responden."""
    container = get_container()
    checks: dict[str, str] = {}
    try:
        status = await asyncio.to_thread(
            lambda: container.dynamo.describe_table(TableName=container.store.table)["Table"]["TableStatus"]
        )
        checks[container.store.table] = status
    except Exception as exc:  # noqa: BLE001
        checks[container.store.table] = f"ERROR: {exc.__class__.__name__}"
    for client in container.services:
        try:
            await client.health()
            checks[client.name] = "UP"
        except Exception as exc:  # noqa: BLE001
            checks[client.name] = f"DOWN: {exc}"
    healthy = all(v in ("ACTIVE", "UP") for v in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ready" if healthy else "not_ready", "checks": checks},
    )
