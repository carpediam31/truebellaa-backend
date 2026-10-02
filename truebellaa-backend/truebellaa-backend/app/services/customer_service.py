"""Logged-in shopper self-service: profile, order history, wishlist."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.i18n import pick_translation
from app.models.tenancy import Tenant
from app.models.customer import Customer, WishlistItem
from app.models.order import Order
from app.models.catalog import Product, ProductVariant


def get_profile(customer: Customer) -> dict:
    return {
        "id": customer.public_id, "email": customer.email,
        "full_name": customer.full_name, "phone": customer.phone,
        "marketing_opt_in": bool(customer.marketing_opt_in),
    }


def list_orders(db: Session, tenant: Tenant, customer: Customer) -> list[dict]:
    orders = db.execute(
        select(Order).where(Order.tenant_id == tenant.id, Order.customer_id == customer.id)
        .options(selectinload(Order.items))
        .order_by(Order.id.desc())
    ).scalars().all()
    return [{
        "order_number": o.order_number, "public_id": o.public_id,
        "status": o.status, "grand_total": float(o.grand_total),
        "currency": o.currency_code, "item_count": sum(i.quantity for i in o.items),
        "placed_at": o.placed_at.isoformat() if o.placed_at else None,
    } for o in orders]


def _product_card(db: Session, tenant: Tenant, locale: str, product: Product) -> dict:
    tr = pick_translation(product.translations, locale, tenant.default_locale_code)
    dv = next((v for v in product.variants if v.is_default), None) or \
        (product.variants[0] if product.variants else None)
    imgs = sorted(product.images, key=lambda i: (not i.is_primary, i.position))
    return {
        "public_id": product.public_id, "slug": product.slug,
        "name": tr.name if tr else product.slug,
        "price": float(dv.price) if dv else float(product.base_price),
        "currency": product.currency_code,
        "image": imgs[0].url if imgs else None,
        "alt": imgs[1].url if len(imgs) > 1 else (imgs[0].url if imgs else None),
        "default_sku": dv.sku if dv else None,
        "stock": (dv.stock_on_hand - dv.stock_reserved) if dv else 0,
        "category": product.category.slug if product.category else None,
        "rating_avg": float(product.rating_avg), "rating_count": product.rating_count,
    }


def list_wishlist(db: Session, tenant: Tenant, locale: str, customer: Customer) -> list[dict]:
    rows = db.execute(
        select(WishlistItem).where(WishlistItem.tenant_id == tenant.id,
                                   WishlistItem.customer_id == customer.id)
        .order_by(WishlistItem.id.desc())
    ).scalars().all()
    if not rows:
        return []
    product_ids = [r.product_id for r in rows]
    products = db.execute(
        select(Product).where(Product.id.in_(product_ids))
        .options(selectinload(Product.translations), selectinload(Product.images),
                 selectinload(Product.variants))
    ).scalars().all()
    by_id = {p.id: p for p in products}
    return [_product_card(db, tenant, locale, by_id[r.product_id])
            for r in rows if r.product_id in by_id]


def _get_product_by_slug(db: Session, tenant: Tenant, slug: str) -> Product:
    product = db.execute(
        select(Product).where(Product.tenant_id == tenant.id, Product.slug == slug,
                              Product.deleted_at.is_(None))
    ).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def add_wishlist(db: Session, tenant: Tenant, customer: Customer, slug: str) -> dict:
    product = _get_product_by_slug(db, tenant, slug)
    existing = db.execute(
        select(WishlistItem).where(WishlistItem.tenant_id == tenant.id,
                                   WishlistItem.customer_id == customer.id,
                                   WishlistItem.product_id == product.id)
    ).scalar_one_or_none()
    if not existing:
        db.add(WishlistItem(tenant_id=tenant.id, customer_id=customer.id, product_id=product.id))
        db.commit()
    return {"status": "added", "slug": slug}


def remove_wishlist(db: Session, tenant: Tenant, customer: Customer, slug: str) -> dict:
    product = _get_product_by_slug(db, tenant, slug)
    existing = db.execute(
        select(WishlistItem).where(WishlistItem.tenant_id == tenant.id,
                                   WishlistItem.customer_id == customer.id,
                                   WishlistItem.product_id == product.id)
    ).scalar_one_or_none()
    if existing:
        db.delete(existing)
        db.commit()
    return {"status": "removed", "slug": slug}
