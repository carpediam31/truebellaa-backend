"""Marketing / Sales panel: coupons, newsletter list, review moderation."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_read_db
from app.core.deps import require, CurrentStaff, client_meta, get_staff_write_db
from app.models.order import Coupon
from app.models.customer import NewsletterSubscriber, ProductReview
from app.models.catalog import Product, ProductTranslation
from app.schemas.api import CouponCreateIn, CouponStatusIn, ReviewModerateIn
from app.services.audit_service import log_action

router = APIRouter(prefix="/admin", tags=["admin: marketing"])


def _coupon_out(c: Coupon) -> dict:
    return {
        "code": c.code, "discount_type": c.discount_type,
        "discount_value": float(c.discount_value),
        "min_order_total": float(c.min_order_total) if c.min_order_total is not None else None,
        "max_discount": float(c.max_discount) if c.max_discount is not None else None,
        "usage_limit": c.usage_limit, "per_customer_limit": c.per_customer_limit,
        "times_used": c.times_used, "is_active": bool(c.is_active),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


# ---------------------------------------------------------------- coupons
@router.get("/coupons")
def list_coupons(staff: CurrentStaff = Depends(require("coupon.manage")),
                 db: Session = Depends(get_read_db)):
    rows = db.execute(
        select(Coupon).where(Coupon.tenant_id == staff.tenant_id).order_by(Coupon.id.desc())
    ).scalars().all()
    return [_coupon_out(c) for c in rows]


@router.post("/coupons", status_code=201)
def create_coupon(body: CouponCreateIn,
                  staff: CurrentStaff = Depends(require("coupon.manage")),
                  db: Session = Depends(get_staff_write_db),
                  meta: dict = Depends(client_meta)):
    if body.discount_type not in ("percent", "fixed"):
        raise HTTPException(status_code=400, detail="discount_type must be 'percent' or 'fixed'")
    code = body.code.strip().upper()
    exists = db.execute(
        select(Coupon).where(Coupon.tenant_id == staff.tenant_id, Coupon.code == code)
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail=f"Coupon '{code}' already exists")

    coupon = Coupon(
        tenant_id=staff.tenant_id, code=code, discount_type=body.discount_type,
        discount_value=body.discount_value, min_order_total=body.min_order_total,
        max_discount=body.max_discount, usage_limit=body.usage_limit,
        per_customer_limit=body.per_customer_limit, created_by=staff.user.id,
    )
    db.add(coupon)
    db.flush()
    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="coupon.created",
               entity_type="coupon", entity_id=coupon.id, entity_label=code,
               summary=f"Created coupon {code}", ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return _coupon_out(coupon)


@router.patch("/coupons/{code}/status")
def set_coupon_status(code: str, body: CouponStatusIn,
                      staff: CurrentStaff = Depends(require("coupon.manage")),
                      db: Session = Depends(get_staff_write_db),
                      meta: dict = Depends(client_meta)):
    coupon = db.execute(
        select(Coupon).where(Coupon.tenant_id == staff.tenant_id, Coupon.code == code.upper())
    ).scalar_one_or_none()
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")
    coupon.is_active = body.is_active
    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="coupon.status_changed",
               entity_type="coupon", entity_id=coupon.id, entity_label=coupon.code,
               summary=f"is_active -> {body.is_active}", ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return _coupon_out(coupon)


# ------------------------------------------------------------- newsletter
@router.get("/newsletter")
def list_newsletter(staff: CurrentStaff = Depends(require("newsletter.manage")),
                    db: Session = Depends(get_read_db)):
    rows = db.execute(
        select(NewsletterSubscriber).where(NewsletterSubscriber.tenant_id == staff.tenant_id)
        .order_by(NewsletterSubscriber.id.desc()).limit(500)
    ).scalars().all()
    return [{"email": s.email, "status": s.status, "locale_code": s.locale_code,
             "created_at": s.created_at.isoformat() if s.created_at else None} for s in rows]


# ---------------------------------------------------------------- reviews
@router.get("/reviews")
def list_reviews(status: str | None = None,
                 staff: CurrentStaff = Depends(require("review.moderate")),
                 db: Session = Depends(get_read_db)):
    stmt = (
        select(ProductReview, Product.slug, ProductTranslation.name)
        .join(Product, Product.id == ProductReview.product_id)
        .outerjoin(ProductTranslation,
                   (ProductTranslation.product_id == Product.id) & (ProductTranslation.locale_code == "en"))
        .where(ProductReview.tenant_id == staff.tenant_id)
        .order_by(ProductReview.id.desc()).limit(200)
    )
    if status:
        stmt = stmt.where(ProductReview.status == status)
    rows = db.execute(stmt).all()
    return [{
        "id": r.id, "product_slug": slug, "product_name": name,
        "rating": r.rating, "title": r.title, "body": r.body, "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r, slug, name in rows]


@router.patch("/reviews/{review_id}")
def moderate_review(review_id: int, body: ReviewModerateIn,
                    staff: CurrentStaff = Depends(require("review.moderate")),
                    db: Session = Depends(get_staff_write_db),
                    meta: dict = Depends(client_meta)):
    if body.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'approved' or 'rejected'")
    review = db.execute(
        select(ProductReview).where(ProductReview.tenant_id == staff.tenant_id,
                                    ProductReview.id == review_id)
    ).scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    review.status = body.status
    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="review.moderated",
               entity_type="review", entity_id=review.id, entity_label=f"review#{review.id}",
               summary=f"status -> {body.status}", ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return {"id": review.id, "status": review.status}
