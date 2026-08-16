"""ORM models: shoppers, addresses, wishlist, newsletter, reviews."""
from sqlalchemy import (
    BigInteger, Boolean, Column, String, CHAR, Text, Enum, ForeignKey,
    TIMESTAMP, Integer, func,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class Customer(Base):
    __tablename__ = "customers"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    public_id = Column(CHAR(26), unique=True, nullable=False)
    email = Column(String(190), nullable=False)
    phone = Column(String(30))
    password_hash = Column(String(255))
    full_name = Column(String(150))
    preferred_locale = Column(String(10), ForeignKey("locales.code"))
    is_guest = Column(Boolean, default=False)
    email_verified_at = Column(TIMESTAMP)
    marketing_opt_in = Column(Boolean, default=False)
    status = Column(Enum("active", "blocked"), default="active")
    last_login_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(TIMESTAMP)


class CustomerAddress(Base):
    __tablename__ = "customer_addresses"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    customer_id = Column(BigInteger, ForeignKey("customers.id"), nullable=False)
    label = Column(String(40))
    first_name = Column(String(80), nullable=False)
    last_name = Column(String(80), nullable=False)
    phone = Column(String(30), nullable=False)
    line1 = Column(String(200), nullable=False)
    line2 = Column(String(200))
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)
    postal_code = Column(String(20), nullable=False)
    country_code = Column(CHAR(2), default="IN")
    is_default_shipping = Column(Boolean, default=False)
    is_default_billing = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class WishlistItem(Base):
    __tablename__ = "wishlist_items"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    customer_id = Column(BigInteger, ForeignKey("customers.id"), nullable=False)
    product_id = Column(BigInteger, ForeignKey("products.id"), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())


class NewsletterSubscriber(Base):
    __tablename__ = "newsletter_subscribers"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    email = Column(String(190), nullable=False)
    customer_id = Column(BigInteger, ForeignKey("customers.id"))
    locale_code = Column(String(10))
    status = Column(Enum("subscribed", "unsubscribed"), default="subscribed")
    created_at = Column(TIMESTAMP, server_default=func.now())
    unsubscribed_at = Column(TIMESTAMP)


class ProductReview(Base):
    __tablename__ = "product_reviews"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    product_id = Column(BigInteger, ForeignKey("products.id"), nullable=False)
    customer_id = Column(BigInteger, ForeignKey("customers.id"))
    rating = Column(Integer, nullable=False)
    title = Column(String(160))
    body = Column(Text)
    status = Column(Enum("pending", "approved", "rejected"), default="pending")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
