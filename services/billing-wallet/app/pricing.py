"""Tarificación. ENABLE_DYNAMIC_SURGE_PRICING aplica un multiplicador en horas pico.

El precio lo calcula SIEMPRE billing (autoridad de cobro); el orquestador solo envía kWh estimados.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from aegis_common.domain import connector_tier

CURRENCY = "USD"
TZ = ZoneInfo("America/Bogota")
TIER_RATE = {"STANDARD": Decimal("0.22"), "FAST": Decimal("0.28"), "ULTRA": Decimal("0.36")}
BOOST_FEE_PER_KWH = Decimal("0.12")
PEAK_HOURS = frozenset({7, 8, 9, 17, 18, 19, 20, 21})
SURGE_PEAK = Decimal("1.50")
SURGE_OFF_PEAK = Decimal("1.15")


def quote(
    *,
    power_kw: float,
    estimated_kwh: float,
    fast_charge_boost: bool,
    surge_enabled: bool,
    now: datetime | None = None,
) -> dict:
    local_now = (now or datetime.now(TZ)).astimezone(TZ)
    tier = connector_tier(power_kw)
    rate = TIER_RATE[tier]
    kwh = Decimal(str(estimated_kwh))
    peak = local_now.hour in PEAK_HOURS

    surge = Decimal("1.00")
    if surge_enabled:
        surge = SURGE_PEAK if peak else SURGE_OFF_PEAK

    energy_cost = rate * kwh * surge
    boost_fee = BOOST_FEE_PER_KWH * kwh if fast_charge_boost else Decimal("0")
    total = (energy_cost + boost_fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "tier": tier,
        "rate_per_kwh": rate,
        "estimated_kwh": kwh,
        "surge_pricing_enabled": surge_enabled,
        "peak_hour": peak,
        "surge_multiplier": surge,
        "energy_cost": energy_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "boost_fee": boost_fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "total": total,
        "currency": CURRENCY,
        "local_time": local_now.isoformat(timespec="minutes"),
    }
