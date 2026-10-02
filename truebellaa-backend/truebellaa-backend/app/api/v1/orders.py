"""Order lookup + tracking (customer-facing) and Shiprocket webhook."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.database import get_read_db, get_write_db
from app.core.deps import get_tenant, get_optional_customer
from app.models.customer import Customer
from app.models.tenancy import Tenant
from app.models.order import Order, OrderItem
from app.services import order_service, shipping_service

router = APIRouter(tags=["orders"])


def _authorise_order(order: Order, customer: Customer | None, email: str | None) -> None:
    """
    An order exposes the buyer's name, address and email, so a bare order id
    must not be enough to read it — a forwarded link would leak PII.

    Access is granted when EITHER:
      * the logged-in customer owns the order, or
      * the caller supplies the order's own contact email (the classic
        "order number + email" track-order form, which keeps guest
        checkout working without an account).

    The failure is deliberately 404, not 403: a 403 would confirm that the
    order id is real, letting someone enumerate valid ids.
    """
    if customer is not None and order.customer_id == customer.id:
        return
    if email and order.contact_email and email.strip().lower() == order.contact_email.lower():
        return
    raise HTTPException(
        status_code=404,
        detail="Order not found. If you checked out as a guest, include the email "
               "address used on the order.",
    )


@router.get("/orders/{public_id}")
def get_order(public_id: str, tenant: Tenant = Depends(get_tenant),
              email: str | None = Query(default=None,
                                        description="Required for guest orders — the email used at checkout"),
              customer: Customer | None = Depends(get_optional_customer),
              db: Session = Depends(get_read_db)):
    order = order_service.get_order(db, tenant, public_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _authorise_order(order, customer, email)
    items = db.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalars().all()
    return {
        "order_number": order.order_number, "public_id": order.public_id,
        "status": order.status, "grand_total": float(order.grand_total),
        "currency": order.currency_code,
        "items": [{"name": i.product_name, "variant": i.variant_label,
                   "qty": i.quantity, "line_total": float(i.line_total)} for i in items],
        "shipping": {"name": f"{order.ship_first_name} {order.ship_last_name}",
                     "city": order.ship_city, "state": order.ship_state,
                     "pin": order.ship_postal_code},
    }


@router.get("/orders/{public_id}/tracking")
def track_order(public_id: str, tenant: Tenant = Depends(get_tenant),
                email: str | None = Query(default=None,
                                          description="Required for guest orders — the email used at checkout"),
                customer: Customer | None = Depends(get_optional_customer),
                db: Session = Depends(get_read_db)):
    order = order_service.get_order(db, tenant, public_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _authorise_order(order, customer, email)
    return shipping_service.get_tracking(db, tenant, order)


@router.post("/webhook/shiprocket", tags=["shipping"])
async def shiprocket_webhook(request: Request, db: Session = Depends(get_write_db)):
    raw = await request.body()
    return shipping_service.handle_webhook(db, raw)
