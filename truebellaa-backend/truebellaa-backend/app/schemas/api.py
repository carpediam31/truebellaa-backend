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


# ---- admin: roles & permissions matrix ----
class RolePermissionsIn(BaseModel):
    permission_codes: list[str]
