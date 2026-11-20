"""Propagación del correlation_id entre servicios.

El orquestador SAGA usa el saga_id como correlation_id y lo envía en el header X-Correlation-ID a
cada microservicio. Este middleware lo lee, lo deja en un ContextVar (para que cada línea de log lo
incluya) y lo devuelve en la respuesta.
"""

from __future__ import annotations

import contextvars
import uuid

CORRELATION_HEADER = "X-Correlation-ID"
correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def get_correlation_id() -> str | None:
    return correlation_id_var.get()


def new_correlation_id() -> str:
    return str(uuid.uuid4())


class CorrelationIdMiddleware:
    """Middleware ASGI puro (funciona también para WebSockets de las subscriptions GraphQL)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(CORRELATION_HEADER.lower().encode(), b"").decode().strip()
        cid = incoming[:128] if incoming else new_correlation_id()
        token = correlation_id_var.set(cid)

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((CORRELATION_HEADER.lower().encode(), cid.encode()))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            correlation_id_var.reset(token)
