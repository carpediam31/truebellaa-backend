"""Server-side cart endpoints (works for guests and logged-in shoppers)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_write_db, get_read_db
from app.core.deps import get_tenant, get_optional_customer
from app.models.tenancy import Tenant
from app.models.customer import Customer
from app.schemas.api import CartAddIn
from app.services import cart_service

router = APIRouter(prefix="/cart", tags=["cart"])


@router.post("/items")
def add_to_cart(body: CartAddIn, tenant: Tenant = Depends(get_tenant),
                customer: Customer | None = Depends(get_optional_customer),
                db: Session = Depends(get_write_db)):
    cart = cart_service.get_or_create_cart(
        db, tenant, customer_id=customer.id if customer else None,
        session_token=body.cart_token,
    )
    cart_service.add_item(db, tenant, cart, body.sku, body.qty)
    db.commit()
    return cart_service.serialize_cart(db, cart)


@router.get("")
def view_cart(tenant: Tenant = Depends(get_tenant),
              customer: Customer | None = Depends(get_optional_customer),
              cart_token: str | None = Query(default=None),
              db: Session = Depends(get_read_db)):
    cart = cart_service.get_or_create_cart(
        db, tenant, customer_id=customer.id if customer else None, session_token=cart_token,
    )
    return cart_service.serialize_cart(db, cart)
