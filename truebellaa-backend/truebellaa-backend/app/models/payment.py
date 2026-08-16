"""ORM models: Razorpay payments, refunds, webhook events."""
from sqlalchemy import (
    BigInteger, Boolean, Column, String, CHAR, Enum, ForeignKey, TIMESTAMP,
    Numeric, JSON, func,
)
from app.core.database import Base


class Payment(Base):
    __tablename__ = "payments"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=False)
    provider = Column(String(30), default="razorpay")
    razorpay_order_id = Column(String(64))
    razorpay_payment_id = Column(String(64), unique=True)
    razorpay_signature = Column(String(255))
    amount = Column(Numeric(12, 2), nullable=False)
    currency_code = Column(CHAR(3), default="INR")
    status = Column(Enum("created", "authorized", "captured", "failed",
                         "refunded", "partially_refunded"), default="created")
    method = Column(String(30))
    signature_verified = Column(Boolean, default=False)
    error_code = Column(String(80))
    error_description = Column(String(255))
    raw_response = Column(JSON)
    authorized_at = Column(TIMESTAMP)
    captured_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class PaymentRefund(Base):
    __tablename__ = "payment_refunds"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    payment_id = Column(BigInteger, ForeignKey("payments.id"), nullable=False)
    razorpay_refund_id = Column(String(64), unique=True)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(Enum("pending", "processed", "failed"), default="pending")
    reason = Column(String(255))
    initiated_by = Column(BigInteger, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP, server_default=func.now())
    processed_at = Column(TIMESTAMP)


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"))
    provider = Column(String(30), default="razorpay")
    event_id = Column(String(120), nullable=False)
    event_type = Column(String(80))
    signature_verified = Column(Boolean, default=False)
    payload = Column(JSON, nullable=False)
    processing_status = Column(Enum("received", "processed", "ignored", "error"), default="received")
    error_message = Column(String(255))
    received_at = Column(TIMESTAMP, server_default=func.now())
    processed_at = Column(TIMESTAMP)
