"""Order lookup + tracking (customer-facing) and Shiprocket webhook."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.database import get_read_db, get_write_db
from app.core.deps import get_tenant
from app.models.tenancy import Tenant
from app.models.order import Order, OrderItem
from app.services import order_service, shipping_service

router = APIRouter(tags=["orders"])


@router.get("/orders/{public_id}")
def get_order(public_id: str, tenant: Tenant = Depends(get_tenant),
              db: Session = Depends(get_read_db)):
    order = order_service.get_order(db, tenant, public_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
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
                db: Session = Depends(get_read_db)):
    order = order_service.get_order(db, tenant, public_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return shipping_service.get_tracking(db, tenant, order)


@router.post("/webhook/shiprocket", tags=["shipping"])
async def shiprocket_webhook(request: Request, db: Session = Depends(get_write_db)):
    raw = await request.body()
    return shipping_service.handle_webhook(db, raw)
