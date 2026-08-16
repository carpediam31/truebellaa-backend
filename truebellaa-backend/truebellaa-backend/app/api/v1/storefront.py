"""Small storefront extras: newsletter signup."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_write_db
from app.core.deps import get_tenant, get_locale
from app.models.tenancy import Tenant
from app.models.customer import NewsletterSubscriber
from app.schemas.api import NewsletterIn

router = APIRouter(prefix="/newsletter", tags=["storefront"])


@router.post("/subscribe")
def subscribe(body: NewsletterIn, tenant: Tenant = Depends(get_tenant),
              locale: str = Depends(get_locale), db: Session = Depends(get_write_db)):
    existing = db.execute(
        select(NewsletterSubscriber).where(NewsletterSubscriber.tenant_id == tenant.id,
                                           NewsletterSubscriber.email == body.email)
    ).scalar_one_or_none()
    if existing:
        existing.status = "subscribed"
    else:
        db.add(NewsletterSubscriber(tenant_id=tenant.id, email=body.email, locale_code=locale))
    db.commit()
    return {"status": "subscribed", "email": body.email}
