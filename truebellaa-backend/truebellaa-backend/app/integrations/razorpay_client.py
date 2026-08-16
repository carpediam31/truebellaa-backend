"""
Razorpay integration.

Two modes:
  * LIVE  — when real keys are set in .env, we call the Razorpay API.
  * DEMO  — when keys are placeholders, we simulate success (mirrors the
            frontend's demo mode) so you can develop without keys.

Signature verification is the security-critical part: it proves a payment
callback genuinely came from Razorpay and wasn't forged by the browser.
"""
import hmac
import hashlib
import time

import httpx

from app.core.config import settings

API_BASE = "https://api.razorpay.com/v1"


def create_order(amount_rupees: float, currency: str = "INR", receipt: str = "") -> dict:
    """Ask Razorpay to create an order. Returns {'id': 'order_...', ...}."""
    amount_paise = int(round(amount_rupees * 100))
    if not settings.razorpay_live:
        # DEMO: fabricate a plausible order id.
        return {
            "id": f"order_DEMO{int(time.time())}",
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt,
            "status": "created",
            "demo": True,
        }
    resp = httpx.post(
        f"{API_BASE}/orders",
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
        json={"amount": amount_paise, "currency": currency, "receipt": receipt},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def verify_payment_signature(razorpay_order_id: str, razorpay_payment_id: str,
                             signature: str) -> bool:
    """Verify the checkout callback signature (order_id|payment_id)."""
    if not settings.razorpay_live:
        return True  # DEMO mode accepts the simulated payment
    message = f"{razorpay_order_id}|{razorpay_payment_id}".encode()
    expected = hmac.new(settings.RAZORPAY_KEY_SECRET.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """Verify a webhook POST using the webhook secret."""
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return True  # DEMO / not configured
    expected = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")
