"""Crypto Pay API (@CryptoBot) client and webhook verification.

Docs: https://help.send.tg/en/articles/10279948-crypto-pay-api
- Auth header `Crypto-Pay-API-Token`; responses are `{"ok": bool, "result"|"error": ...}`.
- Webhook signature: hex(HMAC-SHA256(key=SHA256(token), msg=raw_body)) in the
  `crypto-pay-api-signature` header.
- `update_id` is NOT unique, so idempotency is keyed on the invoice, not the update.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import AppError

log = logging.getLogger(__name__)

SIGNATURE_HEADER = "crypto-pay-api-signature"
# Toncoin was rebranded to Gram; providers switch tickers at their own pace. Each configured
# code lists the codes it may appear under, in order of preference.
ASSET_ALIASES: dict[str, tuple[str, ...]] = {"GRAM": ("GRAM", "TON"), "TON": ("TON", "GRAM")}
MAX_WEBHOOK_AGE = dt.timedelta(minutes=10)


class PaymentProviderError(AppError):
    status_code = 502
    code = "payment_provider_error"
    message = "The payment provider is unavailable. Please try again in a minute."


@dataclass(frozen=True)
class Invoice:
    invoice_id: int
    status: str  # active | paid | expired
    amount: Decimal
    fiat: str | None
    payload: str | None
    pay_url: str | None
    expires_at: dt.datetime | None
    paid_at: dt.datetime | None
    paid_asset: str | None
    paid_amount: str | None

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Invoice:
        return cls(
            invoice_id=int(data["invoice_id"]),
            status=str(data["status"]),
            amount=Decimal(str(data["amount"])),
            fiat=data.get("fiat"),
            payload=data.get("payload"),
            pay_url=data.get("bot_invoice_url") or data.get("pay_url"),
            expires_at=_ts(data.get("expiration_date")),
            paid_at=_ts(data.get("paid_at")),
            paid_asset=data.get("paid_asset"),
            paid_amount=None if data.get("paid_amount") is None else str(data["paid_amount"]),
        )


def _ts(value: Any) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def minor_to_amount(amount_minor: int) -> str:
    """499 → "4.99" (USD cents to the decimal string the API expects)."""
    return f"{Decimal(amount_minor) / 100:.2f}"


def verify_signature(token: str, raw_body: bytes, signature: str | None) -> bool:
    if not token or not signature:
        return False
    secret = hashlib.sha256(token.encode()).digest()
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def parse_webhook(raw_body: bytes, *, now: dt.datetime) -> tuple[str, Invoice]:
    """Return (update_type, invoice). Raises ValueError for malformed or stale updates."""
    data = json.loads(raw_body)
    if not isinstance(data, dict) or not isinstance(data.get("payload"), dict):
        raise ValueError("malformed update")
    sent = _ts(data.get("request_date"))
    if sent is None or abs(now - sent) > MAX_WEBHOOK_AGE:
        raise ValueError("stale or undated update")
    return str(data.get("update_type", "")), Invoice.parse(data["payload"])


class CryptoBotClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.cryptobot_base_url,
            headers={"Crypto-Pay-API-Token": settings.cryptobot_api_token.get_secret_value()},
            timeout=httpx.Timeout(10.0, connect=5.0),
            transport=transport,
        )
        self._resolved_assets: list[str] | None = None

    async def accepted_assets(self) -> list[str]:
        """Configured assets mapped to the codes the API actually offers (cached).

        If the currency list can't be fetched, the configured codes are used as-is."""
        if self._resolved_assets is not None:
            return self._resolved_assets
        configured = self._settings.cryptobot_accepted_assets
        try:
            offered = {
                str(c["code"]).upper()
                for c in await self.get_currencies()
                if isinstance(c, dict) and c.get("code")
            }
        except PaymentProviderError:
            return configured
        resolved: list[str] = []
        for asset in configured:
            match = next((a for a in ASSET_ALIASES.get(asset, (asset,)) if a in offered), None)
            if match is None:
                log.warning("cryptobot: asset %s is not offered by the API; skipping", asset)
            elif match not in resolved:
                resolved.append(match)
        if not resolved:
            log.error("cryptobot: none of %s is offered by the API", configured)
            raise PaymentProviderError()
        if resolved != configured:
            log.info("cryptobot: accepted assets resolved %s -> %s", configured, resolved)
        self._resolved_assets = resolved
        return resolved

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = await self._client.post(f"/{method}", json=params or {})
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("cryptobot %s transport error: %s", method, exc)
            raise PaymentProviderError() from exc
        if not isinstance(data, dict) or not data.get("ok"):
            err = data.get("error") if isinstance(data, dict) else None
            log.warning("cryptobot %s failed: %s", method, err)
            raise PaymentProviderError(details={"provider_error": str(err)[:200]})
        return data.get("result")

    async def get_me(self) -> dict[str, Any]:
        result: dict[str, Any] = await self._call("getMe")
        return result

    async def get_currencies(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = await self._call("getCurrencies")
        return result

    async def create_invoice(
        self,
        *,
        amount_minor: int,
        fiat: str,
        payload: str,
        description: str,
    ) -> Invoice:
        params: dict[str, Any] = {
            "currency_type": "fiat",
            "fiat": fiat,
            "amount": minor_to_amount(amount_minor),
            "accepted_assets": ",".join(await self.accepted_assets()),
            "payload": payload,
            "description": description[:1024],
            "expires_in": self._settings.cryptobot_invoice_ttl_seconds,
            "allow_comments": False,
            "allow_anonymous": False,
        }
        if self._settings.telegram_bot_username:
            params["paid_btn_name"] = "callback"
            params["paid_btn_url"] = f"https://t.me/{self._settings.telegram_bot_username}"
        return Invoice.parse(await self._call("createInvoice", params))

    async def get_invoices(self, invoice_ids: list[int]) -> list[Invoice]:
        if not invoice_ids:
            return []
        result = await self._call(
            "getInvoices",
            {"invoice_ids": ",".join(str(i) for i in invoice_ids), "count": len(invoice_ids)},
        )
        items = result.get("items", []) if isinstance(result, dict) else result
        return [Invoice.parse(i) for i in items or []]
