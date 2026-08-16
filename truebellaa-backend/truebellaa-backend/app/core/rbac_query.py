"""Look up the set of permission codes a staff user has, via their roles."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.rbac import UserRole, RolePermission
from app.models.tenancy import Permission


def staff_permission_codes(db: Session, user_id: int) -> set[str]:
    rows = db.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
    ).scalars().all()
    return set(rows)
