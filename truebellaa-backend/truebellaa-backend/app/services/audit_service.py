"""
Audit helpers — write to audit_logs and auth_events.

Keep these calls next to any meaningful action (price change, order status
change, login) so the Admin panel's activity feed stays complete.
"""
import socket

from sqlalchemy.orm import Session

from app.models.audit import AuditLog, AuthEvent


def ip_to_bytes(ip: str | None) -> bytes | None:
    """Convert an IP string to packed bytes for the VARBINARY column."""
    if not ip:
        return None
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            return socket.inet_pton(family, ip)
        except OSError:
            continue
    return None


def log_action(
    db: Session,
    *,
    tenant_id: int | None,
    actor_type: str,
    action: str,
    actor_id: int | None = None,
    actor_name: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    entity_label: str | None = None,
    summary: str | None = None,
    old_values: dict | None = None,
    new_values: dict | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    row = AuditLog(
        tenant_id=tenant_id, actor_type=actor_type, actor_id=actor_id,
        actor_name=actor_name, action=action, entity_type=entity_type,
        entity_id=entity_id, entity_label=entity_label, summary=summary,
        old_values=old_values, new_values=new_values,
        ip_address=ip_to_bytes(ip), user_agent=user_agent,
    )
    db.add(row)
    return row


def log_auth(
    db: Session,
    *,
    tenant_id: int,
    actor_type: str,
    event: str,
    actor_id: int | None = None,
    email_tried: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AuthEvent:
    row = AuthEvent(
        tenant_id=tenant_id, actor_type=actor_type, actor_id=actor_id,
        email_tried=email_tried, event=event,
        ip_address=ip_to_bytes(ip), user_agent=user_agent,
    )
    db.add(row)
    return row
