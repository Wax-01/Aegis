"""Vocabulario de dominio compartido (solo constantes, sin lógica de negocio de un servicio)."""

from __future__ import annotations

from decimal import Decimal


def connector_tier(power_kw: float | Decimal) -> str:
    power = float(power_kw)
    if power >= 300:
        return "ULTRA"
    if power >= 50:
        return "FAST"
    return "STANDARD"
