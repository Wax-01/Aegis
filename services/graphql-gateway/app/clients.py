"""Clientes HTTP hacia los microservicios.

Reintentos con backoff exponencial SOLO para errores transitorios (red / 5xx / 429). Reintentar un POST es
seguro porque todos los endpoints de la SAGA son idempotentes por saga_id.
Los errores 4xx son errores de negocio: se propagan de inmediato (sin reintento) con su código.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from aegis_common.correlation import CORRELATION_HEADER, get_correlation_id, new_correlation_id


class ServiceCallError(Exception):
    def __init__(
        self,
        service: str,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        transient: bool = False,
    ):
        super().__init__(f"[{service}] {code}: {message}")
        self.service = service
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        self.transient = transient


class ServiceClient:
    def __init__(
        self, name: str, base_url: str, timeout: float = 5.0, retries: int = 3, backoff: float = 0.2
    ):
        self.name = name
        self.retries = retries
        self.backoff = backoff
        # Sin keep-alive: kube-proxy balancea por CONEXIÓN TCP, no por petición. Con conexiones persistentes el
        # gateway queda pegado a los pods que existían al abrirlas y un canary nuevo nunca recibe tráfico.
        # Una conexión por petición deja que el Service reparta según el número de endpoints (canary ~20 %).
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=0),
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        retries: int | None = None,
    ) -> dict[str, Any]:
        attempts = retries if retries is not None else self.retries
        headers = {CORRELATION_HEADER: get_correlation_id() or new_correlation_id()}
        last_error: ServiceCallError | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = await self._http.request(method, path, json=json, params=params, headers=headers)
            except httpx.TransportError as exc:
                last_error = ServiceCallError(
                    self.name, 503, "SERVICE_UNREACHABLE", f"{exc.__class__.__name__}: {exc}", transient=True
                )
            else:
                if response.status_code < 400:
                    return response.json()
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                error = ServiceCallError(
                    self.name,
                    response.status_code,
                    body.get("error") or f"HTTP_{response.status_code}",
                    body.get("message") or response.text[:300],
                    body.get("details"),
                    transient=response.status_code >= 500 or response.status_code == 429,
                )
                if not error.transient:
                    raise error
                last_error = error
            if attempt < attempts:
                await asyncio.sleep(self.backoff * 2 ** (attempt - 1))
        assert last_error is not None
        raise last_error

    async def health(self) -> dict[str, Any]:
        return await self.request("GET", "/health", retries=1)

    async def aclose(self) -> None:
        await self._http.aclose()


class ReservationClient(ServiceClient):
    async def list_stations(self) -> list[dict]:
        return (await self.request("GET", "/stations"))["stations"]

    async def get_station(self, station_id: str) -> dict:
        return (await self.request("GET", f"/stations/{station_id}"))["station"]

    async def reserve(self, **payload) -> dict:
        return await self.request("POST", "/reservations", json=payload)

    async def release(self, saga_id: str, reason: str) -> dict:
        return await self.request("POST", f"/reservations/{saga_id}/release", json={"reason": reason})

    async def activate(self, saga_id: str) -> dict:
        return await self.request("POST", f"/reservations/{saga_id}/activate")

    async def complete(self, saga_id: str) -> dict:
        return await self.request("POST", f"/reservations/{saga_id}/complete")


class BillingClient(ServiceClient):
    async def list_wallets(self) -> list[dict]:
        return (await self.request("GET", "/wallets"))["wallets"]

    async def wallet(self, fleet_id: str) -> dict:
        return (await self.request("GET", f"/wallets/{fleet_id}"))["wallet"]

    async def transactions(self, fleet_id: str, limit: int = 50) -> list[dict]:
        return (await self.request("GET", f"/wallets/{fleet_id}/transactions", params={"limit": limit}))[
            "transactions"
        ]

    async def quote(self, **payload) -> dict:
        return (await self.request("POST", "/quotes", json=payload))["quote"]

    async def charge(self, **payload) -> dict:
        return await self.request("POST", "/charges", json=payload)

    async def refund(self, saga_id: str, fleet_id: str, reason: str) -> dict:
        return await self.request(
            "POST", f"/charges/{saga_id}/refund", json={"fleet_id": fleet_id, "reason": reason}
        )

    async def top_up(self, fleet_id: str, amount: float) -> dict:
        return (await self.request("POST", f"/wallets/{fleet_id}/topup", json={"amount": amount}))["wallet"]


class DispatchClient(ServiceClient):
    async def start(self, **payload) -> dict:
        return await self.request("POST", "/sessions", json=payload)

    async def abort(self, saga_id: str, reason: str) -> dict:
        return await self.request("POST", f"/sessions/{saga_id}/abort", json={"reason": reason})

    async def stop(self, saga_id: str) -> dict:
        return await self.request("POST", f"/sessions/{saga_id}/stop")

    async def session(self, saga_id: str) -> dict:
        return (await self.request("GET", f"/sessions/{saga_id}"))["session"]

    async def sessions(self, status: str | None = None) -> list[dict]:
        params = {"status": status} if status else None
        return (await self.request("GET", "/sessions", params=params))["sessions"]

    async def telemetry(self, saga_id: str, limit: int = 60) -> list[dict]:
        return (await self.request("GET", f"/sessions/{saga_id}/telemetry", params={"limit": limit}))[
            "telemetry"
        ]
