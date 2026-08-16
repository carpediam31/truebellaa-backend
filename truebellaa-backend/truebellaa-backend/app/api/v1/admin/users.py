"""
Admin: staff user management — this powers the staff "Registration" screen.

Only Admins (permission `user.manage`) can create Manager/Sales/Admin
logins. Staff do NOT self-register like customers do; an Admin creates
their account and hands them the email/password.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_read_db
from app.core.deps import require, CurrentStaff, client_meta, get_staff_write_db
from app.core.ids import new_ulid
from app.core.security import hash_password
from app.models.rbac import User, Role, UserRole
from app.schemas.api import StaffCreateIn, StaffStatusIn, StaffRoleUpdateIn
from app.services.audit_service import log_action

router = APIRouter(prefix="/admin", tags=["admin: users"])


def _role_map(db: Session, tenant_id: int) -> dict[str, Role]:
    rows = db.execute(select(Role).where(Role.tenant_id == tenant_id)).scalars().all()
    return {r.code: r for r in rows}


def _serialize(db: Session, user: User) -> dict:
    role_codes = db.execute(
        select(Role.code).join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    ).scalars().all()
    return {
        "public_id": user.public_id, "email": user.email, "full_name": user.full_name,
        "phone": user.phone, "status": user.status, "roles": list(role_codes),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.get("/roles")
def list_roles(staff: CurrentStaff = Depends(require("user.manage")),
               db: Session = Depends(get_read_db)):
    roles = db.execute(select(Role).where(Role.tenant_id == staff.tenant_id)).scalars().all()
    return [{"code": r.code, "name": r.name, "description": r.description} for r in roles]


@router.get("/users")
def list_users(staff: CurrentStaff = Depends(require("user.manage")),
               db: Session = Depends(get_read_db)):
    rows = db.execute(
        select(User).where(User.tenant_id == staff.tenant_id, User.deleted_at.is_(None))
        .order_by(User.id.desc())
    ).scalars().all()
    return [_serialize(db, u) for u in rows]


@router.post("/users", status_code=201)
def create_user(body: StaffCreateIn,
                staff: CurrentStaff = Depends(require("user.manage")),
                db: Session = Depends(get_staff_write_db),
                meta: dict = Depends(client_meta)):
    """Create a new staff login (Admin / Manager / Sales) — the Registration screen."""
    existing = db.execute(
        select(User).where(User.tenant_id == staff.tenant_id, User.email == body.email,
                           User.deleted_at.is_(None))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A staff account with this email already exists")

    roles = _role_map(db, staff.tenant_id)
    role = roles.get(body.role_code)
    if not role:
        raise HTTPException(status_code=400,
                            detail=f"Unknown role '{body.role_code}'. Valid: {', '.join(roles) or 'none configured'}")

    user = User(
        tenant_id=staff.tenant_id, public_id=new_ulid(), email=body.email, phone=body.phone,
        password_hash=hash_password(body.password), full_name=body.full_name, status="active",
    )
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id, tenant_id=staff.tenant_id))
    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="user.created",
               entity_type="user", entity_id=user.id, entity_label=user.email,
               summary=f"Created {body.role_code} account for {user.email}",
               ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return _serialize(db, user)


@router.patch("/users/{public_id}/status")
def update_status(public_id: str, body: StaffStatusIn,
                  staff: CurrentStaff = Depends(require("user.manage")),
                  db: Session = Depends(get_staff_write_db),
                  meta: dict = Depends(client_meta)):
    if body.status not in ("active", "disabled"):
        raise HTTPException(status_code=400, detail="status must be 'active' or 'disabled'")
    user = db.execute(
        select(User).where(User.tenant_id == staff.tenant_id, User.public_id == public_id)
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Staff user not found")
    if user.id == staff.user.id and body.status == "disabled":
        raise HTTPException(status_code=400, detail="You cannot disable your own account")
    old = user.status
    user.status = body.status
    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="user.status_changed",
               entity_type="user", entity_id=user.id, entity_label=user.email,
               summary=f"{old} -> {body.status}", ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return _serialize(db, user)


@router.patch("/users/{public_id}/role")
def update_role(public_id: str, body: StaffRoleUpdateIn,
                staff: CurrentStaff = Depends(require("role.manage")),
                db: Session = Depends(get_staff_write_db),
                meta: dict = Depends(client_meta)):
    user = db.execute(
        select(User).where(User.tenant_id == staff.tenant_id, User.public_id == public_id)
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Staff user not found")
    roles = _role_map(db, staff.tenant_id)
    role = roles.get(body.role_code)
    if not role:
        raise HTTPException(status_code=400, detail=f"Unknown role '{body.role_code}'")

    db.query(UserRole).filter(UserRole.user_id == user.id).delete()
    db.add(UserRole(user_id=user.id, role_id=role.id, tenant_id=staff.tenant_id))
    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="user.role_changed",
               entity_type="user", entity_id=user.id, entity_label=user.email,
               summary=f"Role -> {body.role_code}", ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return _serialize(db, user)
