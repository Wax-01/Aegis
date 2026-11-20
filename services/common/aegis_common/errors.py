"""Errores de dominio que se traducen a respuestas HTTP con un código de negocio estable.

El orquestador SAGA decide si compensar según `code` y si el error es transitorio (5xx / red) o de
negocio (4xx): un error de negocio significa "el paso NO se aplicó"; uno transitorio significa
"no sé si se aplicó", y por eso también se compensa (las compensaciones son idempotentes).
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status_code: int = 400
    code: str = "DOMAIN_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}


class NotFoundError(DomainError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(DomainError):
    status_code = 409
    code = "CONFLICT"
