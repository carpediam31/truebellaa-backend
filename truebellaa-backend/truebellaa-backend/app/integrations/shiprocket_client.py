"""
Shiprocket integration.

Two modes:
  * LIVE  — when credentials are set, we authenticate and create shipments.
  * DEMO  — otherwise, we simulate an AWB (tracking number) + courier so the
            fulfilment flow works end-to-end without a Shiprocket account.

Shiprocket auth returns a bearer token that we cache for ~24h.
"""
import logging
import time

import httpx

from app.core.config import settings

logger = logging.getLogger("app.shiprocket")


class ShiprocketError(RuntimeError):
    """Shiprocket rejected the request — the message is safe to show staff."""


def _explain(resp: httpx.Response, doing: str) -> str:
    """
    Turn Shiprocket's error body into something an admin can act on.

    Their failures are usually configuration (unverified pickup address,
    empty wallet, missing KYC), so surfacing the raw message saves a lot of
    guessing.
    """
    try:
        body = resp.json()
        msg = body.get("message") or body.get("error") or str(body)
        errors = body.get("errors")
        if errors:
            msg = f"{msg} — {errors}"
    except Exception:  # noqa: BLE001
        msg = resp.text[:300]
    hint = ""
    if resp.status_code == 403:
        hint = " (check the API user is active and KYC is complete)"
    elif "pickup" in str(msg).lower():
        hint = (f" (SHIPROCKET_PICKUP_LOCATION is "
                f"'{settings.SHIPROCKET_PICKUP_LOCATION}' — it must match a verified "
                f"pickup address exactly)")
    elif "wallet" in str(msg).lower() or "balance" in str(msg).lower():
        hint = " (the Shiprocket wallet needs credit before a courier can be booked)"
    return f"Shiprocket refused while {doing}: HTTP {resp.status_code} — {msg}{hint}"

# Set SHIPROCKET_BASE_URL in .env to switch between live and sandbox.
API_BASE = settings.SHIPROCKET_BASE_URL.rstrip("/")

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

    # Shiprocket needs the pickup address nickname exactly as it appears in
    # Settings -> Company -> Pick Up Address. Without it the order is rejected.
    order.setdefault("pickup_location", settings.SHIPROCKET_PICKUP_LOCATION)

    # --- 1) create the order -----------------------------------------
    create = httpx.post(f"{API_BASE}/orders/create/adhoc", headers=headers,
                        json=order, timeout=30)
    if create.status_code >= 400:
        raise ShiprocketError(_explain(create, "creating the order"))
    data = create.json()
    sr_order_id = str(data.get("order_id") or "")
    shipment_id = str(data.get("shipment_id") or "")
    if not shipment_id:
        raise ShiprocketError(
            f"Shiprocket accepted the order but returned no shipment id: {str(data)[:200]}")

    # --- 2) assign a courier + AWB ------------------------------------
    # Creating the order alone does NOT produce a tracking number; this is
    # the call that picks a courier and returns the AWB.
    awb_code = courier_name = None
    awb_error = None
    try:
        awb = httpx.post(f"{API_BASE}/courier/assign/awb", headers=headers,
                         json={"shipment_id": shipment_id}, timeout=45)
        if awb.status_code >= 400:
            awb_error = _explain(awb, "assigning a courier")
        else:
            body = awb.json()
            payload = (body.get("response") or {}).get("data") or {}
            awb_code = payload.get("awb_code")
            courier_name = payload.get("courier_name")
            # Shiprocket answers HTTP 200 even when it refuses to assign a
            # courier — the real outcome is awb_assign_status, and the reason
            # sits in awb_assign_error (e.g. "recharge your wallet").
            # Trusting the status code alone silently loses the AWB.
            if not awb_code:
                awb_error = (payload.get("awb_assign_error")
                             or body.get("message")
                             or f"no AWB returned: {str(body)[:200]}")
    except Exception as exc:  # noqa: BLE001
        awb_error = f"{type(exc).__name__}: {exc}"

    # The order exists in Shiprocket either way, so don't fail the whole
    # operation if only the AWB step failed — record it and let staff retry
    # or assign a courier from the Shiprocket panel.
    if awb_error:
        logger.warning("Shiprocket order %s created but AWB failed: %s", sr_order_id, awb_error)

    return {
        "shiprocket_order_id": sr_order_id,
        "shipment_id": shipment_id,
        "awb_code": awb_code,
        "courier_name": courier_name,
        # Must be one of the shipments.status enum values. "pending" means
        # the order exists in Shiprocket but no courier/AWB is assigned yet
        # — staff can assign one from the Shiprocket panel and retry.
        "status": "ready_to_ship" if awb_code else "pending",
        "tracking_url": f"https://shiprocket.co/tracking/{awb_code}" if awb_code else None,
        "awb_error": awb_error,
        "raw": data,
    }


def track_awb(awb_code: str) -> dict:
    """Live tracking for one AWB. Returns {} in demo mode or on failure."""
    if not settings.shiprocket_live or not awb_code:
        return {}
    try:
        token = _get_token()
        r = httpx.get(f"{API_BASE}/courier/track/awb/{awb_code}",
                      headers={"Authorization": f"Bearer {token}"}, timeout=25)
        return r.json() if r.status_code < 400 else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shiprocket tracking failed for %s: %s", awb_code, exc)
        return {}
