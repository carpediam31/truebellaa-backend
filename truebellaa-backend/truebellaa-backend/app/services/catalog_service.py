"""Catalog reads: product listing and product detail, in the chosen language."""
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.i18n import pick_translation
from app.models.tenancy import Tenant
from app.models.catalog import Product, ProductVariant, Attribute, AttributeValue


def _default_variant(product: Product) -> ProductVariant | None:
    for v in product.variants:
        if v.is_default:
            return v
    return product.variants[0] if product.variants else None


def _images_sorted(product: Product) -> list[str]:
    return [i.url for i in sorted(product.images, key=lambda i: (not i.is_primary, i.position))]


def _primary_image(product: Product) -> str | None:
    imgs = _images_sorted(product)
    return imgs[0] if imgs else None


def _attr_code_map(db: Session, tenant: Tenant) -> dict[int, str]:
    """{attribute_id: 'metal'|'length'} so we can classify attribute values."""
    rows = db.execute(
        select(Attribute.id, Attribute.code).where(Attribute.tenant_id == tenant.id)
    ).all()
    return {r[0]: r[1] for r in rows}


def list_products(db: Session, tenant: Tenant, locale: str, *, category: str | None = None,
                  metals: list[str] | None = None, in_stock: bool = False,
                  sort: str = "featured", limit: int = 24, offset: int = 0) -> list[dict]:
    stmt = (
        select(Product)
        .where(Product.tenant_id == tenant.id, Product.status == "active",
               Product.deleted_at.is_(None))
        .options(selectinload(Product.translations), selectinload(Product.images),
                 selectinload(Product.variants)
                 .selectinload(ProductVariant.attribute_values)
                 .selectinload(AttributeValue.translations))
    )
    products = list(db.execute(stmt).scalars().all())
    attr_code = _attr_code_map(db, tenant)

    # category filter (by slug)
    if category and category != "all":
        products = [p for p in products if p.category and p.category.slug == category]
    # metal filter (variant carries the metal attribute value)
    if metals:
        wanted = {m.lower() for m in metals}
        products = [p for p in products
                    if any(av.code in wanted for v in p.variants for av in v.attribute_values)]
    if in_stock:
        products = [p for p in products
                    if any((v.stock_on_hand - v.stock_reserved) > 0 for v in p.variants)]

    items = []
    for p in products:
        tr = pick_translation(p.translations, locale, tenant.default_locale_code)
        dv = _default_variant(p)
        imgs = _images_sorted(p)

        # derive the product's metal (single per product in this catalog) and
        # its available lengths (localized labels), for the storefront cards.
        metal_name, length_opts = None, []
        seen_len = set()
        for v in sorted(p.variants, key=lambda x: (not x.is_default, x.id)):
            for av in v.attribute_values:
                kind = attr_code.get(av.attribute_id)
                if kind == "metal" and metal_name is None:
                    metal_name = av.code.title()  # gold -> Gold
                elif kind == "length" and av.code not in seen_len:
                    seen_len.add(av.code)
                    lab = pick_translation(av.translations, locale, tenant.default_locale_code)
                    length_opts.append(lab.label if lab else av.code)

        items.append({
            "public_id": p.public_id, "slug": p.slug,
            "name": tr.name if tr else p.slug,
            "price": float(dv.price) if dv else float(p.base_price),
            "currency": p.currency_code,
            "image": imgs[0] if imgs else None,
            "alt": imgs[1] if len(imgs) > 1 else (imgs[0] if imgs else None),
            "metal": metal_name,
            "lengths": length_opts,
            "stock": (dv.stock_on_hand - dv.stock_reserved) if dv else 0,
            "default_sku": dv.sku if dv else None,
            "rating_avg": float(p.rating_avg), "rating_count": p.rating_count,
            "category": p.category.slug if p.category else None,
        })

    if sort == "low":
        items.sort(key=lambda x: x["price"])
    elif sort == "high":
        items.sort(key=lambda x: x["price"], reverse=True)
    elif sort == "name":
        items.sort(key=lambda x: x["name"].lower())
    return items[offset: offset + limit]


def get_product_detail(db: Session, tenant: Tenant, locale: str, slug: str) -> dict | None:
    product = db.execute(
        select(Product).where(Product.tenant_id == tenant.id, Product.slug == slug,
                              Product.deleted_at.is_(None))
        .options(selectinload(Product.translations), selectinload(Product.images),
                 selectinload(Product.variants).selectinload(ProductVariant.attribute_values))
    ).scalar_one_or_none()
    if not product:
        return None

    tr = pick_translation(product.translations, locale, tenant.default_locale_code)

    # Build the localized label map for attribute values used by this product.
    def label(av: AttributeValue) -> str:
        t = pick_translation(av.translations, locale, tenant.default_locale_code)
        return t.label if t else av.code

    variants = []
    metals, lengths = {}, {}
    for v in product.variants:
        attrs = {}
        for av in v.attribute_values:
            attr = db.get(Attribute, av.attribute_id)
            attrs[attr.code] = {"code": av.code, "label": label(av), "hex": av.hex_color}
            if attr.code == "metal":
                metals[av.code] = attrs[attr.code]
            elif attr.code == "length":
                lengths[av.code] = attrs[attr.code]
        variants.append({
            "sku": v.sku, "price": float(v.price),
            "compare_at_price": float(v.compare_at_price) if v.compare_at_price else None,
            "stock_available": v.stock_on_hand - v.stock_reserved,
            "is_default": v.is_default, "attributes": attrs,
        })

    return {
        "public_id": product.public_id, "slug": product.slug,
        "name": tr.name if tr else product.slug,
        "short_description": tr.short_description if tr else None,
        "description": tr.description if tr else None,
        "care_instructions": tr.care_instructions if tr else None,
        "currency": product.currency_code,
        "base_price": float(product.base_price),
        "rating_avg": float(product.rating_avg), "rating_count": product.rating_count,
        "category": product.category.slug if product.category else None,
        "images": [i.url for i in sorted(product.images, key=lambda x: (not x.is_primary, x.position))],
        "options": {"metals": list(metals.values()), "lengths": list(lengths.values())},
        "variants": variants,
    }
