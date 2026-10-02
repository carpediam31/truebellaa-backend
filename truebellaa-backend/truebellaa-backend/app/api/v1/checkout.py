"""Checkout: create an order from the cart form, then start a Razorpay payment."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_write_db
from app.core.deps import get_tenant, get_locale, get_optional_customer
from app.models.tenancy import Tenant
from app.models.customer import Customer
from app.schemas.api import CheckoutIn
from app.services import order_service, payment_service, email_service, settings_service

router = APIRouter(prefix="/checkout", tags=["checkout"])


@router.post("")
def checkout(body: CheckoutIn, tenant: Tenant = Depends(get_tenant),
             locale: str = Depends(get_locale),
             customer: Customer | None = Depends(get_optional_customer),
             db: Session = Depends(get_write_db)):
    """
    1) Create the order (status pending_payment) + reserve stock.
    2) Create a Razorpay order and return what the frontend needs to open
       the Razorpay widget. In demo mode (no keys), the frontend can call
       /payments/verify directly to simulate success.

    By default a shopper must be logged in. Without that, anyone can place
    an order against someone else's email address — which also undermines
    the OTP we require at signup. Admins can allow guest checkout again
    from Settings -> Orders.
    """
    if settings_service.get(db, tenant.id, "require_login_checkout") and customer is None:
        raise HTTPException(
            status_code=401,
            detail="Please log in to place your order. Creating an account takes "
                   "a moment — we email you a code to confirm your address.",
        )

    # A logged-in shopper's own email is the one we trust, so an order can
    # never be filed under an address they don't own.
    contact_email = customer.email if customer else body.email

    order = order_service.create_order(
        db, tenant, locale,
        customer_id=customer.id if customer else None,
        items=[{"sku": i.sku, "qty": i.qty} for i in body.items],
        contact={"email": contact_email, "phone": body.phone},
        shipping={"first_name": body.fname, "last_name": body.lname,
                  "line1": body.addr, "line2": body.addr2, "city": body.city,
                  "state": body.state, "postal_code": body.pin, "country_code": "IN"},
    )
    db.commit()
    email_service.send_order_placed_email(order, db)
    return payment_service.create_payment_for_order(db, tenant, order)
