"""Public storefront catalog: list + detail, language-aware."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_read_db
from app.core.deps import get_tenant, get_locale
from app.models.tenancy import Tenant
from app.services import catalog_service

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/products")
def list_products(
    tenant: Tenant = Depends(get_tenant),
    locale: str = Depends(get_locale),
    db: Session = Depends(get_read_db),
    category: str | None = Query(default=None, description="category slug or 'all'"),
    metal: list[str] | None = Query(default=None, description="gold/silver/steel"),
    in_stock: bool = False,
    sort: str = Query(default="featured", pattern="^(featured|low|high|name)$"),
    limit: int = Query(default=24, le=100),
    offset: int = 0,
):
    items = catalog_service.list_products(
        db, tenant, locale, category=category, metals=metal, in_stock=in_stock,
        sort=sort, limit=limit, offset=offset,
    )
    return {"locale": locale, "count": len(items), "products": items}


@router.get("/products/{slug}")
def product_detail(slug: str, tenant: Tenant = Depends(get_tenant),
                   locale: str = Depends(get_locale), db: Session = Depends(get_read_db)):
    data = catalog_service.get_product_detail(db, tenant, locale, slug)
    if not data:
        raise HTTPException(status_code=404, detail="Product not found")
    data["locale"] = locale
    return data
