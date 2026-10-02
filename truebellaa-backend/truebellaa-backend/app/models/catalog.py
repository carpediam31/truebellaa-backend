"""ORM models: categories, attributes, products, variants, inventory (+ i18n)."""
from sqlalchemy import (
    BigInteger, Boolean, Column, String, CHAR, Text, Enum, ForeignKey,
    TIMESTAMP, Numeric, Integer, Computed, func,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class Category(Base):
    __tablename__ = "categories"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    parent_id = Column(BigInteger, ForeignKey("categories.id"))
    slug = Column(String(140), nullable=False)
    position = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(TIMESTAMP)

    translations = relationship("CategoryTranslation", cascade="all, delete-orphan")


class CategoryTranslation(Base):
    __tablename__ = "category_translations"
    category_id = Column(BigInteger, ForeignKey("categories.id"), primary_key=True)
    locale_code = Column(String(10), ForeignKey("locales.code"), primary_key=True)
    name = Column(String(160), nullable=False)
    description = Column(String(500))


class Attribute(Base):
    __tablename__ = "attributes"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    code = Column(String(40), nullable=False)
    position = Column(Integer, default=0)


class AttributeValue(Base):
    __tablename__ = "attribute_values"
    id = Column(BigInteger, primary_key=True)
    attribute_id = Column(BigInteger, ForeignKey("attributes.id"), nullable=False)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    code = Column(String(40), nullable=False)
    hex_color = Column(CHAR(7))
    position = Column(Integer, default=0)

    translations = relationship("AttributeValueTranslation", cascade="all, delete-orphan")


class AttributeValueTranslation(Base):
    __tablename__ = "attribute_value_translations"
    attribute_value_id = Column(BigInteger, ForeignKey("attribute_values.id"), primary_key=True)
    locale_code = Column(String(10), ForeignKey("locales.code"), primary_key=True)
    label = Column(String(80), nullable=False)


class Product(Base):
    __tablename__ = "products"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    public_id = Column(CHAR(26), unique=True, nullable=False)
    category_id = Column(BigInteger, ForeignKey("categories.id"))
    slug = Column(String(160), nullable=False)
    sku_prefix = Column(String(40))
    base_price = Column(Numeric(12, 2), default=0)
    currency_code = Column(CHAR(3), ForeignKey("currencies.code"), default="INR")
    rating_avg = Column(Numeric(3, 2), default=0)
    rating_count = Column(Integer, default=0)
    status = Column(Enum("draft", "active", "archived"), default="draft")
    published_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(TIMESTAMP)

    translations = relationship("ProductTranslation", cascade="all, delete-orphan")
    images = relationship("ProductImage", cascade="all, delete-orphan")
    variants = relationship("ProductVariant", cascade="all, delete-orphan")
    category = relationship("Category")


class ProductTranslation(Base):
    __tablename__ = "product_translations"
    product_id = Column(BigInteger, ForeignKey("products.id"), primary_key=True)
    locale_code = Column(String(10), ForeignKey("locales.code"), primary_key=True)
    name = Column(String(200), nullable=False)
    short_description = Column(String(500))
    description = Column(Text)
    care_instructions = Column(Text)
    meta_title = Column(String(200))
    meta_description = Column(String(300))


class ProductImage(Base):
    __tablename__ = "product_images"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    product_id = Column(BigInteger, ForeignKey("products.id"), nullable=False)
    url = Column(String(500), nullable=False)
    alt_text = Column(String(200))
    position = Column(Integer, default=0)
    is_primary = Column(Boolean, default=False)
    # Media metadata for the uploads themselves — filled in by whichever
    # backend stored the file (see app/integrations/mileswebstorage_client.py).
    original_filename = Column(String(255))
    file_extension = Column(String(10))
    file_size_bytes = Column(Integer)
    storage_provider = Column(String(20), default="mileswebstorage")
    storage_path = Column(String(500))
    uploaded_by = Column(BigInteger, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP, server_default=func.now())


class ProductVariant(Base):
    __tablename__ = "product_variants"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    product_id = Column(BigInteger, ForeignKey("products.id"), nullable=False)
    sku = Column(String(64), unique=True, nullable=False)
    price = Column(Numeric(12, 2), nullable=False)
    compare_at_price = Column(Numeric(12, 2))
    cost_price = Column(Numeric(12, 2))
    stock_on_hand = Column(Integer, default=0)
    stock_reserved = Column(Integer, default=0)
    # generated column — read only, never written by the app
    stock_available = Column(Integer, Computed("stock_on_hand - stock_reserved"))
    weight_grams = Column(Integer)
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    attribute_values = relationship("AttributeValue", secondary="variant_attribute_values", viewonly=True)


class VariantAttributeValue(Base):
    __tablename__ = "variant_attribute_values"
    variant_id = Column(BigInteger, ForeignKey("product_variants.id"), primary_key=True)
    attribute_value_id = Column(BigInteger, ForeignKey("attribute_values.id"), primary_key=True)


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    variant_id = Column(BigInteger, ForeignKey("product_variants.id"), nullable=False)
    change_qty = Column(Integer, nullable=False)
    reason = Column(Enum("restock", "sale", "return", "adjustment", "reservation", "release"), nullable=False)
    reference = Column(String(80))
    created_by = Column(BigInteger)
    created_at = Column(TIMESTAMP, server_default=func.now())
