"""ORM models: staff users, roles, permissions mapping, sessions."""
from sqlalchemy import (
    BigInteger, Boolean, Column, String, CHAR, Enum, ForeignKey, TIMESTAMP,
    func, LargeBinary,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    """Back-office staff (Admin / Manager / Sales)."""
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    public_id = Column(CHAR(26), unique=True, nullable=False)
    email = Column(String(190), nullable=False)
    phone = Column(String(30))
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(150), nullable=False)
    status = Column(Enum("invited", "active", "disabled"), default="invited")
    last_login_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(TIMESTAMP)

    roles = relationship("Role", secondary="user_roles", viewonly=True)


class Role(Base):
    __tablename__ = "roles"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    code = Column(String(40), nullable=False)
    name = Column(String(80), nullable=False)
    description = Column(String(255))
    is_system = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    permissions = relationship("Permission", secondary="role_permissions", viewonly=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id = Column(BigInteger, ForeignKey("roles.id"), primary_key=True)
    permission_id = Column(BigInteger, ForeignKey("permissions.id"), primary_key=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id = Column(BigInteger, ForeignKey("users.id"), primary_key=True)
    role_id = Column(BigInteger, ForeignKey("roles.id"), primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)


class StaffSession(Base):
    __tablename__ = "staff_sessions"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    token_hash = Column(CHAR(64), unique=True, nullable=False)
    ip_address = Column(LargeBinary(16))
    user_agent = Column(String(255))
    expires_at = Column(TIMESTAMP, nullable=False)
    revoked_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, server_default=func.now())
