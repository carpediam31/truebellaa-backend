"""Admin activity feed: the combined audit + login/logout log."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_read_db
from app.core.deps import require, CurrentStaff

router = APIRouter(prefix="/admin", tags=["admin: audit"])


@router.get("/activity")
def activity_feed(limit: int = 50,
                  staff: CurrentStaff = Depends(require("audit.view")),
                  db: Session = Depends(get_read_db)):
    """Reads the v_recent_activity view (audit_logs UNION auth_events)."""
    rows = db.execute(
        text("""
            SELECT created_at, actor_type, actor_id, event, detail
            FROM v_recent_activity
            WHERE tenant_id = :tid
            ORDER BY created_at DESC
            LIMIT :lim
        """),
        {"tid": staff.tenant_id, "lim": limit},
    ).mappings().all()
    return [dict(r) for r in rows]
