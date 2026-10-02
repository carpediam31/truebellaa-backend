"""Admin/Manager catalog actions — includes the audited price change."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_read_db
from app.core.deps import require, CurrentStaff, client_meta, get_staff_write_db
from app.core.ids import new_ulid
from app.integrations import mileswebstorage_client
from app.models.catalog import (
    Product, ProductTranslation, ProductImage, ProductVariant, InventoryMovement,
)
from app.models.audit import ProductPriceHistory
from app.schemas.api import PriceUpdateIn, StockUpdateIn, ProductCreateIn, ProductUpdateIn
from app.services.audit_service import log_action

router = APIRouter(prefix="/admin", tags=["admin: catalog"])


def _serialize_image(img: ProductImage) -> dict:
    return {
        "id": img.id, "url": img.url, "alt_text": img.alt_text,
        "position": img.position, "is_primary": img.is_primary,
        "original_filename": img.original_filename, "file_extension": img.file_extension,
        "file_size_bytes": img.file_size_bytes,
        "file_size_kb": round(img.file_size_bytes / 1024, 1) if img.file_size_bytes else None,
        "storage_provider": img.storage_provider,
        "created_at": img.created_at.isoformat() if img.created_at else None,
    }


def _serialize_product(p: Product) -> dict:
    en = next((t for t in p.translations if t.locale_code == "en"), p.translations[0] if p.translations else None)
    images = sorted(p.images, key=lambda i: (not i.is_primary, i.position))
    return {
        "public_id": p.public_id, "slug": p.slug, "name": en.name if en else p.slug,
        "sku_prefix": p.sku_prefix, "base_price": float(p.base_price), "currency_code": p.currency_code,
        "status": p.status, "category_id": p.category_id,
        "primary_image": images[0].url if images else None,
        "image_count": len(images),
        "images": [_serialize_image(i) for i in images],
        "variants": [{"sku": v.sku, "price": float(v.price),
                     "stock_available": v.stock_on_hand - v.stock_reserved,
                     "is_default": v.is_default} for v in p.variants],
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _product_or_404(db: Session, tenant_id: int, public_id: str) -> Product:
    product = db.execute(
        select(Product).where(Product.tenant_id == tenant_id, Product.public_id == public_id,
                              Product.deleted_at.is_(None))
        .options(selectinload(Product.translations), selectinload(Product.images),
                 selectinload(Product.variants))
    ).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.get("/products")
def list_products(staff: CurrentStaff = Depends(require("product.view")),
                  db: Session = Depends(get_read_db)):
    rows = db.execute(
        select(Product).where(Product.tenant_id == staff.tenant_id, Product.deleted_at.is_(None))
        .options(selectinload(Product.translations), selectinload(Product.images),
                 selectinload(Product.variants))
        .order_by(Product.id.desc()).limit(200)
    ).scalars().all()
    return [_serialize_product(p) for p in rows]


@router.post("/products", status_code=201)
def create_product(body: ProductCreateIn,
                   staff: CurrentStaff = Depends(require("product.create")),
                   db: Session = Depends(get_staff_write_db),
                   meta: dict = Depends(client_meta)):
    """
    Create a product (+ its translations and, optionally, its first
    variants). Images are attached afterwards via
    POST /admin/products/{public_id}/images, since a browser upload needs
    the product's id first.
    """
    existing = db.execute(
        select(Product).where(Product.tenant_id == staff.tenant_id, Product.slug == body.slug,
                              Product.deleted_at.is_(None))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"A product with slug '{body.slug}' already exists")

    product = Product(
        tenant_id=staff.tenant_id, public_id=new_ulid(), category_id=body.category_id,
        slug=body.slug, sku_prefix=body.sku_prefix, base_price=body.base_price,
        currency_code=body.currency_code, status=body.status,
    )
    db.add(product)
    db.flush()

    for tr in body.translations:
        db.add(ProductTranslation(
            product_id=product.id, locale_code=tr.locale_code, name=tr.name,
            short_description=tr.short_description, description=tr.description,
            care_instructions=tr.care_instructions,
        ))

    has_default = False
    for v in body.variants:
        is_default = v.is_default and not has_default
        has_default = has_default or is_default
        db.add(ProductVariant(
            tenant_id=staff.tenant_id, product_id=product.id, sku=v.sku, price=v.price,
            compare_at_price=v.compare_at_price, stock_on_hand=v.stock_on_hand,
            is_default=is_default, is_active=True,
        ))
    db.flush()
    # If nothing was marked default, the first variant becomes it.
    if body.variants and not has_default:
        first = db.execute(
            select(ProductVariant).where(ProductVariant.product_id == product.id)
            .order_by(ProductVariant.id).limit(1)
        ).scalar_one()
        first.is_default = True

    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="product.created",
               entity_type="product", entity_id=product.id, entity_label=product.slug,
               summary=f"Created product '{body.translations[0].name}' ({body.slug})",
               new_values={"slug": body.slug, "base_price": body.base_price, "status": body.status},
               ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()

    return _serialize_product(_product_or_404(db, staff.tenant_id, product.public_id))


@router.patch("/products/{public_id}")
def update_product(public_id: str, body: ProductUpdateIn,
                   staff: CurrentStaff = Depends(require("product.update")),
                   db: Session = Depends(get_staff_write_db),
                   meta: dict = Depends(client_meta)):
    """
    Edit a product. PATCH semantics — only the fields present in the body
    change, so the admin panel can send a partial form without wiping
    anything it didn't ask about.
    """
    product = _product_or_404(db, staff.tenant_id, public_id)
    # exclude_unset so an omitted field is left alone rather than set to None.
    data = body.model_dump(exclude_unset=True)
    # model_dump() turns nested models into plain dicts, so take the
    # translations off the ORIGINAL body to keep them as typed objects.
    translations = body.translations if "translations" in data else None
    data.pop("translations", None)

    if "status" in data and data["status"] not in ("draft", "active", "archived"):
        raise HTTPException(status_code=400, detail="status must be draft, active or archived")

    if "slug" in data and data["slug"] != product.slug:
        clash = db.execute(
            select(Product).where(Product.tenant_id == staff.tenant_id,
                                  Product.slug == data["slug"],
                                  Product.id != product.id,
                                  Product.deleted_at.is_(None))
        ).scalar_one_or_none()
        if clash:
            raise HTTPException(status_code=409,
                                detail=f"Another product already uses slug '{data['slug']}'")

    old = {k: getattr(product, k) for k in data}
    for field, value in data.items():
        setattr(product, field, value)

    # Translations are upserted per locale so editing English doesn't drop Hindi.
    if translations is not None:
        existing = {t.locale_code: t for t in product.translations}
        for tr in translations:
            row = existing.get(tr.locale_code)
            if row:
                row.name = tr.name
                row.short_description = tr.short_description
                row.description = tr.description
                row.care_instructions = tr.care_instructions
            else:
                db.add(ProductTranslation(
                    product_id=product.id, locale_code=tr.locale_code, name=tr.name,
                    short_description=tr.short_description, description=tr.description,
                    care_instructions=tr.care_instructions,
                ))

    changed = ", ".join(data) + (", translations" if translations is not None else "")
    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="product.updated",
               entity_type="product", entity_id=product.id, entity_label=product.slug,
               summary=f"Updated {changed or 'nothing'}",
               old_values={k: str(v) for k, v in old.items()},
               new_values={k: str(v) for k, v in data.items()},
               ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return _serialize_product(_product_or_404(db, staff.tenant_id, public_id))


@router.delete("/products/{public_id}", status_code=204)
def delete_product(public_id: str,
                   staff: CurrentStaff = Depends(require("product.delete")),
                   db: Session = Depends(get_staff_write_db),
                   meta: dict = Depends(client_meta)):
    """
    Soft-delete: stamps deleted_at so the product vanishes from the
    storefront and admin lists but its rows survive.

    Deliberately NOT a hard delete — past orders reference this product's
    variants, and removing them would corrupt order history and reporting.
    """
    product = _product_or_404(db, staff.tenant_id, public_id)
    product.deleted_at = func.now()
    for v in product.variants:
        v.is_active = False

    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="product.deleted",
               entity_type="product", entity_id=product.id, entity_label=product.slug,
               summary=f"Deleted product '{product.slug}' (soft delete — order history kept)",
               ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return None


@router.post("/products/{public_id}/images", status_code=201)
async def upload_product_image(
    public_id: str,
    file: UploadFile = File(...),
    alt_text: str | None = Form(default=None),
    is_primary: bool = Form(default=False),
    staff: CurrentStaff = Depends(require("product.image_upload")),
    db: Session = Depends(get_staff_write_db),
    meta: dict = Depends(client_meta),
):
    """
    Upload one image for a product to MilesWeb file storage (falls back to
    local disk in DEMO mode — see mileswebstorage_client). Records the
    file's size and extension alongside its URL so the admin panel can
    display them.
    """
    product = _product_or_404(db, staff.tenant_id, public_id)

    data = await file.read()
    try:
        uploaded = mileswebstorage_client.upload_image(data, file.filename or "image", file.content_type)
    except (ValueError, mileswebstorage_client.UnsupportedImageType) as exc:
        # Bad file (wrong type, too big, empty) — the uploader can fix this.
        raise HTTPException(status_code=400, detail=str(exc))
    except mileswebstorage_client.StorageUploadError as exc:
        # The file was fine; MilesWeb storage itself refused or was unreachable.
        raise HTTPException(status_code=502, detail=str(exc))

    if is_primary:
        for img in product.images:
            img.is_primary = False

    next_position = (max((i.position for i in product.images), default=-1) + 1)
    image = ProductImage(
        tenant_id=staff.tenant_id, product_id=product.id, url=uploaded.url,
        alt_text=alt_text, position=next_position,
        is_primary=is_primary or not product.images,  # first image is primary by default
        original_filename=file.filename, file_extension=uploaded.file_extension,
        file_size_bytes=uploaded.file_size_bytes, storage_provider=uploaded.storage_provider,
        storage_path=uploaded.storage_path, uploaded_by=staff.user.id,
    )
    db.add(image)

    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="product.image_uploaded",
               entity_type="product", entity_id=product.id, entity_label=product.slug,
               summary=f"Uploaded {file.filename} ({uploaded.file_size_bytes} bytes, .{uploaded.file_extension}) "
                       f"via {uploaded.storage_provider}",
               new_values={"file_extension": uploaded.file_extension,
                          "file_size_bytes": uploaded.file_size_bytes,
                          "storage_provider": uploaded.storage_provider},
               ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    db.refresh(image)
    return _serialize_image(image)


@router.delete("/products/{public_id}/images/{image_id}", status_code=204)
def delete_product_image(public_id: str, image_id: int,
                         staff: CurrentStaff = Depends(require("product.image_upload")),
                         db: Session = Depends(get_staff_write_db),
                         meta: dict = Depends(client_meta)):
    product = _product_or_404(db, staff.tenant_id, public_id)
    image = next((i for i in product.images if i.id == image_id), None)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found on this product")
    db.delete(image)
    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="product.image_deleted",
               entity_type="product", entity_id=product.id, entity_label=product.slug,
               summary=f"Removed image {image.original_filename or image.url}",
               ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return None


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
