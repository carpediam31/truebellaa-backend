"""
Roles & Permissions matrix — lets an Admin change what Manager/Sales can do
without ever touching the database. The 'admin' role itself is locked (it
always has every permission) so nobody can accidentally lock themselves out.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_read_db
from app.core.deps import require, CurrentStaff, client_meta, get_staff_write_db
from app.models.rbac import Role, RolePermission
from app.models.tenancy import Permission
from app.schemas.api import RolePermissionsIn
from app.services.audit_service import log_action

router = APIRouter(prefix="/admin", tags=["admin: roles & permissions"])

LOCKED_ROLE = "admin"  # this role's permissions can never be edited from the UI


@router.get("/permissions")
def list_permissions(staff: CurrentStaff = Depends(require("role.manage")),
                     db: Session = Depends(get_read_db)):
    """The full permission catalog (same for every tenant)."""
    rows = db.execute(select(Permission).order_by(Permission.category, Permission.code)).scalars().all()
    return [{"code": p.code, "category": p.category, "description": p.description} for p in rows]


def _role_or_404(db: Session, tenant_id: int, code: str) -> Role:
    role = db.execute(
        select(Role).where(Role.tenant_id == tenant_id, Role.code == code)
    ).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role '{code}' not found")
    return role


@router.get("/roles/{code}/permissions")
def get_role_permissions(code: str,
                         staff: CurrentStaff = Depends(require("role.manage")),
                         db: Session = Depends(get_read_db)):
    role = _role_or_404(db, staff.tenant_id, code)
    granted = db.execute(
        select(Permission.code).join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role.id)
    ).scalars().all()
    return {"code": role.code, "name": role.name, "locked": role.code == LOCKED_ROLE,
            "permission_codes": sorted(granted)}


@router.put("/roles/{code}/permissions")
def set_role_permissions(code: str, body: RolePermissionsIn,
                         staff: CurrentStaff = Depends(require("role.manage")),
                         db: Session = Depends(get_staff_write_db),
                         meta: dict = Depends(client_meta)):
    if code == LOCKED_ROLE:
        raise HTTPException(status_code=400,
                            detail="The Admin role always has every permission and can't be edited "
                                   "(this prevents anyone from accidentally locking everyone out).")
    role = _role_or_404(db, staff.tenant_id, code)

    # Validate every requested code actually exists.
    valid_codes = set(db.execute(select(Permission.code)).scalars().all())
    requested = set(body.permission_codes)
    unknown = requested - valid_codes
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown permission code(s): {', '.join(sorted(unknown))}")

    perm_ids = db.execute(select(Permission.id).where(Permission.code.in_(requested))).scalars().all() if requested else []

    db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
    for pid in perm_ids:
        db.add(RolePermission(role_id=role.id, permission_id=pid))

    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="role.permissions_changed",
               entity_type="role", entity_id=role.id, entity_label=role.code,
               summary=f"{role.code} -> {len(requested)} permission(s)",
               new_values={"permission_codes": sorted(requested)},
               ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return {"code": role.code, "name": role.name, "permission_codes": sorted(requested)}
