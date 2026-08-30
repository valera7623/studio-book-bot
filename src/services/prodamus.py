"""Prodamus payform: ссылка оплаты и проверка уведомления (54-ФЗ на стороне кассы)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any
from urllib.parse import urlencode

from src.config import settings

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(
        settings.PRODAMUS_PAYFORM_URL.strip() and settings.PRODAMUS_SECRET.strip()
    )


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if value is None:
        return ""
    return str(value)


def sign_payload(data: dict[str, Any], secret: str) -> str:
    payload = json.dumps(_normalize(data), ensure_ascii=False, separators=(",", ":"))
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(data: dict[str, Any], signature: str, secret: str) -> bool:
    expected = sign_payload(data, secret)
    return hmac.compare_digest(expected.lower(), (signature or "").strip().lower())


def build_payment_url(
    *,
    order_id: str,
    amount_rub: int,
    description: str,
    customer_phone: str | None = None,
    extra: dict[str, str] | None = None,
) -> str:
    base = settings.PRODAMUS_PAYFORM_URL.rstrip("/")
    params: dict[str, Any] = {
        "do": "pay",
        "order_id": order_id,
        "products": {
            "0": {
                "name": description,
                "price": str(amount_rub),
                "quantity": "1",
            }
        },
        "customer_extra": json.dumps(extra or {}, ensure_ascii=False),
    }
    if customer_phone:
        params["customer_phone"] = customer_phone
    if settings.PUBLIC_BASE_URL.strip():
        params["urlSuccess"] = settings.PUBLIC_BASE_URL.rstrip("/") + "/pay/success"
        params["urlReturn"] = settings.PUBLIC_BASE_URL.rstrip("/") + "/pay/return"
        params["urlNotification"] = settings.PUBLIC_BASE_URL.rstrip("/") + "/prodamus/webhook"
    params["signature"] = sign_payload(params, settings.PRODAMUS_SECRET)
    flat: dict[str, str] = {}
    for key, value in params.items():
        if key == "products":
            flat["products[0][name]"] = description
            flat["products[0][price]"] = str(amount_rub)
            flat["products[0][quantity]"] = "1"
            continue
        if isinstance(value, dict):
            continue
        flat[key] = str(value)
    return f"{base}?{urlencode(flat, safe='[]')}"


async def request_refund(order_id: str, amount_rub: int) -> tuple[bool, str]:
    """Возврат в кассе Prodamus. Без ключей — только локальная отмена (тесты/пилот)."""
    if not order_id:
        return True, "no_order"
    if not is_configured():
        return True, "local"
    if amount_rub <= 0:
        return True, "zero"
    import aiohttp

    payload = {
        "do": "refund",
        "order_id": order_id,
        "sum": str(amount_rub),
    }
    payload["signature"] = sign_payload(payload, settings.PRODAMUS_SECRET)
    url = settings.PRODAMUS_PAYFORM_URL.rstrip("/")
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(url, data=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    logger.warning("prodamus refund http %s: %s", resp.status, body[:300])
                    return False, f"http_{resp.status}"
        return True, "ok"
    except Exception as exc:
        logger.exception("prodamus refund")
        return False, str(exc)[:120]
