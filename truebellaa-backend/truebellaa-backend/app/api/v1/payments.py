"""Payment verification + Razorpay webhook."""
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.orm import Session

from app.core.database import get_write_db
from app.core.deps import get_tenant
from app.models.tenancy import Tenant
from app.schemas.api import PaymentVerifyIn
from app.services import payment_service, order_service

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/verify")
def verify_payment(body: PaymentVerifyIn, tenant: Tenant = Depends(get_tenant),
                   db: Session = Depends(get_write_db)):
    order = order_service.get_order(db, tenant, body.order_public_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return payment_service.verify_and_capture(
        db, tenant, order,
        razorpay_order_id=body.razorpay_order_id,
        razorpay_payment_id=body.razorpay_payment_id,
        signature=body.razorpay_signature,
    )


@router.post("/webhook/razorpay")
async def razorpay_webhook(request: Request,
                           x_razorpay_signature: str | None = Header(default=None),
                           db: Session = Depends(get_write_db)):
    """Razorpay calls this. We store it once and act on it (idempotent)."""
    raw = await request.body()
    return payment_service.handle_webhook(db, raw, x_razorpay_signature or "")
