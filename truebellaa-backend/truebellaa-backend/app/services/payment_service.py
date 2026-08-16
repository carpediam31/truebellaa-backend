"""Razorpay payment flow: create -> verify/capture -> webhook (idempotent)."""
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.integrations import razorpay_client
from app.models.tenancy import Tenant
from app.models.order import Order
from app.models.payment import Payment, PaymentWebhookEvent
from app.services import order_service


def create_payment_for_order(db: Session, tenant: Tenant, order: Order) -> dict:
    if order.status != "pending_payment":
        raise HTTPException(status_code=409, detail="Order is not awaiting payment")

    rzp = razorpay_client.create_order(
        amount_rupees=float(order.grand_total),
        currency=order.currency_code, receipt=order.order_number,
    )
    payment = Payment(
        tenant_id=tenant.id, order_id=order.id, provider="razorpay",
        razorpay_order_id=rzp["id"], amount=order.grand_total,
        currency_code=order.currency_code, status="created", raw_response=rzp,
    )
    db.add(payment)
    db.commit()

    return {
        "order_number": order.order_number,
        "order_public_id": order.public_id,
        "amount": float(order.grand_total),
        "currency": order.currency_code,
        "razorpay_order_id": rzp["id"],
        "razorpay_key_id": settings.RAZORPAY_KEY_ID or "DEMO",
        "demo_mode": not settings.razorpay_live,
    }


def verify_and_capture(db: Session, tenant: Tenant, order: Order, *,
                       razorpay_order_id: str, razorpay_payment_id: str,
                       signature: str) -> dict:
    payment = db.execute(
        select(Payment).where(Payment.order_id == order.id,
                              Payment.razorpay_order_id == razorpay_order_id)
    ).scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment record not found")

    ok = razorpay_client.verify_payment_signature(razorpay_order_id, razorpay_payment_id, signature)
    if not ok:
        payment.status = "failed"
        payment.error_description = "Signature verification failed"
        db.commit()
        raise HTTPException(status_code=400, detail="Payment verification failed")

    payment.razorpay_payment_id = razorpay_payment_id
    payment.razorpay_signature = signature
    payment.signature_verified = True
    payment.status = "captured"
    payment.captured_at = datetime.now(timezone.utc)

    # load items for stock conversion
    order = db.execute(
        select(Order).where(Order.id == order.id).options(selectinload(Order.items))
    ).scalar_one()
    order_service.mark_paid(db, order, note="Razorpay payment captured")
    db.commit()

    return {"status": "paid", "order_number": order.order_number,
            "order_public_id": order.public_id}


def handle_webhook(db: Session, raw_body: bytes, signature: str) -> dict:
    """Store every webhook once (idempotent), then act on it."""
    verified = razorpay_client.verify_webhook_signature(raw_body, signature)
    try:
        body = json.loads(raw_body.decode() or "{}")
    except json.JSONDecodeError:
        body = {}

    event_id = signature or body.get("id") or f"evt_{datetime.now(timezone.utc).timestamp()}"
    existing = db.execute(
        select(PaymentWebhookEvent).where(PaymentWebhookEvent.provider == "razorpay",
                                          PaymentWebhookEvent.event_id == event_id)
    ).scalar_one_or_none()
    if existing:
        return {"status": "duplicate_ignored"}

    event = PaymentWebhookEvent(
        provider="razorpay", event_id=event_id, event_type=body.get("event"),
        signature_verified=verified, payload=body,
        processing_status="received",
    )
    db.add(event)
    db.flush()

    if not verified:
        event.processing_status = "error"
        event.error_message = "Bad signature"
        db.commit()
        return {"status": "invalid_signature"}

    # Act on payment.captured — find the payment by razorpay order id.
    try:
        entity = body.get("payload", {}).get("payment", {}).get("entity", {})
        rzp_order_id = entity.get("order_id")
        if body.get("event") == "payment.captured" and rzp_order_id:
            payment = db.execute(
                select(Payment).where(Payment.razorpay_order_id == rzp_order_id)
            ).scalar_one_or_none()
            if payment and payment.status != "captured":
                payment.status = "captured"
                payment.razorpay_payment_id = entity.get("id")
                payment.signature_verified = True
                payment.captured_at = datetime.now(timezone.utc)
                order = db.execute(
                    select(Order).where(Order.id == payment.order_id)
                    .options(selectinload(Order.items))
                ).scalar_one()
                order_service.mark_paid(db, order, note="Confirmed via webhook")
                event.tenant_id = payment.tenant_id
        event.processing_status = "processed"
        event.processed_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "processed"}
    except Exception as exc:  # noqa: BLE001
        event.processing_status = "error"
        event.error_message = str(exc)[:255]
        db.commit()
        return {"status": "error"}
