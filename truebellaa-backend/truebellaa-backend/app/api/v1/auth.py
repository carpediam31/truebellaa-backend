"""Auth endpoints for staff (admin panels) and customers (storefront)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_write_db
from app.core.deps import get_tenant, get_current_staff, client_meta, CurrentStaff
from app.models.tenancy import Tenant
from app.schemas.api import (
    StaffLoginIn, RefreshIn, LogoutIn, CustomerRegisterIn, CustomerLoginIn,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


# ---- staff ----
@router.post("/staff/login")
def staff_login(body: StaffLoginIn, tenant: Tenant = Depends(get_tenant),
                db: Session = Depends(get_write_db), meta: dict = Depends(client_meta)):
    return auth_service.staff_login(db, tenant, body.email, body.password, meta)


@router.post("/staff/refresh")
def staff_refresh(body: RefreshIn, db: Session = Depends(get_write_db)):
    return auth_service.refresh_access(db, body.refresh_token)


@router.post("/staff/logout")
def staff_logout(body: LogoutIn, staff: CurrentStaff = Depends(get_current_staff),
                 db: Session = Depends(get_write_db), meta: dict = Depends(client_meta)):
    auth_service.staff_logout(db, staff.user, body.refresh_token, meta)
    return {"status": "logged_out"}


@router.get("/staff/me")
def staff_me(staff: CurrentStaff = Depends(get_current_staff)):
    return {"id": staff.user.id, "name": staff.user.full_name, "email": staff.user.email,
            "permissions": sorted(staff.permissions)}


# ---- customer ----
@router.post("/customer/register")
def customer_register(body: CustomerRegisterIn, tenant: Tenant = Depends(get_tenant),
                      db: Session = Depends(get_write_db), meta: dict = Depends(client_meta)):
    return auth_service.customer_register(db, tenant, body.email, body.password,
                                          body.full_name, meta)


@router.post("/customer/login")
def customer_login(body: CustomerLoginIn, tenant: Tenant = Depends(get_tenant),
                   db: Session = Depends(get_write_db), meta: dict = Depends(client_meta)):
    return auth_service.customer_login(db, tenant, body.email, body.password, meta)
