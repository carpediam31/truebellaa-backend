"""Shiprocket flow: create a shipment for a paid order, and track via webhook."""
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.integrations import shiprocket_client
from app.models.tenancy import Tenant
from app.models.order import Order, OrderStatusHistory
from app.models.shipping import Shipment, ShipmentTrackingEvent, ShippingWebhookEvent
from app.services.audit_service import log_action


def create_shipment(db: Session, tenant: Tenant, order: Order, *, staff_id: int,
                    staff_name: str) -> Shipment:
    if order.status not in ("paid", "processing"):
        raise HTTPException(status_code=409, detail="Order must be paid before shipping")

    existing = db.execute(
        select(Shipment).where(Shipment.order_id == order.id)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Shipment already exists for this order")

    order = db.execute(
        select(Order).where(Order.id == order.id).options(selectinload(Order.items))
    ).scalar_one()

    payload = {
        "order_id": order.order_number,
        "order_date": (order.placed_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M"),
        "billing_customer_name": order.ship_first_name,
        "billing_last_name": order.ship_last_name,
        "billing_address": order.ship_line1,
        "billing_city": order.ship_city,
        "billing_pincode": order.ship_postal_code,
        "billing_state": order.ship_state,
        "billing_country": "India",
        "billing_email": order.contact_email,
        "billing_phone": order.contact_phone,
        # Shiprocket rejects the order outright without this flag (422
        # "The shipping is billing field is required"). We only collect one
        # address at checkout, so shipping always equals billing.
        "shipping_is_billing": True,
        "order_items": [{"name": i.product_name, "sku": i.sku, "units": i.quantity,
                         "selling_price": float(i.unit_price)} for i in order.items],
        "payment_method": "Prepaid",
        "sub_total": float(order.grand_total),
        "length": 10, "breadth": 10, "height": 5, "weight": 0.3,
    }

    result = shiprocket_client.create_shipment(payload)

    shipment = Shipment(
        tenant_id=tenant.id, order_id=order.id, provider="shiprocket",
        shiprocket_order_id=result.get("shiprocket_order_id"),
        shiprocket_shipment_id=result.get("shipment_id"),
        awb_code=result.get("awb_code"), courier_name=result.get("courier_name"),
        status=result.get("status", "ready_to_ship"),
        tracking_url=result.get("tracking_url"),
        raw_response=result, created_by=staff_id,
    )
    db.add(shipment)
    db.flush()

    db.add(ShipmentTrackingEvent(tenant_id=tenant.id, shipment_id=shipment.id,
                                 status=shipment.status, status_detail="Shipment created",
                                 occurred_at=datetime.now(timezone.utc)))

    prev = order.status
    order.status = "shipped" if shipment.status != "ready_to_ship" else "processing"
    db.add(OrderStatusHistory(tenant_id=tenant.id, order_id=order.id, from_status=prev,
                              to_status=order.status, note=f"Shiprocket AWB {shipment.awb_code}",
                              changed_by=staff_id))
    log_action(db, tenant_id=tenant.id, actor_type="staff", actor_id=staff_id,
               actor_name=staff_name, action="shipment.created", entity_type="order",
               entity_id=order.id, entity_label=order.order_number,
               summary=f"Shipment created (AWB {shipment.awb_code})",
               new_values={"awb": shipment.awb_code, "courier": shipment.courier_name})
    db.commit()
    return shipment


def get_tracking(db: Session, tenant: Tenant, order: Order) -> dict:
    shipment = db.execute(
        select(Shipment).where(Shipment.order_id == order.id)
    ).scalar_one_or_none()
    if not shipment:
        return {"status": "not_shipped", "events": []}
    events = db.execute(
        select(ShipmentTrackingEvent).where(ShipmentTrackingEvent.shipment_id == shipment.id)
        .order_by(ShipmentTrackingEvent.created_at.desc())
    ).scalars().all()
    return {
        "awb_code": shipment.awb_code, "courier": shipment.courier_name,
        "status": shipment.status, "tracking_url": shipment.tracking_url,
        "events": [{"status": e.status, "detail": e.status_detail,
                    "location": e.location,
                    "at": e.occurred_at.isoformat() if e.occurred_at else None}
                   for e in events],
    }


def handle_webhook(db: Session, raw_body: bytes) -> dict:
    try:
        body = json.loads(raw_body.decode() or "{}")
    except json.JSONDecodeError:
        body = {}

    awb = str(body.get("awb") or body.get("awb_code") or "")
    status = str(body.get("current_status") or body.get("shipment_status") or "update")
    event_id = f"{awb}:{status}:{body.get('current_timestamp', '')}"

    existing = db.execute(
        select(ShippingWebhookEvent).where(ShippingWebhookEvent.provider == "shiprocket",
                                           ShippingWebhookEvent.event_id == event_id)
    ).scalar_one_or_none()
    if existing:
        return {"status": "duplicate_ignored"}

    event = ShippingWebhookEvent(provider="shiprocket", event_id=event_id,
                                 event_type=status, payload=body, processing_status="received")
    db.add(event)
    db.flush()

    shipment = db.execute(
        select(Shipment).where(Shipment.awb_code == awb)
    ).scalar_one_or_none() if awb else None

    if shipment:
        db.add(ShipmentTrackingEvent(tenant_id=shipment.tenant_id, shipment_id=shipment.id,
                                     status=status, status_detail=body.get("current_status_body"),
                                     location=body.get("location"),
                                     occurred_at=datetime.now(timezone.utc), raw_payload=body))
        mapping = {"delivered": "delivered", "in transit": "in_transit",
                   "out for delivery": "out_for_delivery", "rto": "rto"}
        mapped = mapping.get(status.lower())
        if mapped:
            shipment.status = mapped
            if mapped == "delivered":
                shipment.delivered_at = datetime.now(timezone.utc)
                order = db.get(Order, shipment.order_id)
                if order and order.status not in ("delivered", "refunded", "returned"):
                    order.status = "delivered"
        event.tenant_id = shipment.tenant_id

    event.processing_status = "processed"
    event.processed_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "processed"}
