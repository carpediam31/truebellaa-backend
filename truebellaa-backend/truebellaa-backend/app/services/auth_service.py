"""Authentication flows for staff and customers."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    verify_password, hash_password, create_access_token, create_refresh_token,
    decode_token, sha256, random_token,
)
from app.core.ids import new_ulid
from app.models.rbac import User, StaffSession
from app.models.customer import Customer
from app.models.tenancy import Tenant
from app.services.audit_service import log_auth, ip_to_bytes


# --------------------------------------------------------------- staff
def staff_login(db: Session, tenant: Tenant, email: str, password: str,
                meta: dict) -> dict:
    user = db.execute(
        select(User).where(User.tenant_id == tenant.id, User.email == email,
                           User.deleted_at.is_(None))
    ).scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        log_auth(db, tenant_id=tenant.id, actor_type="staff", event="login_failed",
                 email_tried=email, ip=meta.get("ip"), user_agent=meta.get("user_agent"))
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is not active")

    claims = {"kind": "staff", "tid": user.tenant_id}
    access = create_access_token(user.id, claims)
    refresh = create_refresh_token(user.id, claims)

    db.add(StaffSession(
        tenant_id=user.tenant_id, user_id=user.id, token_hash=sha256(refresh),
        ip_address=ip_to_bytes(meta.get("ip")), user_agent=meta.get("user_agent"),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    user.last_login_at = datetime.now(timezone.utc)
    log_auth(db, tenant_id=user.tenant_id, actor_type="staff", event="login",
             actor_id=user.id, ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()

    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer",
            "user": {"id": user.id, "public_id": user.public_id, "name": user.full_name,
                     "email": user.email}}


def staff_logout(db: Session, user: User, refresh_token: str | None, meta: dict) -> None:
    if refresh_token:
        sess = db.execute(
            select(StaffSession).where(StaffSession.token_hash == sha256(refresh_token))
        ).scalar_one_or_none()
        if sess and sess.revoked_at is None:
            sess.revoked_at = datetime.now(timezone.utc)
    log_auth(db, tenant_id=user.tenant_id, actor_type="staff", event="logout",
             actor_id=user.id, ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()


def refresh_access(db: Session, refresh_token: str) -> dict:
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    sess = db.execute(
        select(StaffSession).where(StaffSession.token_hash == sha256(refresh_token))
    ).scalar_one_or_none()
    if not sess or sess.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Session expired, please log in")
    claims = {"kind": payload.get("kind", "staff"), "tid": payload.get("tid")}
    return {"access_token": create_access_token(payload["sub"], claims),
            "token_type": "bearer"}


# ------------------------------------------------------------ customer
def customer_register(db: Session, tenant: Tenant, email: str, password: str,
                      full_name: str | None, meta: dict) -> dict:
    exists = db.execute(
        select(Customer).where(Customer.tenant_id == tenant.id, Customer.email == email)
    ).scalar_one_or_none()
    if exists and exists.password_hash:
        raise HTTPException(status_code=409, detail="An account with this email exists")

    if exists:  # upgrade a prior guest record
        customer = exists
        customer.password_hash = hash_password(password)
        customer.full_name = full_name or customer.full_name
        customer.is_guest = False
    else:
        customer = Customer(
            tenant_id=tenant.id, public_id=new_ulid(), email=email,
            password_hash=hash_password(password), full_name=full_name, is_guest=False,
        )
        db.add(customer)
    db.flush()
    db.commit()
    return _customer_tokens(customer)


def customer_login(db: Session, tenant: Tenant, email: str, password: str,
                   meta: dict) -> dict:
    customer = db.execute(
        select(Customer).where(Customer.tenant_id == tenant.id, Customer.email == email)
    ).scalar_one_or_none()
    if not customer or not customer.password_hash or not verify_password(password, customer.password_hash):
        log_auth(db, tenant_id=tenant.id, actor_type="customer", event="login_failed",
                 email_tried=email, ip=meta.get("ip"), user_agent=meta.get("user_agent"))
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if customer.status != "active":
        raise HTTPException(status_code=403, detail="Account is blocked")
    customer.last_login_at = datetime.now(timezone.utc)
    log_auth(db, tenant_id=tenant.id, actor_type="customer", event="login",
             actor_id=customer.id, ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return _customer_tokens(customer)


def _customer_tokens(customer: Customer) -> dict:
    claims = {"kind": "customer", "tid": customer.tenant_id}
    return {
        "access_token": create_access_token(customer.id, claims),
        "refresh_token": create_refresh_token(customer.id, claims),
        "token_type": "bearer",
        "customer": {"id": customer.id, "public_id": customer.public_id,
                     "email": customer.email, "name": customer.full_name},
    }
