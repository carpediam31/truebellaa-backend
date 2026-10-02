"""
Admin: runtime settings.

Token lifetimes, lockout thresholds, OTP rules, upload limits — all
changeable from the admin panel and live within seconds. No .env edit,
no restart, no redeploy.

Secrets (SMTP/FTP/Razorpay credentials) are deliberately NOT exposed
here: they stay in .env so the API can never read or leak them.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_read_db
from app.core.deps import require, CurrentStaff, client_meta, get_staff_write_db
from app.schemas.api import SettingsUpdateIn
from app.services import settings_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/admin", tags=["admin: settings"])


@router.get("/settings")
def list_settings(staff: CurrentStaff = Depends(require("settings.manage")),
                  db: Session = Depends(get_read_db)):
    return settings_service.describe(db, staff.tenant_id)


@router.put("/settings")
def update_settings(body: SettingsUpdateIn,
                    staff: CurrentStaff = Depends(require("settings.manage")),
                    db: Session = Depends(get_staff_write_db),
                    meta: dict = Depends(client_meta)):
    before = settings_service.load_all(db, staff.tenant_id, fresh=True)
    applied = settings_service.set_many(db, staff.tenant_id, body.values)
    changed = {k: v for k, v in applied.items() if before.get(k) != v}

    if changed:
        log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
                   actor_name=staff.user.full_name, action="settings.updated",
                   entity_type="settings", entity_label="store settings",
                   summary=", ".join(f"{k}: {before.get(k)} -> {v}" for k, v in changed.items()),
                   old_values={k: before.get(k) for k in changed},
                   new_values=changed, ip=meta.get("ip"), user_agent=meta.get("user_agent"))
        db.commit()

    return {"updated": changed, "settings": settings_service.describe(db, staff.tenant_id)}
