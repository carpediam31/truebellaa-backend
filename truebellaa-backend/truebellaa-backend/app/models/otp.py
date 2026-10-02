"""ORM model: one-time email verification codes."""
from sqlalchemy import (
    BigInteger, Column, String, CHAR, Enum, ForeignKey, TIMESTAMP, SmallInteger,
    LargeBinary, func,
)

from app.core.database import Base


class EmailOtp(Base):
    __tablename__ = "email_otps"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    email = Column(String(190), nullable=False)
    purpose = Column(Enum("register", "login"), default="register", nullable=False)
    code_hash = Column(CHAR(64), nullable=False)
    attempts = Column(SmallInteger, default=0)
    max_attempts = Column(SmallInteger, default=5)
    expires_at = Column(TIMESTAMP, nullable=False)
    consumed_at = Column(TIMESTAMP)
    ip_address = Column(LargeBinary(16))
    created_at = Column(TIMESTAMP, server_default=func.now())
