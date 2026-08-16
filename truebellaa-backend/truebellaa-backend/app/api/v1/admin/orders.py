"""Admin/Manager order operations: list + create Shiprocket shipment."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_read_db
from app.core.deps import require, get_tenant, CurrentStaff, get_staff_write_db
from app.models.tenancy import Tenant
from app.models.order import Order
from app.services import order_service, shipping_service

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


@router.post("/orders/{public_id}/ship")
def ship_order(public_id: str, tenant: Tenant = Depends(get_tenant),
               staff: CurrentStaff = Depends(require("shipment.create")),
               db: Session = Depends(get_staff_write_db)):
    order = db.execute(
        select(Order).where(Order.tenant_id == staff.tenant_id, Order.public_id == public_id)
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    shipment = shipping_service.create_shipment(db, tenant, order,
                                                staff_id=staff.user.id,
                                                staff_name=staff.user.full_name)
    return {"order_number": order.order_number, "awb_code": shipment.awb_code,
            "courier": shipment.courier_name, "status": shipment.status,
            "tracking_url": shipment.tracking_url}
