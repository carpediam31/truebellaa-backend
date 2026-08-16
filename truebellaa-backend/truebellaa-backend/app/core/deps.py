"""
FastAPI dependencies: the guards every endpoint reuses.

  * get_tenant          -> which brand is this request for? (multi-tenancy)
  * get_current_staff   -> a logged-in Admin/Manager/Sales user (+ permissions)
  * require("perm")     -> ensure that staff user has a permission (RBAC)
  * get_current_customer-> a logged-in shopper
  * get_locale          -> the language to render in
"""
from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_read_db, get_write_db, set_audit_actor
from app.core.security import decode_token
from app.core.i18n import resolve_locale
from app.models.tenancy import Tenant
from app.models.rbac import User
from app.core.rbac_query import staff_permission_codes
from app.models.customer import Customer

bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------- tenant
def get_tenant(
    x_tenant_slug: str = Header(default="truebellaa", alias="X-Tenant-Slug"),
    db: Session = Depends(get_read_db),
) -> Tenant:
    tenant = db.execute(
        select(Tenant).where(Tenant.slug == x_tenant_slug, Tenant.deleted_at.is_(None))
    ).scalar_one_or_none()
    if not tenant or tenant.status not in ("trial", "active"):
        raise HTTPException(status_code=404, detail="Unknown or inactive store")
    return tenant


# ------------------------------------------------------------ staff auth
@dataclass
class CurrentStaff:
    user: User
    tenant_id: int
    permissions: set[str] = field(default_factory=set)

    def has(self, perm: str) -> bool:
        return perm in self.permissions


def _require_token(creds: HTTPAuthorizationCredentials | None) -> dict:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(creds.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


def get_current_staff(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_read_db),
) -> CurrentStaff:
    payload = _require_token(creds)
    if payload.get("kind") != "staff":
        raise HTTPException(status_code=403, detail="Staff access required")
    user = db.get(User, int(payload["sub"]))
    if not user or user.status != "active" or user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Account not active")
    perms = staff_permission_codes(db, user.id)
    return CurrentStaff(user=user, tenant_id=user.tenant_id, permissions=perms)


def require(*needed: str):
    """Dependency factory: ensure the staff user has ALL listed permissions."""
    def checker(staff: CurrentStaff = Depends(get_current_staff)) -> CurrentStaff:
        missing = [p for p in needed if not staff.has(p)]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"Missing permission(s): {', '.join(missing)}",
            )
        return staff
    return checker


def get_staff_write_db(
    staff: CurrentStaff = Depends(get_current_staff),
    db: Session = Depends(get_write_db),
) -> Session:
    """A PRIMARY session that also tells the DB who is acting (for the price trigger)."""
    set_audit_actor(db, staff.user.id)
    return db


# --------------------------------------------------------- customer auth
def get_current_customer(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_read_db),
) -> Customer:
    payload = _require_token(creds)
    if payload.get("kind") != "customer":
        raise HTTPException(status_code=403, detail="Customer access required")
    customer = db.get(Customer, int(payload["sub"]))
    if not customer or customer.status != "active":
        raise HTTPException(status_code=401, detail="Account not active")
    return customer


def get_optional_customer(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_read_db),
) -> Customer | None:
    """For endpoints that work for guests AND logged-in shoppers."""
    if not creds:
        return None
    try:
        return get_current_customer(creds, db)
    except HTTPException:
        return None


# --------------------------------------------------------------- locale
def get_locale(
    x_locale: str | None = Header(default=None, alias="X-Locale"),
    lang: str | None = None,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_read_db),
) -> str:
    return resolve_locale(db, tenant, lang or x_locale)


# --------------------------------------------------------- request meta
def client_meta(request: Request) -> dict:
    return {
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }
