"""
Shiprocket integration.

Two modes:
  * LIVE  — when credentials are set, we authenticate and create shipments.
  * DEMO  — otherwise, we simulate an AWB (tracking number) + courier so the
            fulfilment flow works end-to-end without a Shiprocket account.

Shiprocket auth returns a bearer token that we cache for ~24h.
"""
import time

import httpx

from app.core.config import settings

API_BASE = "https://apiv2.shiprocket.in/v1/external"

_token_cache = {"token": None, "expires": 0.0}


def _get_token() -> str | None:
    if not settings.shiprocket_live:
        return None
    now = time.time()
    if _token_cache["token"] and _token_cache["expires"] > now:
        return _token_cache["token"]
    resp = httpx.post(
        f"{API_BASE}/auth/login",
        json={"email": settings.SHIPROCKET_EMAIL, "password": settings.SHIPROCKET_PASSWORD},
        timeout=20,
    )
    resp.raise_for_status()
    token = resp.json()["token"]
    _token_cache.update(token=token, expires=now + 23 * 3600)
    return token


def create_shipment(order: dict) -> dict:
    """
    Create a Shiprocket order + return AWB/courier info.

    `order` is a plain dict the service layer builds from our Order row
    (order number, items, shipping address, weight). Returns a normalised
    dict the service stores on the `shipments` table.
    """
    if not settings.shiprocket_live:
        # DEMO: deterministic fake AWB from the order number.
        num = "".join(ch for ch in str(order.get("order_id", "0")) if ch.isdigit()) or "0"
        awb = f"DEMOAWB{int(num):>08}"[:16]
        return {
            "shiprocket_order_id": f"SR{num}",
            "shipment_id": f"SH{num}",
            "awb_code": awb,
            "courier_name": "Demo Express",
            "status": "ready_to_ship",
            "tracking_url": f"https://shiprocket.co/tracking/{awb}",
            "demo": True,
        }

    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    # 1) create the order in Shiprocket
    create = httpx.post(f"{API_BASE}/orders/create/adhoc", headers=headers, json=order, timeout=30)
    create.raise_for_status()
    data = create.json()
    return {
        "shiprocket_order_id": str(data.get("order_id", "")),
        "shipment_id": str(data.get("shipment_id", "")),
        "awb_code": data.get("awb_code"),
        "courier_name": data.get("courier_name"),
        "status": "ready_to_ship",
        "tracking_url": None,
        "raw": data,
    }
