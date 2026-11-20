"""Persistencia del billing-wallet-service (tabla aegisvolt-billing-<env>).

  pk=WALLET#<fleet>  sk=META                 -> saldo de la billetera de la flota
  pk=WALLET#<fleet>  sk=TX#<saga>#CHARGE     -> cobro (llave de idempotencia del paso 2)
  pk=WALLET#<fleet>  sk=TX#<saga>#REFUND     -> reembolso / evento de reversión (llave de idempotencia de la compensación)
  pk=WALLET#<fleet>  sk=TX#<topup-id>#TOPUP  -> recargas

Garantías:
* Cobro: TransactWriteItems = [descontar saldo con condición balance >= monto,
  Put CHARGE con attribute_not_exists, ConditionCheck REFUND no existe]. Un cobro duplicado no descuenta dos
  veces; un cobro que llega DESPUÉS de su compensación es rechazado.
* Reembolso: [ConditionCheck CHARGE existe, Put REFUND con attribute_not_exists, sumar saldo]. Un reembolso
  duplicado no devuelve dos veces. Si nunca hubo cobro se escribe un REFUND tombstone de monto 0.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from aegis_common.dynamo import (
    from_item,
    is_conditional_failure,
    money,
    now_iso,
    query_all,
    scan_all,
    to_item,
)
from aegis_common.errors import ConflictError, DomainError, NotFoundError
from aegis_common.logging_setup import get_logger, log_event
from botocore.exceptions import ClientError

logger = get_logger("billing")


def wallet_key(fleet_id: str) -> dict[str, str]:
    return {"pk": f"WALLET#{fleet_id}", "sk": "META"}


def tx_key(fleet_id: str, ref: str, kind: str) -> dict[str, str]:
    return {"pk": f"WALLET#{fleet_id}", "sk": f"TX#{ref}#{kind}"}


class BillingRepository:
    def __init__(self, client, table: str):
        self.client = client
        self.table = table

    def _get(self, key: dict[str, str]) -> dict[str, Any] | None:
        resp = self.client.get_item(TableName=self.table, Key=to_item(key), ConsistentRead=True)
        return from_item(resp.get("Item"))

    def get_wallet(self, fleet_id: str) -> dict[str, Any]:
        wallet = self._get(wallet_key(fleet_id))
        if wallet is None:
            raise NotFoundError(f"La flota {fleet_id} no tiene billetera", code="WALLET_NOT_FOUND")
        return wallet

    def list_wallets(self) -> list[dict[str, Any]]:
        items = scan_all(
            self.client,
            self.table,
            FilterExpression="entity = :e",
            ExpressionAttributeValues=to_item({":e": "WALLET"}),
        )
        return sorted(items, key=lambda w: w["fleet_id"])

    def list_transactions(self, fleet_id: str, limit: int = 50) -> list[dict[str, Any]]:
        items = query_all(
            self.client,
            self.table,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :tx)",
            ExpressionAttributeValues=to_item({":pk": f"WALLET#{fleet_id}", ":tx": "TX#"}),
        )
        return sorted(items, key=lambda t: t.get("created_at", ""), reverse=True)[:limit]

    def get_saga_transactions(self, fleet_id: str, saga_id: str) -> dict[str, Any]:
        return {
            "charge": self._get(tx_key(fleet_id, saga_id, "CHARGE")),
            "refund": self._get(tx_key(fleet_id, saga_id, "REFUND")),
        }

    # ------------------------------------------------------------------ SAGA paso 2
    def charge(self, *, saga_id: str, fleet_id: str, amount: Decimal, pricing: dict) -> tuple[dict, bool]:
        amount = money(amount)
        existing = self._get(tx_key(fleet_id, saga_id, "CHARGE"))
        if existing:
            log_event(logger, "charge.replayed", saga_id=saga_id, fleet_id=fleet_id)
            return existing, True
        if self._get(tx_key(fleet_id, saga_id, "REFUND")):
            raise ConflictError(
                f"La saga {saga_id} ya fue compensada; no se puede cobrar", code="SAGA_ALREADY_COMPENSATED"
            )

        now = now_iso()
        charge = {
            **tx_key(fleet_id, saga_id, "CHARGE"),
            "entity": "TX",
            "tx_type": "CHARGE",
            "tx_id": f"{saga_id}#CHARGE",
            "saga_id": saga_id,
            "fleet_id": fleet_id,
            "amount": amount,
            "currency": pricing.get("currency", "USD"),
            "pricing": pricing,
            "created_at": now,
        }
        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.table,
                            "Key": to_item(wallet_key(fleet_id)),
                            "UpdateExpression": "SET balance = balance - :amt, updated_at = :now",
                            "ConditionExpression": "attribute_exists(pk) AND balance >= :amt",
                            "ExpressionAttributeValues": to_item({":amt": amount, ":now": now}),
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": to_item(charge),
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "ConditionCheck": {
                            "TableName": self.table,
                            "Key": to_item(tx_key(fleet_id, saga_id, "REFUND")),
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                ]
            )
        except ClientError as exc:
            if not is_conditional_failure(exc):
                raise
            existing = self._get(tx_key(fleet_id, saga_id, "CHARGE"))
            if existing:
                return existing, True
            if self._get(tx_key(fleet_id, saga_id, "REFUND")):
                raise ConflictError(
                    f"La saga {saga_id} ya fue compensada", code="SAGA_ALREADY_COMPENSATED"
                ) from exc
            wallet = self.get_wallet(fleet_id)  # lanza WALLET_NOT_FOUND si no existe
            raise DomainError(
                f"Fondos insuficientes en {fleet_id}: saldo {wallet['balance']} < {amount}",
                code="INSUFFICIENT_FUNDS",
                status_code=402,
                details={"balance": str(wallet["balance"]), "required": str(amount)},
            ) from exc

        wallet = self.get_wallet(fleet_id)
        charge["balance_after"] = wallet["balance"]
        self.client.update_item(
            TableName=self.table,
            Key=to_item(tx_key(fleet_id, saga_id, "CHARGE")),
            UpdateExpression="SET balance_after = :b",
            ExpressionAttributeValues=to_item({":b": wallet["balance"]}),
        )
        log_event(logger, "charge.captured", saga_id=saga_id, fleet_id=fleet_id, amount=str(amount))
        return charge, False

    # ------------------------------------------------------------------ SAGA compensación 2
    def refund(self, *, saga_id: str, fleet_id: str, reason: str) -> tuple[dict, str]:
        existing_refund = self._get(tx_key(fleet_id, saga_id, "REFUND"))
        if existing_refund:
            log_event(logger, "refund.replayed", saga_id=saga_id, fleet_id=fleet_id)
            return existing_refund, "REPLAY"

        now = now_iso()
        charge = self._get(tx_key(fleet_id, saga_id, "CHARGE"))
        if charge is None:
            tombstone = {
                **tx_key(fleet_id, saga_id, "REFUND"),
                "entity": "TX",
                "tx_type": "REFUND",
                "tx_id": f"{saga_id}#REFUND",
                "saga_id": saga_id,
                "fleet_id": fleet_id,
                "amount": Decimal("0"),
                "reason": reason,
                "tombstone": True,
                "created_at": now,
            }
            try:
                self.client.put_item(
                    TableName=self.table,
                    Item=to_item(tombstone),
                    ConditionExpression="attribute_not_exists(pk)",
                )
                log_event(logger, "refund.tombstone", saga_id=saga_id, fleet_id=fleet_id, reason=reason)
                return tombstone, "TOMBSTONE"
            except ClientError as exc:
                if not is_conditional_failure(exc):
                    raise
                return self._get(tx_key(fleet_id, saga_id, "REFUND")) or tombstone, "REPLAY"

        amount = money(charge["amount"])
        refund = {
            **tx_key(fleet_id, saga_id, "REFUND"),
            "entity": "TX",
            "tx_type": "REFUND",
            "tx_id": f"{saga_id}#REFUND",
            "saga_id": saga_id,
            "fleet_id": fleet_id,
            "amount": amount,
            "currency": charge.get("currency", "USD"),
            "reason": reason,
            "reverses": charge["tx_id"],
            "created_at": now,
        }
        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "ConditionCheck": {
                            "TableName": self.table,
                            "Key": to_item(tx_key(fleet_id, saga_id, "CHARGE")),
                            "ConditionExpression": "attribute_exists(pk)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": to_item(refund),
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Update": {
                            "TableName": self.table,
                            "Key": to_item(wallet_key(fleet_id)),
                            "UpdateExpression": "SET balance = balance + :amt, updated_at = :now",
                            "ConditionExpression": "attribute_exists(pk)",
                            "ExpressionAttributeValues": to_item({":amt": amount, ":now": now}),
                        }
                    },
                ]
            )
        except ClientError as exc:
            if not is_conditional_failure(exc):
                raise
            existing_refund = self._get(tx_key(fleet_id, saga_id, "REFUND"))
            if existing_refund:
                return existing_refund, "REPLAY"
            raise
        wallet = self.get_wallet(fleet_id)
        refund["balance_after"] = wallet["balance"]
        self.client.update_item(
            TableName=self.table,
            Key=to_item(tx_key(fleet_id, saga_id, "REFUND")),
            UpdateExpression="SET balance_after = :b",
            ExpressionAttributeValues=to_item({":b": wallet["balance"]}),
        )
        log_event(
            logger, "refund.applied", saga_id=saga_id, fleet_id=fleet_id, amount=str(amount), reason=reason
        )
        return refund, "REFUNDED"

    # ------------------------------------------------------------------ operaciones de soporte
    def top_up(self, fleet_id: str, amount: Decimal) -> dict:
        amount = money(amount)
        if amount <= 0:
            raise DomainError("El monto de recarga debe ser positivo", code="INVALID_AMOUNT", status_code=422)
        now = now_iso()
        ref = f"topup-{uuid.uuid4().hex[:12]}"
        self.client.transact_write_items(
            TransactItems=[
                {
                    "Update": {
                        "TableName": self.table,
                        "Key": to_item(wallet_key(fleet_id)),
                        "UpdateExpression": "SET balance = balance + :amt, updated_at = :now",
                        "ConditionExpression": "attribute_exists(pk)",
                        "ExpressionAttributeValues": to_item({":amt": amount, ":now": now}),
                    }
                },
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": to_item(
                            {
                                **tx_key(fleet_id, ref, "TOPUP"),
                                "entity": "TX",
                                "tx_type": "TOPUP",
                                "tx_id": ref,
                                "fleet_id": fleet_id,
                                "amount": amount,
                                "currency": "USD",
                                "created_at": now,
                            }
                        ),
                    }
                },
            ]
        )
        log_event(logger, "wallet.topped_up", fleet_id=fleet_id, amount=str(amount))
        return self.get_wallet(fleet_id)

    def seed(self, wallets: list[dict[str, Any]]) -> int:
        created = 0
        now = now_iso()
        for wallet in wallets:
            item = {
                **wallet_key(wallet["fleet_id"]),
                "entity": "WALLET",
                "fleet_id": wallet["fleet_id"],
                "name": wallet["name"],
                "balance": money(wallet["balance"]),
                "currency": "USD",
                "created_at": now,
                "updated_at": now,
            }
            try:
                self.client.put_item(
                    TableName=self.table, Item=to_item(item), ConditionExpression="attribute_not_exists(pk)"
                )
                created += 1
            except ClientError as exc:
                if not is_conditional_failure(exc):
                    raise
        return created
