"""
Admin: the customer list — the people who actually shop.

Not to be confused with Staff & Roles, which is your own team. Staff live
in `users` and sign into this console; customers live in `customers` and
sign into the storefront.

Backs the customer.view / customer.update / customer.block permissions,
which existed in the permission catalog but had no feature behind them.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_read_db
from app.core.deps import require, CurrentStaff, client_meta, get_staff_write_db
from app.models.customer import Customer
from app.models.order import Order
from app.schemas.api import CustomerStatusIn
from app.services.audit_service import log_action

router = APIRouter(prefix="/admin", tags=["admin: customers"])

# Orders that represent real money, for the "spent" column. An abandoned
# pending_payment order is not revenue and must not inflate the total.
PAID_STATUSES = ("paid", "processing", "shipped", "delivered", "completed")


@router.get("/customers")
def list_customers(staff: CurrentStaff = Depends(require("customer.view")),
                   db: Session = Depends(get_read_db),
                   q: str | None = Query(default=None, description="search name or email"),
                   limit: int = Query(default=200, le=500)):
    """Customers with their order count and lifetime spend."""
    # One grouped query for the order stats, then a single pass to merge —
    # avoids the N+1 that a per-customer count would cause.
    stats = {
        row[0]: (row[1], float(row[2] or 0))
        for row in db.execute(
            select(Order.customer_id, func.count(Order.id), func.sum(Order.grand_total))
            .where(Order.tenant_id == staff.tenant_id,
                   Order.status.in_(PAID_STATUSES),
                   Order.customer_id.isnot(None))
            .group_by(Order.customer_id)
        ).all()
    }

    stmt = select(Customer).where(Customer.tenant_id == staff.tenant_id,
                                  Customer.deleted_at.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Customer.email.like(like) | Customer.full_name.like(like))

    rows = db.execute(stmt.order_by(Customer.id.desc()).limit(limit)).scalars().all()

    out = []
    for cst in rows:
        orders, spent = stats.get(cst.id, (0, 0.0))
        out.append({
            "public_id": cst.public_id,
            "email": cst.email,
            "full_name": cst.full_name,
            "phone": cst.phone,
            "status": cst.status,
            "is_guest": bool(cst.is_guest),
            "email_verified": cst.email_verified_at is not None,
            "marketing_opt_in": bool(cst.marketing_opt_in),
            "orders": orders,
            "total_spent": spent,
            "last_login_at": cst.last_login_at.isoformat() if cst.last_login_at else None,
            "created_at": cst.created_at.isoformat() if cst.created_at else None,
        })
    return out


@router.get("/customers/summary")
def customers_summary(staff: CurrentStaff = Depends(require("customer.view")),
                      db: Session = Depends(get_read_db)):
    """Headline counts for the top of the page."""
    base = select(func.count(Customer.id)).where(Customer.tenant_id == staff.tenant_id,
                                                 Customer.deleted_at.is_(None))
    total = db.execute(base).scalar() or 0
    blocked = db.execute(base.where(Customer.status == "blocked")).scalar() or 0
    guests = db.execute(base.where(Customer.is_guest.is_(True))).scalar() or 0
    with_orders = db.execute(
        select(func.count(func.distinct(Order.customer_id)))
        .where(Order.tenant_id == staff.tenant_id, Order.customer_id.isnot(None),
               Order.status.in_(PAID_STATUSES))
    ).scalar() or 0
    revenue = db.execute(
        select(func.sum(Order.grand_total))
        .where(Order.tenant_id == staff.tenant_id, Order.status.in_(PAID_STATUSES))
    ).scalar() or 0
    return {
        "total": total, "registered": total - guests, "guests": guests,
        "blocked": blocked, "with_orders": with_orders,
        "revenue": float(revenue),
    }


@router.get("/customers/{public_id}")
def get_customer(public_id: str,
                 staff: CurrentStaff = Depends(require("customer.view")),
                 db: Session = Depends(get_read_db)):
    cst = db.execute(
        select(Customer).where(Customer.tenant_id == staff.tenant_id,
                               Customer.public_id == public_id)
    ).scalar_one_or_none()
    if not cst:
        raise HTTPException(status_code=404, detail="Customer not found")

    orders = db.execute(
        select(Order).where(Order.tenant_id == staff.tenant_id, Order.customer_id == cst.id)
        .order_by(Order.id.desc()).limit(50)
    ).scalars().all()

    return {
        "public_id": cst.public_id, "email": cst.email, "full_name": cst.full_name,
        "phone": cst.phone, "status": cst.status, "is_guest": bool(cst.is_guest),
        "marketing_opt_in": bool(cst.marketing_opt_in),
        "created_at": cst.created_at.isoformat() if cst.created_at else None,
        "last_login_at": cst.last_login_at.isoformat() if cst.last_login_at else None,
        "orders": [{
            "order_number": o.order_number, "public_id": o.public_id,
            "status": o.status, "total": float(o.grand_total),
            "placed_at": o.created_at.isoformat() if o.created_at else None,
        } for o in orders],
    }


@router.patch("/customers/{public_id}/status")
def set_customer_status(public_id: str, body: CustomerStatusIn,
                        staff: CurrentStaff = Depends(require("customer.block")),
                        db: Session = Depends(get_staff_write_db),
                        meta: dict = Depends(client_meta)):
    """Block or unblock a shopper. A blocked customer cannot sign in."""
    if body.status not in ("active", "blocked"):
        raise HTTPException(status_code=400, detail="status must be 'active' or 'blocked'")
    cst = db.execute(
        select(Customer).where(Customer.tenant_id == staff.tenant_id,
                               Customer.public_id == public_id)
    ).scalar_one_or_none()
    if not cst:
        raise HTTPException(status_code=404, detail="Customer not found")

    old = cst.status
    cst.status = body.status
    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="customer.status_changed",
               entity_type="customer", entity_id=cst.id, entity_label=cst.email,
               summary=f"Customer {cst.email}: {old} -> {body.status}",
               old_values={"status": old}, new_values={"status": body.status},
               ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return {"public_id": cst.public_id, "email": cst.email, "status": cst.status}
