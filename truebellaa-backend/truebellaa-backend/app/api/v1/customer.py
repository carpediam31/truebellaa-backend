"""Logged-in shopper self-service: profile, order history, wishlist."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_read_db, get_write_db
from app.core.deps import get_tenant, get_locale, get_current_customer
from app.models.tenancy import Tenant
from app.models.customer import Customer
from app.services import customer_service

router = APIRouter(tags=["customer"])


@router.get("/customers/me")
def my_profile(customer: Customer = Depends(get_current_customer)):
    return customer_service.get_profile(customer)


@router.get("/customers/me/orders")
def my_orders(tenant: Tenant = Depends(get_tenant),
             customer: Customer = Depends(get_current_customer),
             db: Session = Depends(get_read_db)):
    return customer_service.list_orders(db, tenant, customer)


@router.get("/wishlist")
def get_wishlist(tenant: Tenant = Depends(get_tenant), locale: str = Depends(get_locale),
                 customer: Customer = Depends(get_current_customer),
                 db: Session = Depends(get_read_db)):
    return customer_service.list_wishlist(db, tenant, locale, customer)


@router.post("/wishlist/{slug}")
def add_to_wishlist(slug: str, tenant: Tenant = Depends(get_tenant),
                    customer: Customer = Depends(get_current_customer),
                    db: Session = Depends(get_write_db)):
    return customer_service.add_wishlist(db, tenant, customer, slug)


@router.delete("/wishlist/{slug}")
def remove_from_wishlist(slug: str, tenant: Tenant = Depends(get_tenant),
                         customer: Customer = Depends(get_current_customer),
                         db: Session = Depends(get_write_db)):
    return customer_service.remove_wishlist(db, tenant, customer, slug)
