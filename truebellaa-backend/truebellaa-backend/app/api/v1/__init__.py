"""Assemble every v1 router under a single APIRouter."""
from fastapi import APIRouter

from app.api.v1 import auth, catalog, cart, checkout, payments, orders, storefront, customer, media
from app.api.v1.admin import products as admin_products
from app.api.v1.admin import orders as admin_orders
from app.api.v1.admin import audit as admin_audit
from app.api.v1.admin import users as admin_users
from app.api.v1.admin import marketing as admin_marketing
from app.api.v1.admin import roles as admin_roles
from app.api.v1.admin import email_templates as admin_email_templates
from app.api.v1.admin import settings as admin_settings
from app.api.v1.admin import customers as admin_customers

api_router = APIRouter(prefix="/api/v1")

# storefront + customer
api_router.include_router(auth.router)
api_router.include_router(catalog.router)
api_router.include_router(cart.router)
api_router.include_router(checkout.router)
api_router.include_router(payments.router)
api_router.include_router(orders.router)
api_router.include_router(storefront.router)
api_router.include_router(customer.router)
api_router.include_router(media.router)

# back-office panels (Admin / Manager / Sales)
api_router.include_router(admin_products.router)
api_router.include_router(admin_orders.router)
api_router.include_router(admin_audit.router)
api_router.include_router(admin_users.router)
api_router.include_router(admin_marketing.router)
api_router.include_router(admin_roles.router)
api_router.include_router(admin_email_templates.router)
api_router.include_router(admin_settings.router)
api_router.include_router(admin_customers.router)
