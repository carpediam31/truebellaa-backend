"""
Order flow: turn a checkout into an order, reserve stock, and (later) mark paid.

Stock handling (the important bit):
  * At checkout we RESERVE stock (bump stock_reserved + a 'reservation'
    ledger row). This stops two people buying the last piece.
  * When payment succeeds we convert the reservation into a real 'sale'
    (drop stock_on_hand + stock_reserved).
  * If payment never happens, a cleanup job can release reservations.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.ids import new_ulid
from app.models.tenancy import Tenant
from app.models.catalog import ProductVariant, Product, ProductTranslation, InventoryMovement
from app.models.order import Order, OrderItem, OrderStatusHistory
from app.services.audit_service import log_action


def _order_number(db: Session, tenant_id: int) -> str:
    count = db.execute(
        select(func.count(Order.id)).where(Order.tenant_id == tenant_id)
    ).scalar_one()
    return f"TB{100000 + count + 1}"


def _variant_label(db: Session, variant: ProductVariant, locale: str) -> str:
    parts = []
    for av in variant.attribute_values:
        t = next((x for x in av.translations if x.locale_code == locale), None) \
            or next((x for x in av.translations if x.locale_code == "en"), None)
        parts.append(t.label if t else av.code)
    return " / ".join(parts)


def create_order(db: Session, tenant: Tenant, locale: str, *, customer_id: int | None,
                 items: list[dict], contact: dict, shipping: dict) -> Order:
    if not items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    order = Order(
        tenant_id=tenant.id, public_id=new_ulid(),
        order_number=_order_number(db, tenant.id), customer_id=customer_id,
        locale_code=locale, currency_code=tenant.default_currency_code,
        status="pending_payment",
        contact_email=contact["email"], contact_phone=contact["phone"],
        ship_first_name=shipping["first_name"], ship_last_name=shipping["last_name"],
        ship_line1=shipping["line1"], ship_line2=shipping.get("line2"),
        ship_city=shipping["city"], ship_state=shipping["state"],
        ship_postal_code=shipping["postal_code"],
        ship_country_code=shipping.get("country_code", "IN"),
    )
    db.add(order)
    db.flush()

    subtotal = 0.0
    for line in items:
        variant = db.execute(
            select(ProductVariant).where(ProductVariant.tenant_id == tenant.id,
                                         ProductVariant.sku == line["sku"])
        ).scalar_one_or_none()
        if not variant:
            raise HTTPException(status_code=404, detail=f"SKU {line['sku']} not found")
        qty = int(line["qty"])
        if variant.stock_on_hand - variant.stock_reserved < qty:
            raise HTTPException(status_code=409,
                                detail=f"Not enough stock for {variant.sku}")

        # product name snapshot in the order's locale
        tr = db.execute(
            select(ProductTranslation).where(ProductTranslation.product_id == variant.product_id,
                                             ProductTranslation.locale_code == locale)
        ).scalar_one_or_none() or db.execute(
            select(ProductTranslation).where(ProductTranslation.product_id == variant.product_id,
                                             ProductTranslation.locale_code == "en")
        ).scalar_one_or_none()
        product_name = tr.name if tr else variant.sku

        line_total = float(variant.price) * qty
        subtotal += line_total
        db.add(OrderItem(
            tenant_id=tenant.id, order_id=order.id, product_id=variant.product_id,
            variant_id=variant.id, product_name=product_name,
            variant_label=_variant_label(db, variant, locale), sku=variant.sku,
            unit_price=variant.price, quantity=qty, line_total=line_total,
        ))
        # reserve stock
        variant.stock_reserved += qty
        db.add(InventoryMovement(tenant_id=tenant.id, variant_id=variant.id,
                                 change_qty=-qty, reason="reservation",
                                 reference=order.order_number))

    order.subtotal = subtotal
    order.grand_total = subtotal + float(order.shipping_total) + float(order.tax_total) - float(order.discount_total)
    db.add(OrderStatusHistory(tenant_id=tenant.id, order_id=order.id,
                              from_status=None, to_status="pending_payment",
                              note="Order created"))
    db.flush()
    return order


def mark_paid(db: Session, order: Order, *, note: str = "Payment captured") -> None:
    if order.status == "paid":
        return
    prev = order.status
    order.status = "paid"
    order.placed_at = datetime.now(timezone.utc)

    # convert each reservation into a real sale
    for item in order.items:
        variant = db.get(ProductVariant, item.variant_id)
        if variant:
            variant.stock_reserved = max(0, variant.stock_reserved - item.quantity)
            variant.stock_on_hand = max(0, variant.stock_on_hand - item.quantity)
            db.add(InventoryMovement(tenant_id=order.tenant_id, variant_id=variant.id,
                                     change_qty=-item.quantity, reason="sale",
                                     reference=order.order_number))

    db.add(OrderStatusHistory(tenant_id=order.tenant_id, order_id=order.id,
                              from_status=prev, to_status="paid", note=note))
    log_action(db, tenant_id=order.tenant_id, actor_type="system",
               action="order.paid", entity_type="order", entity_id=order.id,
               entity_label=order.order_number, summary=f"Order {order.order_number} paid")


def get_order(db: Session, tenant: Tenant, public_id: str) -> Order | None:
    return db.execute(
        select(Order).where(Order.tenant_id == tenant.id, Order.public_id == public_id)
    ).scalar_one_or_none()
