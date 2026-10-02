"""Admin/Manager order operations: list + create Shiprocket shipment."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_read_db
from app.core.deps import require, get_tenant, CurrentStaff, get_staff_write_db, client_meta
from app.integrations import shiprocket_client
from app.models.tenancy import Tenant
from app.models.order import Order, OrderStatusHistory
from app.models.shipping import Shipment
from app.schemas.api import OrderStatusIn, OrderNoteIn
from app.services import order_service, order_lifecycle, shipping_service, email_service

router = APIRouter(prefix="/admin", tags=["admin: orders"])


@router.get("/orders")
def list_orders(status: str | None = None,
                staff: CurrentStaff = Depends(require("order.view")),
                db: Session = Depends(get_read_db)):
    stmt = select(Order).where(Order.tenant_id == staff.tenant_id).order_by(Order.id.desc()).limit(100)
    if status:
        stmt = stmt.where(Order.status == status)
    rows = db.execute(stmt).scalars().all()
    return [{"order_number": o.order_number, "public_id": o.public_id,
             "status": o.status, "grand_total": float(o.grand_total),
             "email": o.contact_email,
             "placed_at": o.placed_at.isoformat() if o.placed_at else None} for o in rows]


@router.get("/orders/{public_id}")
def get_order(public_id: str,
              staff: CurrentStaff = Depends(require("order.view")),
              db: Session = Depends(get_read_db)):
    """One order with its items, status history and shipment."""
    order = order_lifecycle.get_order_or_404(db, staff.tenant_id, public_id)
    history = db.execute(
        select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id)
        .order_by(OrderStatusHistory.id)
    ).scalars().all()
    shipment = db.execute(
        select(Shipment).where(Shipment.order_id == order.id)
    ).scalar_one_or_none()
    return {
        "order_number": order.order_number, "public_id": order.public_id,
        "status": order.status, "grand_total": float(order.grand_total),
        "currency": order.currency_code,
        "email": order.contact_email, "phone": order.contact_phone,
        "placed_at": order.placed_at.isoformat() if order.placed_at else None,
        "shipping": {
            "name": f"{order.ship_first_name} {order.ship_last_name}",
            "line1": order.ship_line1, "line2": order.ship_line2,
            "city": order.ship_city, "state": order.ship_state,
            "pin": order.ship_postal_code,
        },
        "items": [{"name": i.product_name, "sku": i.sku, "qty": i.quantity,
                   "unit_price": float(i.unit_price), "line_total": float(i.line_total)}
                  for i in order.items],
        "next_statuses": sorted(order_lifecycle.TRANSITIONS.get(order.status, set())),
        "history": [{"from": h.from_status, "to": h.to_status, "note": h.note,
                     "at": h.created_at.isoformat() if h.created_at else None}
                    for h in history],
        "shipment": {
            "awb_code": shipment.awb_code, "courier": shipment.courier_name,
            "status": shipment.status, "tracking_url": shipment.tracking_url,
        } if shipment else None,
    }


@router.patch("/orders/{public_id}/status")
def update_status(public_id: str, body: OrderStatusIn,
                  staff: CurrentStaff = Depends(require("order.update_status")),
                  db: Session = Depends(get_staff_write_db),
                  meta: dict = Depends(client_meta)):
    """
    Move an order along its lifecycle. Only transitions allowed by
    order_lifecycle.TRANSITIONS are accepted, so a delivered order can't
    be dragged back to pending.
    """
    order = order_lifecycle.get_order_or_404(db, staff.tenant_id, public_id)
    order_lifecycle.change_status(db, order, body.status, staff_id=staff.user.id,
                                  staff_name=staff.user.full_name, note=body.note, meta=meta)
    return {"order_number": order.order_number, "status": order.status,
            "next_statuses": sorted(order_lifecycle.TRANSITIONS.get(order.status, set()))}


@router.post("/orders/{public_id}/cancel")
def cancel_order(public_id: str, body: OrderNoteIn | None = None,
                 staff: CurrentStaff = Depends(require("order.cancel")),
                 db: Session = Depends(get_staff_write_db),
                 meta: dict = Depends(client_meta)):
    """Cancel an order and return its stock to the shelf."""
    order = order_lifecycle.get_order_or_404(db, staff.tenant_id, public_id)
    order_lifecycle.change_status(db, order, "cancelled", staff_id=staff.user.id,
                                  staff_name=staff.user.full_name,
                                  note=(body.note if body else None) or "Cancelled by staff",
                                  meta=meta)
    return {"order_number": order.order_number, "status": order.status}


@router.post("/orders/{public_id}/refund")
def refund_order(public_id: str, body: OrderNoteIn | None = None,
                 staff: CurrentStaff = Depends(require("order.refund")),
                 db: Session = Depends(get_staff_write_db),
                 meta: dict = Depends(client_meta)):
    """
    Mark an order refunded.

    This records the refund against the order; moving the money back is
    done in the Razorpay dashboard. Marking it here without refunding there
    would leave the books wrong, so the note is worth filling in.
    """
    order = order_lifecycle.get_order_or_404(db, staff.tenant_id, public_id)
    order_lifecycle.change_status(db, order, "refunded", staff_id=staff.user.id,
                                  staff_name=staff.user.full_name,
                                  note=(body.note if body else None) or "Refunded by staff",
                                  meta=meta)
    return {"order_number": order.order_number, "status": order.status,
            "reminder": "Issue the actual refund in Razorpay — this only records it here."}


@router.post("/orders/{public_id}/ship")
def ship_order(public_id: str, tenant: Tenant = Depends(get_tenant),
               staff: CurrentStaff = Depends(require("shipment.create")),
               db: Session = Depends(get_staff_write_db)):
    order = db.execute(
        select(Order).where(Order.tenant_id == staff.tenant_id, Order.public_id == public_id)
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        shipment = shipping_service.create_shipment(db, tenant, order,
                                                    staff_id=staff.user.id,
                                                    staff_name=staff.user.full_name)
    except shiprocket_client.ShiprocketError as exc:
        # Shiprocket's own message is far more useful than a generic 500 —
        # it names the unverified pickup address, empty wallet, etc.
        raise HTTPException(status_code=502, detail=str(exc))

    # Only email the customer once there is a real tracking number — a
    # "your order has shipped" mail with no AWB is worse than no mail.
    if shipment.awb_code:
        email_service.send_order_shipped_email(order, {
            "courier_name": shipment.courier_name, "awb_code": shipment.awb_code,
            "tracking_url": shipment.tracking_url,
        }, db)

    # The Shiprocket order can exist while courier assignment is refused
    # (an empty wallet does exactly this, and it answers HTTP 200). Say so
    # plainly instead of returning a blank AWB and looking like it worked.
    awb_error = (shipment.raw_response or {}).get("awb_error") if shipment.raw_response else None
    return {
        "order_number": order.order_number,
        "awb_code": shipment.awb_code,
        "courier": shipment.courier_name,
        "status": shipment.status,
        "tracking_url": shipment.tracking_url,
        "order_status": order.status,
        "customer_emailed": bool(shipment.awb_code),
        "warning": (f"Order created in Shiprocket, but no courier was assigned: {awb_error}"
                    if not shipment.awb_code else None),
    }
