"""Admin/Manager catalog actions — includes the audited price change."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_read_db
from app.core.deps import require, CurrentStaff, client_meta, get_staff_write_db
from app.models.catalog import ProductVariant, InventoryMovement
from app.models.audit import ProductPriceHistory
from app.schemas.api import PriceUpdateIn, StockUpdateIn
from app.services.audit_service import log_action

router = APIRouter(prefix="/admin", tags=["admin: catalog"])


@router.get("/variants")
def list_variants(staff: CurrentStaff = Depends(require("product.view")),
                  db: Session = Depends(get_read_db)):
    rows = db.execute(
        select(ProductVariant).where(ProductVariant.tenant_id == staff.tenant_id).limit(200)
    ).scalars().all()
    return [{"sku": v.sku, "price": float(v.price),
             "stock_available": v.stock_on_hand - v.stock_reserved} for v in rows]


@router.patch("/variants/{sku}/price")
def update_price(sku: str, body: PriceUpdateIn,
                 staff: CurrentStaff = Depends(require("product.price_update")),
                 db: Session = Depends(get_staff_write_db),
                 meta: dict = Depends(client_meta)):
    """
    Change a variant's price. The DB trigger records the change in
    product_price_history automatically (attributed to this staff user,
    because get_staff_write_db ran SET @app_user_id). We ALSO write a
    human-readable audit_logs entry here.
    """
    variant = db.execute(
        select(ProductVariant).where(ProductVariant.tenant_id == staff.tenant_id,
                                     ProductVariant.sku == sku)
    ).scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")

    old = float(variant.price)
    variant.price = body.price
    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="product.price_changed",
               entity_type="variant", entity_id=variant.id, entity_label=variant.sku,
               summary=f"Price {old} -> {body.price}",
               old_values={"price": old}, new_values={"price": body.price},
               ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return {"sku": sku, "old_price": old, "new_price": body.price}


@router.patch("/variants/{sku}/stock")
def update_stock(sku: str, body: StockUpdateIn,
                 staff: CurrentStaff = Depends(require("inventory.manage")),
                 db: Session = Depends(get_staff_write_db),
                 meta: dict = Depends(client_meta)):
    """Set stock-on-hand for a variant (restock / correction)."""
    variant = db.execute(
        select(ProductVariant).where(ProductVariant.tenant_id == staff.tenant_id,
                                     ProductVariant.sku == sku)
    ).scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")

    old = variant.stock_on_hand
    change = body.stock_on_hand - old
    variant.stock_on_hand = body.stock_on_hand
    db.add(InventoryMovement(tenant_id=staff.tenant_id, variant_id=variant.id, change_qty=change,
                             reason=body.reason if body.reason in
                             ("restock", "sale", "return", "adjustment", "reservation", "release")
                             else "adjustment",
                             reference=f"admin:{staff.user.email}", created_by=staff.user.id))
    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="product.stock_changed",
               entity_type="variant", entity_id=variant.id, entity_label=variant.sku,
               summary=f"Stock {old} -> {body.stock_on_hand}",
               old_values={"stock_on_hand": old}, new_values={"stock_on_hand": body.stock_on_hand},
               ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return {"sku": sku, "old_stock": old, "new_stock": body.stock_on_hand}


@router.get("/variants/{sku}/price-history")
def price_history(sku: str, staff: CurrentStaff = Depends(require("product.view")),
                  db: Session = Depends(get_read_db)):
    variant = db.execute(
        select(ProductVariant).where(ProductVariant.tenant_id == staff.tenant_id,
                                     ProductVariant.sku == sku)
    ).scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")
    rows = db.execute(
        select(ProductPriceHistory).where(ProductPriceHistory.variant_id == variant.id)
        .order_by(ProductPriceHistory.created_at.desc())
    ).scalars().all()
    return [{"old_price": float(r.old_price) if r.old_price is not None else None,
             "new_price": float(r.new_price), "changed_by": r.changed_by,
             "source": r.source, "at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]
