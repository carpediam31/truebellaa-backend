"""Import all models so SQLAlchemy's mapper registry knows about them."""
from app.models.tenancy import (  # noqa: F401
    Locale, Currency, Permission, Tenant, TenantLocale, TenantSetting,
)
from app.models.rbac import (  # noqa: F401
    User, Role, RolePermission, UserRole, StaffSession,
)
from app.models.catalog import (  # noqa: F401
    Category, CategoryTranslation, Attribute, AttributeValue,
    AttributeValueTranslation, Product, ProductTranslation, ProductImage,
    ProductVariant, VariantAttributeValue, InventoryMovement,
)
from app.models.customer import (  # noqa: F401
    Customer, CustomerAddress, WishlistItem, NewsletterSubscriber, ProductReview,
)
from app.models.order import (  # noqa: F401
    Cart, CartItem, Coupon, Order, OrderItem, OrderStatusHistory, CouponRedemption,
)
from app.models.payment import (  # noqa: F401
    Payment, PaymentRefund, PaymentWebhookEvent,
)
from app.models.shipping import (  # noqa: F401
    Shipment, ShipmentTrackingEvent, ShippingWebhookEvent,
)
from app.models.audit import (  # noqa: F401
    AuditLog, AuthEvent, ProductPriceHistory,
)
