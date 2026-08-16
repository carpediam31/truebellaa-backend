"""ORM models: carts, coupons, orders, order items, status history."""
from sqlalchemy import (
    BigInteger, Boolean, Column, String, CHAR, Enum, ForeignKey, TIMESTAMP,
    Numeric, Integer, func,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class Cart(Base):
    __tablename__ = "carts"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    customer_id = Column(BigInteger, ForeignKey("customers.id"))
    session_token = Column(CHAR(36))
    currency_code = Column(CHAR(3), default="INR")
    status = Column(Enum("active", "converted", "abandoned"), default="active")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    items = relationship("CartItem", cascade="all, delete-orphan")


class CartItem(Base):
    __tablename__ = "cart_items"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    cart_id = Column(BigInteger, ForeignKey("carts.id"), nullable=False)
    variant_id = Column(BigInteger, ForeignKey("product_variants.id"), nullable=False)
    quantity = Column(Integer, default=1)
    unit_price = Column(Numeric(12, 2), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    variant = relationship("ProductVariant")


class Coupon(Base):
    __tablename__ = "coupons"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    code = Column(String(40), nullable=False)
    discount_type = Column(Enum("percent", "fixed"), nullable=False)
    discount_value = Column(Numeric(12, 2), nullable=False)
    min_order_total = Column(Numeric(12, 2))
    max_discount = Column(Numeric(12, 2))
    usage_limit = Column(Integer)
    per_customer_limit = Column(Integer)
    times_used = Column(Integer, default=0)
    starts_at = Column(TIMESTAMP)
    ends_at = Column(TIMESTAMP)
    is_active = Column(Boolean, default=True)
    created_by = Column(BigInteger, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP, server_default=func.now())


class Order(Base):
    __tablename__ = "orders"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    public_id = Column(CHAR(26), unique=True, nullable=False)
    order_number = Column(String(20), nullable=False)
    customer_id = Column(BigInteger, ForeignKey("customers.id"))
    cart_id = Column(BigInteger, ForeignKey("carts.id"))
    coupon_id = Column(BigInteger, ForeignKey("coupons.id"))
    locale_code = Column(String(10), default="en")
    currency_code = Column(CHAR(3), ForeignKey("currencies.code"), default="INR")
    status = Column(Enum("pending_payment", "paid", "processing", "shipped",
                         "delivered", "cancelled", "refunded", "returned"),
                    default="pending_payment")
    subtotal = Column(Numeric(12, 2), default=0)
    discount_total = Column(Numeric(12, 2), default=0)
    shipping_total = Column(Numeric(12, 2), default=0)
    tax_total = Column(Numeric(12, 2), default=0)
    grand_total = Column(Numeric(12, 2), default=0)
    contact_email = Column(String(190), nullable=False)
    contact_phone = Column(String(30), nullable=False)
    ship_first_name = Column(String(80), nullable=False)
    ship_last_name = Column(String(80), nullable=False)
    ship_line1 = Column(String(200), nullable=False)
    ship_line2 = Column(String(200))
    ship_city = Column(String(100), nullable=False)
    ship_state = Column(String(100), nullable=False)
    ship_postal_code = Column(String(20), nullable=False)
    ship_country_code = Column(CHAR(2), default="IN")
    customer_note = Column(String(500))
    placed_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    items = relationship("OrderItem", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=False)
    product_id = Column(BigInteger, ForeignKey("products.id"))
    variant_id = Column(BigInteger, ForeignKey("product_variants.id"))
    product_name = Column(String(200), nullable=False)
    variant_label = Column(String(160))
    sku = Column(String(64))
    unit_price = Column(Numeric(12, 2), nullable=False)
    quantity = Column(Integer, nullable=False)
    line_total = Column(Numeric(12, 2), nullable=False)


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=False)
    from_status = Column(String(30))
    to_status = Column(String(30), nullable=False)
    note = Column(String(300))
    changed_by = Column(BigInteger, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP, server_default=func.now())


class CouponRedemption(Base):
    __tablename__ = "coupon_redemptions"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    coupon_id = Column(BigInteger, ForeignKey("coupons.id"), nullable=False)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=False)
    customer_id = Column(BigInteger, ForeignKey("customers.id"))
    amount = Column(Numeric(12, 2), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
