"""
Transactional emails: welcome, order placed, payment confirmed, shipped.

Copy comes from the `email_templates` table so an Admin can edit it in the
admin panel without a redeploy. If the DB has no active row for a template
(or the lookup fails) we fall back to the built-in default below, so a bad
edit can never stop an order confirmation going out.
"""
import logging
import re

from sqlalchemy.orm import Session

from app.integrations.email_client import send_email
from app.models.customer import Customer
from app.models.email_template import EmailTemplate
from app.models.order import Order

logger = logging.getLogger("app.email")

_BRAND = "TrueBellaa"

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render(template: str, values: dict) -> str:
    """
    Replace {{name}} with values[name].

    An unknown placeholder is left verbatim rather than blanked, so a typo
    in the editor is visible in the preview instead of silently vanishing.
    """
    def sub(m):
        key = m.group(1)
        return str(values[key]) if key in values and values[key] is not None else m.group(0)
    return _PLACEHOLDER.sub(sub, template or "")


def get_template(db: Session | None, tenant_id: int | None, code: str):
    """Active DB template for this tenant, or None to use the built-in default."""
    if db is None or tenant_id is None:
        return None
    try:
        return (
            db.query(EmailTemplate)
            .filter(EmailTemplate.tenant_id == tenant_id,
                    EmailTemplate.code == code,
                    EmailTemplate.is_active.is_(True))
            .first()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Email template lookup failed for %r: %s", code, exc)
        return None


def _send_templated(db, tenant_id, code, to_email, values, fallback_subject, fallback_html):
    """Send via the DB template when there is one, else the built-in default."""
    tpl = get_template(db, tenant_id, code)
    if tpl:
        subject = render(tpl.subject, values)
        body = _wrap(subject, render(tpl.html_body, values))
    else:
        subject, body = fallback_subject, fallback_html
    return send_email(to_email, subject, body)


def _wrap(title: str, body_html: str) -> str:
    return f"""
    <div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;padding:32px;color:#111;">
      <h2 style="font-weight:500;letter-spacing:.02em;margin-bottom:4px;">{_BRAND}</h2>
      <hr style="border:none;border-top:1px solid #e5e5e5;margin:16px 0 28px;">
      <h3 style="font-weight:500;margin-bottom:16px;">{title}</h3>
      {body_html}
      <hr style="border:none;border-top:1px solid #e5e5e5;margin:32px 0 16px;">
      <p style="font-size:12px;color:#888;">
        This is an automated message from {_BRAND}. Please do not reply directly to this email.
      </p>
    </div>
    """


def order_values(order: Order) -> dict:
    """Placeholder values available to every order-related template."""
    return {
        "brand": _BRAND,
        "customer_name": order.ship_first_name or "there",
        "order_number": order.order_number,
        "order_public_id": order.public_id,
        "amount": f"{float(order.grand_total):,.2f}",
        "currency": order.currency_code,
    }


def send_welcome_email(customer: Customer, db: Session | None = None) -> None:
    name = customer.full_name or "there"
    values = {"brand": _BRAND, "customer_name": name, "customer_email": customer.email}
    fallback = _wrap("Welcome to TrueBellaa", f"""
      <p>Hi {name},</p>
      <p>Your account has been created. You can now track orders, save favourites
      and check out faster next time.</p>
    """)
    _send_templated(db, getattr(customer, "tenant_id", None), "welcome",
                    customer.email, values, "Welcome to TrueBellaa", fallback)


def send_order_placed_email(order: Order, db: Session | None = None) -> None:
    values = order_values(order)
    fallback = _wrap("We've received your order", f"""
      <p>Hi {order.ship_first_name},</p>
      <p>Thank you — we've received your order <strong>{order.order_number}</strong>
      for {order.currency_code} {float(order.grand_total):,.2f}. We'll email you again
      as soon as your payment is confirmed.</p>
      <p style="color:#888;font-size:13px;">Order ID: {order.public_id}</p>
    """)
    _send_templated(db, getattr(order, "tenant_id", None), "order_placed",
                    order.contact_email, values,
                    f"Order received — {order.order_number}", fallback)


def send_payment_confirmed_email(order: Order, db: Session | None = None) -> None:
    values = order_values(order)
    fallback = _wrap("Payment confirmed", f"""
      <p>Hi {order.ship_first_name},</p>
      <p>Your payment for order <strong>{order.order_number}</strong>
      ({order.currency_code} {float(order.grand_total):,.2f}) has been confirmed.
      We're preparing it for shipment.</p>
      <p style="color:#888;font-size:13px;">Order ID: {order.public_id}</p>
    """)
    _send_templated(db, getattr(order, "tenant_id", None), "payment_confirmed",
                    order.contact_email, values,
                    f"Payment confirmed — {order.order_number}", fallback)


def send_order_shipped_email(order: Order, shipment: dict, db: Session | None = None) -> None:
    """Sent when a shipment is created and we have a tracking number."""
    values = order_values(order)
    values.update({
        "courier_name": shipment.get("courier_name") or "our courier partner",
        "awb_code": shipment.get("awb_code") or "—",
        "tracking_url": shipment.get("tracking_url") or "",
    })
    fallback = _wrap("Your order has shipped", f"""
      <p>Hi {order.ship_first_name},</p>
      <p>Good news — order <strong>{order.order_number}</strong> is on its way.</p>
      <p>Courier: <strong>{values['courier_name']}</strong><br>
      Tracking number: <strong>{values['awb_code']}</strong></p>
    """)
    _send_templated(db, getattr(order, "tenant_id", None), "order_shipped",
                    order.contact_email, values,
                    f"Your order has shipped — {order.order_number}", fallback)
