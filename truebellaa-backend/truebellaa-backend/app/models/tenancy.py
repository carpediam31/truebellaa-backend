"""ORM models: tenancy + global reference tables + permission catalog."""
from sqlalchemy import (
    BigInteger, Boolean, Column, String, CHAR, Enum, ForeignKey, TIMESTAMP,
    func, JSON,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class Locale(Base):
    __tablename__ = "locales"
    code = Column(String(10), primary_key=True)
    english_name = Column(String(60), nullable=False)
    native_name = Column(String(60), nullable=False)
    is_rtl = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)


class Currency(Base):
    __tablename__ = "currencies"
    code = Column(CHAR(3), primary_key=True)
    symbol = Column(String(8), nullable=False)
    name = Column(String(60), nullable=False)
    decimal_digits = Column(BigInteger, default=2)


class Permission(Base):
    __tablename__ = "permissions"
    id = Column(BigInteger, primary_key=True)
    code = Column(String(80), unique=True, nullable=False)
    category = Column(String(40), nullable=False)
    description = Column(String(255), nullable=False)


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(BigInteger, primary_key=True)
    public_id = Column(CHAR(26), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    slug = Column(String(120), unique=True, nullable=False)
    legal_name = Column(String(200))
    primary_domain = Column(String(190))
    gstin = Column(String(20))
    support_email = Column(String(190))
    support_phone = Column(String(30))
    default_locale_code = Column(String(10), ForeignKey("locales.code"), default="en")
    default_currency_code = Column(CHAR(3), ForeignKey("currencies.code"), default="INR")
    status = Column(Enum("trial", "active", "suspended", "closed"), default="trial")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(TIMESTAMP)


class TenantLocale(Base):
    __tablename__ = "tenant_locales"
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), primary_key=True)
    locale_code = Column(String(10), ForeignKey("locales.code"), primary_key=True)
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)


class TenantSetting(Base):
    __tablename__ = "tenant_settings"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    setting_key = Column(String(120), nullable=False)
    setting_val = Column(JSON)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
