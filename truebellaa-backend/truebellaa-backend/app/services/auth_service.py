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
from app.services import email_service


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

    # Lifetimes come from the runtime settings (Admin -> Settings), so they
    # can be changed without touching .env or redeploying.
    from app.services import settings_service
    cfg = settings_service.load_all(db, user.tenant_id)
    access_minutes = cfg.get("access_token_minutes", settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_days = cfg.get("refresh_token_days", settings.REFRESH_TOKEN_EXPIRE_DAYS)

    # Create the session FIRST so both tokens can carry its id as `sid`.
    #
    # Why: a plain JWT is valid until it expires and cannot be taken back,
    # so a stolen access token would keep working even after logout. Binding
    # every token to a session row means each request can confirm the
    # session is still alive — logout, "sign out everywhere" and disabling
    # an account all take effect immediately.
    session = StaffSession(
        tenant_id=user.tenant_id, user_id=user.id, token_hash="",
        ip_address=ip_to_bytes(meta.get("ip")), user_agent=meta.get("user_agent"),
        expires_at=datetime.now(timezone.utc) + timedelta(days=refresh_days),
    )
    db.add(session)
    db.flush()           # assigns session.id

    claims = {"kind": "staff", "tid": user.tenant_id, "sid": session.id}
    access = create_access_token(user.id, claims, minutes=access_minutes)
    refresh = create_refresh_token(user.id, claims, days=refresh_days)
    session.token_hash = sha256(refresh)
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
    # The session row carries its own expiry — without this check a refresh
    # token kept working forever, long after the session should have died.
    if sess.expires_at and sess.expires_at < datetime.utcnow():
        sess.revoked_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=401, detail="Session expired, please log in")
    # Carry the session id into the new access token too, so the renewed
    # token is still revocable the instant this session is logged out.
    claims = {"kind": payload.get("kind", "staff"), "tid": payload.get("tid"),
              "sid": sess.id}
    from app.services import settings_service
    minutes = settings_service.get(db, sess.tenant_id, "access_token_minutes")
    return {"access_token": create_access_token(payload["sub"], claims, minutes=minutes),
            "token_type": "bearer"}


def staff_logout_everywhere(db: Session, user: User, meta: dict) -> int:
    """
    Revoke every active session for this user.

    Use when a password may have leaked: it kills all access tokens on all
    devices at once, because each one is bound to a session row.
    """
    now = datetime.now(timezone.utc)
    sessions = db.execute(
        select(StaffSession).where(StaffSession.user_id == user.id,
                                   StaffSession.revoked_at.is_(None))
    ).scalars().all()
    for s in sessions:
        s.revoked_at = now
    log_auth(db, tenant_id=user.tenant_id, actor_type="staff", event="logout",
             actor_id=user.id, ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return len(sessions)


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
    email_service.send_welcome_email(customer, db)
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


def customer_login_without_password(db: Session, tenant: Tenant, email: str,
                                    meta: dict) -> dict:
    """
    Sign in a customer who has already proved ownership of the address with
    an emailed OTP. The OTP is verified by the CALLER (see
    /auth/customer/otp/login) — this function must never be reachable from
    a route that hasn't done that check.

    An OTP login also creates the account if there isn't one yet, so a
    shopper who only ever checked out as a guest can claim their account
    (and see their past orders) without inventing a password.
    """
    email = email.strip().lower()
    customer = db.execute(
        select(Customer).where(Customer.tenant_id == tenant.id, Customer.email == email)
    ).scalar_one_or_none()

    if not customer:
        customer = Customer(
            tenant_id=tenant.id, public_id=new_ulid(), email=email,
            full_name=None, password_hash=None, is_guest=False, status="active",
        )
        db.add(customer)
        db.flush()
    elif customer.is_guest:
        customer.is_guest = False

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
