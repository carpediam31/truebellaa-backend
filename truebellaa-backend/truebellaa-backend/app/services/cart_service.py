"""Server-side cart: create/find a cart, add items with a price snapshot."""
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.tenancy import Tenant
from app.models.catalog import ProductVariant
from app.models.order import Cart, CartItem


def get_or_create_cart(db: Session, tenant: Tenant, *, customer_id: int | None,
                       session_token: str | None) -> Cart:
    stmt = select(Cart).where(Cart.tenant_id == tenant.id, Cart.status == "active")
    if customer_id:
        stmt = stmt.where(Cart.customer_id == customer_id)
    elif session_token:
        stmt = stmt.where(Cart.session_token == session_token)
    else:
        session_token = str(uuid.uuid4())
        stmt = stmt.where(Cart.session_token == session_token)

    cart = db.execute(stmt).scalars().first()
    if not cart:
        cart = Cart(tenant_id=tenant.id, customer_id=customer_id,
                    session_token=session_token or str(uuid.uuid4()))
        db.add(cart)
        db.flush()
    return cart


def add_item(db: Session, tenant: Tenant, cart: Cart, sku: str, qty: int) -> Cart:
    variant = db.execute(
        select(ProductVariant).where(ProductVariant.tenant_id == tenant.id,
                                     ProductVariant.sku == sku,
                                     ProductVariant.is_active == True)  # noqa: E712
    ).scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail=f"SKU {sku} not found")
    if qty < 1:
        raise HTTPException(status_code=400, detail="Quantity must be at least 1")

    existing = db.execute(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.variant_id == variant.id)
    ).scalar_one_or_none()
    if existing:
        existing.quantity += qty
    else:
        db.add(CartItem(tenant_id=tenant.id, cart_id=cart.id, variant_id=variant.id,
                        quantity=qty, unit_price=variant.price))
    db.flush()
    return cart


def serialize_cart(db: Session, cart: Cart) -> dict:
    cart = db.execute(
        select(Cart).where(Cart.id == cart.id)
        .options(selectinload(Cart.items).selectinload(CartItem.variant))
    ).scalar_one()
    items, total = [], 0.0
    for it in cart.items:
        line = float(it.unit_price) * it.quantity
        total += line
        items.append({"sku": it.variant.sku, "quantity": it.quantity,
                      "unit_price": float(it.unit_price), "line_total": line})
    return {"cart_token": cart.session_token, "items": items,
            "item_count": sum(i["quantity"] for i in items), "subtotal": total}
