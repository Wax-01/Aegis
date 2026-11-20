"""Feature Flags propias sobre DynamoDB, una tabla por ambiente: aegisvolt-feature-flags-<env>.

* El estado inicial de cada flag por ambiente lo declara Terraform (módulo feature_flags) con
  `lifecycle { ignore_changes = [item] }`, así un cambio en caliente no es revertido por el siguiente apply.
* Los servicios leen las flags con caché de pocos segundos: cambiar una flag en dev NO requiere
  redesplegar, y como cada ambiente lee SU tabla, prod permanece intacto.
* Si DynamoDB no responde, se usa el último valor conocido o el default seguro (todo apagado).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .dynamo import from_item, now_iso, scan_all, to_item
from .logging_setup import get_logger, log_event

SURGE_PRICING = "ENABLE_DYNAMIC_SURGE_PRICING"
FAST_CHARGE_BOOST = "ENABLE_FAST_CHARGE_BOOST"
SIMULATE_HARDWARE_FAULT = "SIMULATE_CHARGER_HARDWARE_FAULT"

FLAG_DESCRIPTIONS: dict[str, str] = {
    SURGE_PRICING: "Activa tarifas dinámicas en horas pico (multiplicador sobre la tarifa base).",
    FAST_CHARGE_BOOST: "Habilita la reserva prioritaria de ultra-carga (conectores >= 300 kW).",
    SIMULATE_HARDWARE_FAULT: "Inyección de fallos: el cargador reporta falla física y se dispara el rollback SAGA.",
}

SAFE_DEFAULTS: dict[str, bool] = {key: False for key in FLAG_DESCRIPTIONS}

logger = get_logger("flags")


@dataclass(frozen=True)
class FlagState:
    key: str
    enabled: bool
    description: str
    updated_at: str | None = None
    updated_by: str | None = None
    source: str = "dynamodb"  # dynamodb | default

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "enabled": self.enabled,
            "description": self.description,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
            "source": self.source,
        }


class FeatureFlagClient:
    def __init__(
        self,
        dynamo_client,
        table_name: str,
        ttl_seconds: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.client = dynamo_client
        self.table = table_name
        self.ttl = ttl_seconds
        self.clock = clock
        self._lock = threading.Lock()
        self._cache: dict[str, FlagState] | None = None
        self._loaded_at = 0.0

    def _load(self) -> dict[str, FlagState]:
        flags = {
            key: FlagState(key, SAFE_DEFAULTS[key], FLAG_DESCRIPTIONS[key], source="default")
            for key in FLAG_DESCRIPTIONS
        }
        for item in scan_all(self.client, self.table, ConsistentRead=True):
            key = item.get("flag_key")
            if not key:
                continue
            flags[key] = FlagState(
                key=key,
                enabled=bool(item.get("enabled", False)),
                description=item.get("description") or FLAG_DESCRIPTIONS.get(key, ""),
                updated_at=item.get("updated_at"),
                updated_by=item.get("updated_by"),
            )
        return flags

    def all(self, force_refresh: bool = False) -> dict[str, FlagState]:
        with self._lock:
            fresh = self._cache is not None and (self.clock() - self._loaded_at) < self.ttl
            if fresh and not force_refresh:
                return dict(self._cache)  # type: ignore[arg-type]
            try:
                self._cache = self._load()
                self._loaded_at = self.clock()
            except Exception as exc:  # noqa: BLE001
                log_event(logger, "feature_flags.read_failed", level=30, table=self.table, error=str(exc))
                if self._cache is None:
                    return {
                        k: FlagState(k, v, FLAG_DESCRIPTIONS[k], source="default")
                        for k, v in SAFE_DEFAULTS.items()
                    }
            return dict(self._cache)

    def is_enabled(self, key: str) -> bool:
        state = self.all().get(key)
        return bool(state and state.enabled)

    def snapshot(self) -> dict[str, bool]:
        return {k: v.enabled for k, v in self.all().items()}

    def set(self, key: str, enabled: bool, actor: str) -> FlagState:
        if key not in FLAG_DESCRIPTIONS:
            raise ValueError(f"Flag desconocida: {key}")
        updated_at = now_iso()
        response = self.client.update_item(
            TableName=self.table,
            Key=to_item({"flag_key": key}),
            UpdateExpression=(
                "SET enabled = :e, updated_at = :t, updated_by = :u, "
                "description = if_not_exists(description, :d)"
            ),
            ExpressionAttributeValues=to_item(
                {":e": enabled, ":t": updated_at, ":u": actor, ":d": FLAG_DESCRIPTIONS[key]}
            ),
            ReturnValues="ALL_NEW",
        )
        item = from_item(response["Attributes"]) or {}
        with self._lock:
            self._cache = None
        log_event(logger, "feature_flags.changed", flag=key, enabled=enabled, actor=actor)
        return FlagState(
            key=key,
            enabled=bool(item.get("enabled")),
            description=item.get("description", ""),
            updated_at=item.get("updated_at"),
            updated_by=item.get("updated_by"),
        )
