"""
Outbound transactional email (SMTP).

Two modes:
  * LIVE  — when real SMTP credentials are set in .env, we actually send via
            the support@ mailbox.
  * DEMO  — when the password is a placeholder, we just log the email to the
            console (mirrors the Razorpay/Shiprocket demo pattern) so nothing
            breaks before the mailbox password is added.

Email sending NEVER raises — a slow/broken mail server must not break
checkout, payment verification, or registration. We log and move on.
"""
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("app.email")


def send_email(to_email: str, subject: str, html_body: str, text_body: str | None = None) -> bool:
    """Send one email. Returns True if it was sent (or logged, in demo mode)."""
    if not to_email:
        return False

    if not settings.smtp_live:
        logger.info("[DEMO EMAIL] to=%s subject=%r", to_email, subject)
        return True

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_USER}>"
    msg["To"] = to_email
    msg.set_content(text_body or "Please view this email in an HTML-capable client.")
    msg.add_alternative(html_body, subtype="html")

    try:
        if settings.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
        logger.info("Email sent to %s (subject=%r)", to_email, subject)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Email send to %s FAILED: %s", to_email, exc)
        return False
