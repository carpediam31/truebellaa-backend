"""ORM models: audit log, auth events, price history."""
from sqlalchemy import (
    BigInteger, Column, String, Enum, ForeignKey, TIMESTAMP, Numeric,
    Integer, JSON, LargeBinary, func,
)
from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"))
    actor_type = Column(Enum("staff", "customer", "system"), default="system")
    actor_id = Column(BigInteger)
    actor_name = Column(String(150))
    action = Column(String(80), nullable=False)
    entity_type = Column(String(60))
    entity_id = Column(BigInteger)
    entity_label = Column(String(200))
    summary = Column(String(300))
    old_values = Column(JSON)
    new_values = Column(JSON)
    ip_address = Column(LargeBinary(16))
    user_agent = Column(String(255))
    created_at = Column(TIMESTAMP, server_default=func.now())


class AuthEvent(Base):
    __tablename__ = "auth_events"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    actor_type = Column(Enum("staff", "customer"), nullable=False)
    actor_id = Column(BigInteger)
    email_tried = Column(String(190))
    event = Column(Enum("login", "logout", "login_failed", "password_reset", "password_changed"), nullable=False)
    ip_address = Column(LargeBinary(16))
    user_agent = Column(String(255))
    created_at = Column(TIMESTAMP, server_default=func.now())


class ProductPriceHistory(Base):
    __tablename__ = "product_price_history"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    variant_id = Column(BigInteger, ForeignKey("product_variants.id"), nullable=False)
    product_id = Column(BigInteger)
    old_price = Column(Numeric(12, 2))
    new_price = Column(Numeric(12, 2), nullable=False)
    changed_by = Column(BigInteger)
    source = Column(String(40), default="trigger")
    note = Column(String(255))
    created_at = Column(TIMESTAMP, server_default=func.now())
