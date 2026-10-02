"""Pydantic request/response models (what the API accepts and returns)."""
from pydantic import BaseModel, EmailStr, Field


# ---- auth ----
class StaffLoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    refresh_token: str | None = None


class CustomerRegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str | None = None


class CustomerLoginIn(BaseModel):
    email: EmailStr
    password: str


# ---- cart ----
class CartAddIn(BaseModel):
    sku: str
    qty: int = Field(default=1, ge=1)
    cart_token: str | None = None


# ---- checkout ----  (field names mirror the frontend checkout form)
class CartLine(BaseModel):
    sku: str
    qty: int = Field(ge=1)


class CheckoutIn(BaseModel):
    items: list[CartLine]
    email: EmailStr
    phone: str
    fname: str
    lname: str
    addr: str
    addr2: str | None = None
    city: str
    pin: str
    state: str


# ---- payment ----
class PaymentVerifyIn(BaseModel):
    order_public_id: str
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ---- admin: catalog ----
class PriceUpdateIn(BaseModel):
    price: float = Field(gt=0)


class StockUpdateIn(BaseModel):
    stock_on_hand: int = Field(ge=0)
    reason: str = Field(default="adjustment")


class ProductTranslationIn(BaseModel):
    locale_code: str = Field(default="en")
    name: str = Field(min_length=1, max_length=200)
    short_description: str | None = None
    description: str | None = None
    care_instructions: str | None = None


class ProductVariantIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    price: float = Field(gt=0)
    compare_at_price: float | None = None
    stock_on_hand: int = Field(default=0, ge=0)
    is_default: bool = False


class ProductUpdateIn(BaseModel):
    """Every field optional — only what's sent gets changed (PATCH semantics)."""
    slug: str | None = Field(default=None, min_length=1, max_length=160)
    sku_prefix: str | None = None
    category_id: int | None = None
    base_price: float | None = Field(default=None, ge=0)
    currency_code: str | None = None
    status: str | None = Field(default=None, description="draft | active | archived")
    translations: list[ProductTranslationIn] | None = None


class ProductCreateIn(BaseModel):
    slug: str = Field(min_length=1, max_length=160)
    sku_prefix: str | None = None
    category_id: int | None = None
    base_price: float = Field(ge=0)
    currency_code: str = Field(default="INR")
    status: str = Field(default="draft", description="draft | active | archived")
    translations: list[ProductTranslationIn] = Field(min_length=1)
    variants: list[ProductVariantIn] = Field(default_factory=list)


class NewsletterIn(BaseModel):
    email: EmailStr


# ---- admin: staff / users (Admin panel "Registration") ----
class StaffCreateIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str
    role_code: str = Field(description="admin | manager | sales")
    phone: str | None = None


class StaffStatusIn(BaseModel):
    status: str = Field(description="active | disabled")


class StaffRoleUpdateIn(BaseModel):
    role_code: str


# ---- admin: marketing / sales panel ----
class CouponCreateIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    discount_type: str = Field(description="percent | fixed")
    discount_value: float = Field(gt=0)
    min_order_total: float | None = None
    max_discount: float | None = None
    usage_limit: int | None = None
    per_customer_limit: int | None = None


class CouponStatusIn(BaseModel):
    is_active: bool


class ReviewModerateIn(BaseModel):
    status: str = Field(description="approved | rejected")


class OrderStatusIn(BaseModel):
    status: str = Field(description="paid | processing | shipped | delivered | cancelled | refunded | returned")
    note: str | None = Field(default=None, max_length=300)


class OrderNoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)


class CustomerStatusIn(BaseModel):
    status: str = Field(description="active | blocked")


# ---- admin: runtime settings ----
class SettingsUpdateIn(BaseModel):
    values: dict[str, object]


# ---- customer OTP ----
class OtpRequestIn(BaseModel):
    email: EmailStr
    purpose: str = Field(default="register", description="register | login")


class OtpRegisterIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)
    password: str = Field(min_length=6)
    full_name: str | None = None


class OtpLoginIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)


# ---- admin: email templates ----
class EmailTemplateUpdateIn(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    html_body: str = Field(min_length=1)
    is_active: bool | None = None


class EmailTestSendIn(BaseModel):
    to_email: EmailStr
    # Optional overrides so the editor can test UNSAVED edits.
    subject: str | None = None
    html_body: str | None = None


# ---- admin: roles & permissions matrix ----
class RolePermissionsIn(BaseModel):
    permission_codes: list[str]
