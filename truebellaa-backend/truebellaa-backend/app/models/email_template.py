"""ORM model: admin-editable transactional email templates."""
from sqlalchemy import (
    BigInteger, Boolean, Column, String, Text, ForeignKey, TIMESTAMP, JSON, func,
)

from app.core.database import Base


class EmailTemplate(Base):
    __tablename__ = "email_templates"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    code = Column(String(60), nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(String(255))
    subject = Column(String(255), nullable=False)
    html_body = Column(Text, nullable=False)
    variables = Column(JSON)
    is_active = Column(Boolean, default=True)
    updated_by = Column(BigInteger, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
