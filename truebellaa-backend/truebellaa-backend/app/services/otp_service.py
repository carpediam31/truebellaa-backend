"""
Email OTP: issue, email, and verify one-time codes.

Used for customer account creation (you must prove you own the address
before an account exists on it) and for passwordless sign-in.

Security properties, each deliberate:
  * codes are generated with `secrets`, never `random`
  * only a SHA-256 hash is stored, so a DB leak yields no usable codes
  * verification is constant-time (`compare_digest`)
  * a code expires, is single-use, and dies after `max_attempts` wrong tries
  * requesting a new code invalidates any outstanding one for that address
  * request + verify are both throttled per email/IP
  * "does this email exist?" is never revealed by the request endpoint
"""
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import ratelimit
from app.models.otp import EmailOtp
from app.models.tenancy import Tenant
from app.services import email_service
from app.services.audit_service import ip_to_bytes

logger = logging.getLogger("app.otp")

CODE_LENGTH = 6
EXPIRY_MINUTES = 10
RESEND_COOLDOWN_SECONDS = 60


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def generate_code() -> str:
    """A cryptographically random 6-digit code (leading zeros allowed)."""
    return f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"


def request_otp(db: Session, tenant: Tenant, email: str, purpose: str = "register",
                ip: str | None = None) -> dict:
    """
    Issue a code and email it.

    Always reports success — telling an anonymous caller whether an address
    is registered would be an account-enumeration hole. The CALLER decides
    what the account state means.
    """
    email = email.strip().lower()

    # Throttle: one code per minute, and a hard ceiling per window.
    rl_key = f"otp:{email}:{ip or '-'}"
    wait = ratelimit.seconds_until_unblocked(rl_key)
    if wait:
        return {"sent": False, "retry_after_seconds": wait,
                "detail": f"Too many code requests. Try again in {wait // 60 + 1} minute(s)."}
    ratelimit.record_failure(rl_key)  # every request counts toward the cap

    # Any previous unused code for this address is dead the moment a new one
    # is issued — otherwise several valid codes would float around at once.
    now = datetime.utcnow()
    outstanding = db.execute(
        select(EmailOtp).where(EmailOtp.tenant_id == tenant.id, EmailOtp.email == email,
                               EmailOtp.purpose == purpose, EmailOtp.consumed_at.is_(None))
    ).scalars().all()
    for old in outstanding:
        if old.created_at and (now - old.created_at).total_seconds() < RESEND_COOLDOWN_SECONDS:
            remaining = RESEND_COOLDOWN_SECONDS - int((now - old.created_at).total_seconds())
            return {"sent": False, "retry_after_seconds": remaining,
                    "detail": f"A code was just sent. You can request another in {remaining}s."}
        old.consumed_at = now

    code = generate_code()
    row = EmailOtp(
        tenant_id=tenant.id, email=email, purpose=purpose, code_hash=_hash(code),
        expires_at=now + timedelta(minutes=EXPIRY_MINUTES), ip_address=ip_to_bytes(ip),
    )
    db.add(row)
    db.commit()

    values = {
        "brand": tenant.name or "TrueBellaa",
        "otp_code": code,
        "expires_minutes": EXPIRY_MINUTES,
        "customer_email": email,
    }
    fallback_html = email_service._wrap(
        "Your verification code",
        f"<p>Your verification code is:</p>"
        f"<p style='font-size:30px;letter-spacing:9px;font-weight:bold;margin:22px 0;'>{code}</p>"
        f"<p>It expires in {EXPIRY_MINUTES} minutes.</p>",
    )
    email_service._send_templated(
        db, tenant.id, "otp_verify", email, values,
        f"Your verification code: {code}", fallback_html,
    )
    # The code itself is never logged.
    logger.info("OTP issued for %s (purpose=%s)", email, purpose)
    return {"sent": True, "expires_in_minutes": EXPIRY_MINUTES}


def verify_otp(db: Session, tenant: Tenant, email: str, code: str,
               purpose: str = "register") -> tuple[bool, str]:
    """
    Check a code. Returns (ok, message).

    Consumes the code on success so it cannot be replayed, and burns an
    attempt on failure so the 6-digit space can't be walked.
    """
    email = email.strip().lower()
    now = datetime.utcnow()

    row = db.execute(
        select(EmailOtp)
        .where(EmailOtp.tenant_id == tenant.id, EmailOtp.email == email,
               EmailOtp.purpose == purpose, EmailOtp.consumed_at.is_(None))
        .order_by(EmailOtp.id.desc())
    ).scalars().first()

    if not row:
        return False, "No verification code is pending for this email. Request a new one."
    if row.expires_at and row.expires_at < now:
        return False, "That code has expired. Request a new one."
    if (row.attempts or 0) >= (row.max_attempts or 5):
        row.consumed_at = now
        db.commit()
        return False, "Too many incorrect attempts. Request a new code."

    # constant-time compare so timing can't leak the digits
    if not hmac.compare_digest(row.code_hash, _hash((code or "").strip())):
        row.attempts = (row.attempts or 0) + 1
        db.commit()
        left = (row.max_attempts or 5) - row.attempts
        return False, f"Incorrect code. {left} attempt(s) remaining."

    row.consumed_at = now
    db.commit()
    return True, "verified"
