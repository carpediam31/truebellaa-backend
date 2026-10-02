"""Auth endpoints for staff (admin panels) and customers (storefront)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core import ratelimit
from app.core.config import settings
from app.core.database import get_write_db
from app.core.deps import get_tenant, get_current_staff, client_meta, CurrentStaff
from app.models.tenancy import Tenant
from app.schemas.api import (
    StaffLoginIn, RefreshIn, LogoutIn, CustomerRegisterIn, CustomerLoginIn,
    OtpRequestIn, OtpRegisterIn, OtpLoginIn,
)
from app.services import auth_service, otp_service

router = APIRouter(prefix="/auth", tags=["auth"])


# ---- staff ----
@router.post("/staff/login")
def staff_login(body: StaffLoginIn, tenant: Tenant = Depends(get_tenant),
                db: Session = Depends(get_write_db), meta: dict = Depends(client_meta)):
    """
    Staff sign-in, throttled per email+IP so an admin password can't be
    brute-forced. A correct password clears the counter immediately, so a
    legitimate user who mistypes a few times is not punished for long.
    """
    key = f"staff:{body.email.lower()}:{meta.get('ip') or '-'}"
    wait = ratelimit.seconds_until_unblocked(key)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed sign-in attempts. Try again in {wait // 60 + 1} minute(s).",
            headers={"Retry-After": str(wait)},
        )
    try:
        result = auth_service.staff_login(db, tenant, body.email, body.password, meta)
    except HTTPException as exc:
        if exc.status_code in (400, 401, 403):
            ratelimit.record_failure(key)
        raise
    ratelimit.reset(key)
    return result


@router.post("/staff/refresh")
def staff_refresh(body: RefreshIn, db: Session = Depends(get_write_db)):
    return auth_service.refresh_access(db, body.refresh_token)


@router.post("/staff/logout")
def staff_logout(body: LogoutIn, staff: CurrentStaff = Depends(get_current_staff),
                 db: Session = Depends(get_write_db), meta: dict = Depends(client_meta)):
    auth_service.staff_logout(db, staff.user, body.refresh_token, meta)
    return {"status": "logged_out"}


@router.post("/staff/logout-all")
def staff_logout_all(staff: CurrentStaff = Depends(get_current_staff),
                     db: Session = Depends(get_write_db),
                     meta: dict = Depends(client_meta)):
    """Log out of every device — use if a password may have leaked."""
    n = auth_service.staff_logout_everywhere(db, staff.user, meta)
    return {"status": "logged_out_everywhere", "sessions_ended": n}


@router.get("/staff/me")
def staff_me(staff: CurrentStaff = Depends(get_current_staff)):
    return {"id": staff.user.id, "name": staff.user.full_name, "email": staff.user.email,
            "permissions": sorted(staff.permissions)}


# ---- customer ----
@router.post("/customer/otp/request")
def customer_otp_request(body: OtpRequestIn, tenant: Tenant = Depends(get_tenant),
                         db: Session = Depends(get_write_db),
                         meta: dict = Depends(client_meta)):
    """
    Email a 6-digit code, for creating an account or for passwordless login.

    The response never says whether the address already has an account —
    that would let anyone enumerate your customer list.
    """
    purpose = "login" if body.purpose == "login" else "register"
    result = otp_service.request_otp(db, tenant, body.email, purpose, meta.get("ip"))
    if not result.get("sent") and result.get("retry_after_seconds"):
        raise HTTPException(status_code=429, detail=result.get("detail"),
                            headers={"Retry-After": str(result["retry_after_seconds"])})
    return {"sent": True, "expires_in_minutes": result.get("expires_in_minutes"),
            "message": f"If {body.email} is a valid address, a code is on its way."}


@router.post("/customer/otp/register")
def customer_otp_register(body: OtpRegisterIn, tenant: Tenant = Depends(get_tenant),
                          db: Session = Depends(get_write_db),
                          meta: dict = Depends(client_meta)):
    """Create the account — only after the emailed code checks out."""
    ok, message = otp_service.verify_otp(db, tenant, body.email, body.code, "register")
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return auth_service.customer_register(db, tenant, body.email, body.password,
                                          body.full_name, meta)


@router.post("/customer/otp/login")
def customer_otp_login(body: OtpLoginIn, tenant: Tenant = Depends(get_tenant),
                       db: Session = Depends(get_write_db),
                       meta: dict = Depends(client_meta)):
    """Passwordless sign-in with an emailed code."""
    ok, message = otp_service.verify_otp(db, tenant, body.email, body.code, "login")
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return auth_service.customer_login_without_password(db, tenant, body.email, meta)


@router.post("/customer/register")
def customer_register(body: CustomerRegisterIn, tenant: Tenant = Depends(get_tenant),
                      db: Session = Depends(get_write_db), meta: dict = Depends(client_meta)):
    """
    Legacy direct registration (no email verification).

    Disabled by default now that OTP exists — leaving it open would let
    anyone create an account on someone else's email address, which is
    exactly what the OTP flow prevents. Flip REQUIRE_OTP_SIGNUP=false in
    .env only if you need the old behaviour back temporarily.
    """
    if settings.REQUIRE_OTP_SIGNUP:
        raise HTTPException(
            status_code=403,
            detail="Email verification is required. Request a code at "
                   "/auth/customer/otp/request, then register at /auth/customer/otp/register.",
        )
    return auth_service.customer_register(db, tenant, body.email, body.password,
                                          body.full_name, meta)


@router.post("/customer/login")
def customer_login(body: CustomerLoginIn, tenant: Tenant = Depends(get_tenant),
                   db: Session = Depends(get_write_db), meta: dict = Depends(client_meta)):
    return auth_service.customer_login(db, tenant, body.email, body.password, meta)
