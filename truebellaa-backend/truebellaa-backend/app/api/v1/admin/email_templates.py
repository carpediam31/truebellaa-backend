"""
Admin: edit the transactional email templates.

Lets an Admin change the wording of the welcome / order / payment / shipping
emails without a developer or a redeploy. Every template can be previewed
with sample data and test-sent to a real inbox before it goes live.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_read_db
from app.core.deps import require, CurrentStaff, client_meta, get_staff_write_db
from app.integrations.email_client import send_email
from app.models.email_template import EmailTemplate
from app.schemas.api import EmailTemplateUpdateIn, EmailTestSendIn
from app.services import email_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/admin", tags=["admin: email templates"])

# Realistic stand-in values so a preview looks like a real email.
SAMPLE = {
    "brand": "TrueBellaa",
    "customer_name": "Aarav",
    "customer_email": "aarav@example.com",
    "order_number": "TB100042",
    "order_public_id": "01HZX9Q2K8N4P6R8T0V2W4Y6A8",
    "amount": "2,607.00",
    "currency": "INR",
    "courier_name": "Delhivery",
    "awb_code": "SR123456789IN",
    "tracking_url": "https://shiprocket.co/tracking/SR123456789IN",
}


def _serialize(t: EmailTemplate) -> dict:
    return {
        "code": t.code, "name": t.name, "description": t.description,
        "subject": t.subject, "html_body": t.html_body,
        "variables": t.variables or [], "is_active": bool(t.is_active),
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _get(db: Session, tenant_id: int, code: str) -> EmailTemplate:
    row = db.execute(
        select(EmailTemplate).where(EmailTemplate.tenant_id == tenant_id,
                                    EmailTemplate.code == code)
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"No email template '{code}'")
    return row


@router.get("/email-templates")
def list_templates(staff: CurrentStaff = Depends(require("settings.manage")),
                   db: Session = Depends(get_read_db)):
    rows = db.execute(
        select(EmailTemplate).where(EmailTemplate.tenant_id == staff.tenant_id)
        .order_by(EmailTemplate.id)
    ).scalars().all()
    return [_serialize(t) for t in rows]


@router.get("/email-templates/{code}")
def get_one(code: str, staff: CurrentStaff = Depends(require("settings.manage")),
            db: Session = Depends(get_read_db)):
    return _serialize(_get(db, staff.tenant_id, code))


@router.put("/email-templates/{code}")
def update_template(code: str, body: EmailTemplateUpdateIn,
                    staff: CurrentStaff = Depends(require("settings.manage")),
                    db: Session = Depends(get_staff_write_db),
                    meta: dict = Depends(client_meta)):
    tpl = _get(db, staff.tenant_id, code)
    old = {"subject": tpl.subject, "is_active": bool(tpl.is_active)}

    tpl.subject = body.subject
    tpl.html_body = body.html_body
    if body.is_active is not None:
        tpl.is_active = body.is_active
    tpl.updated_by = staff.user.id

    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="email_template.updated",
               entity_type="email_template", entity_id=tpl.id, entity_label=tpl.code,
               summary=f"Edited the '{tpl.name}' email",
               old_values=old, new_values={"subject": tpl.subject, "is_active": bool(tpl.is_active)},
               ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    return _serialize(tpl)


@router.post("/email-templates/{code}/preview")
def preview_template(code: str, body: EmailTemplateUpdateIn | None = None,
                     staff: CurrentStaff = Depends(require("settings.manage")),
                     db: Session = Depends(get_read_db)):
    """
    Render with sample data. Accepts an optional body so the editor can
    preview UNSAVED changes — pass what's in the form and see it rendered
    before committing.
    """
    tpl = _get(db, staff.tenant_id, code)
    subject = body.subject if body else tpl.subject
    html = body.html_body if body else tpl.html_body
    rendered_subject = email_service.render(subject, SAMPLE)
    return {
        "subject": rendered_subject,
        "html": email_service._wrap(rendered_subject, email_service.render(html, SAMPLE)),
        "sample_values": SAMPLE,
    }


@router.post("/email-templates/{code}/test-send")
def test_send(code: str, body: EmailTestSendIn,
              staff: CurrentStaff = Depends(require("settings.manage")),
              db: Session = Depends(get_staff_write_db),
              meta: dict = Depends(client_meta)):
    """Send this template, filled with sample data, to a real inbox."""
    tpl = _get(db, staff.tenant_id, code)
    subject = email_service.render(body.subject or tpl.subject, SAMPLE)
    html = email_service._wrap(
        subject, email_service.render(body.html_body or tpl.html_body, SAMPLE))

    sent = send_email(body.to_email, f"[TEST] {subject}", html)
    log_action(db, tenant_id=staff.tenant_id, actor_type="staff", actor_id=staff.user.id,
               actor_name=staff.user.full_name, action="email_template.test_sent",
               entity_type="email_template", entity_id=tpl.id, entity_label=tpl.code,
               summary=f"Test '{tpl.name}' email to {body.to_email} ({'sent' if sent else 'FAILED'})",
               ip=meta.get("ip"), user_agent=meta.get("user_agent"))
    db.commit()
    if not sent:
        raise HTTPException(
            status_code=502,
            detail="The mail server rejected the message. Check SMTP_* settings in .env "
                   "and the backend log for the exact error.")
    return {"sent": True, "to": body.to_email, "subject": subject}
