"""ORM models: Shiprocket shipments, tracking, webhook events."""
from sqlalchemy import (
    BigInteger, Column, String, Enum, ForeignKey, TIMESTAMP, Numeric,
    Integer, JSON, func,
)
from app.core.database import Base


class Shipment(Base):
    __tablename__ = "shipments"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=False)
    provider = Column(String(30), default="shiprocket")
    shiprocket_order_id = Column(String(64))
    shiprocket_shipment_id = Column(String(64))
    awb_code = Column(String(64))
    courier_name = Column(String(80))
    courier_id = Column(String(40))
    status = Column(Enum("pending", "ready_to_ship", "pickup_scheduled", "shipped",
                         "in_transit", "out_for_delivery", "delivered", "rto",
                         "cancelled", "failed"), default="pending")
    tracking_url = Column(String(500))
    label_url = Column(String(500))
    manifest_url = Column(String(500))
    weight_grams = Column(Integer)
    length_cm = Column(Numeric(6, 2))
    breadth_cm = Column(Numeric(6, 2))
    height_cm = Column(Numeric(6, 2))
    shipping_charge = Column(Numeric(12, 2))
    pickup_scheduled_at = Column(TIMESTAMP)
    expected_delivery_at = Column(TIMESTAMP)
    shipped_at = Column(TIMESTAMP)
    delivered_at = Column(TIMESTAMP)
    raw_response = Column(JSON)
    created_by = Column(BigInteger, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class ShipmentTrackingEvent(Base):
    __tablename__ = "shipment_tracking_events"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    shipment_id = Column(BigInteger, ForeignKey("shipments.id"), nullable=False)
    status = Column(String(60), nullable=False)
    status_detail = Column(String(255))
    location = Column(String(120))
    occurred_at = Column(TIMESTAMP)
    raw_payload = Column(JSON)
    created_at = Column(TIMESTAMP, server_default=func.now())


class ShippingWebhookEvent(Base):
    __tablename__ = "shipping_webhook_events"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"))
    provider = Column(String(30), default="shiprocket")
    event_id = Column(String(120), nullable=False)
    event_type = Column(String(80))
    payload = Column(JSON, nullable=False)
    processing_status = Column(Enum("received", "processed", "ignored", "error"), default="received")
    error_message = Column(String(255))
    received_at = Column(TIMESTAMP, server_default=func.now())
    processed_at = Column(TIMESTAMP)
