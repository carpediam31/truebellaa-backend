"""
Runtime settings — change behaviour without editing .env or redeploying.

Values live in the existing `tenant_settings` key/value table and are
cached in-process for a few seconds so reading one on every request is
cheap. An Admin edits them in the admin panel and the change takes effect
within seconds, with no restart.

Each setting declares its type, bounds and a default. The default is the
value from .env/config.py, so a tenant that has never touched a setting
behaves exactly as before.
"""
import json
import logging
import time
from dataclasses import dataclass
from threading import Lock

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings as env_settings

logger = logging.getLogger("app.settings")

CACHE_TTL_SECONDS = 10
_cache: dict[int, tuple[float, dict]] = {}
_lock = Lock()


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    group: str
    kind: str                 # "int" | "bool" | "str"
    default: object
    help: str = ""
    minimum: int | None = None
    maximum: int | None = None


# Everything an Admin may safely tune at runtime. Deliberately excludes
# secrets (passwords, API keys) — those stay in .env, which is not
# readable or writable through the API.
SPECS: list[Spec] = [
    Spec("access_token_minutes", "Access token lifetime (minutes)", "Sessions", "int",
         env_settings.ACCESS_TOKEN_EXPIRE_MINUTES,
         "How long a login lasts before the browser silently renews it. "
         "Short is safer; the refresh token below is what keeps users signed in.",
         minimum=5, maximum=1440),
    Spec("refresh_token_days", "Stay signed in for (days)", "Sessions", "int",
         env_settings.REFRESH_TOKEN_EXPIRE_DAYS,
         "How long before a user must type their password again.",
         minimum=1, maximum=365),
    Spec("login_max_attempts", "Failed logins before lockout", "Security", "int",
         8, "Wrong-password attempts allowed before the account is briefly locked.",
         minimum=3, maximum=50),
    Spec("login_lockout_minutes", "Lockout duration (minutes)", "Security", "int",
         15, "How long a locked-out sign-in has to wait.", minimum=1, maximum=240),
    Spec("otp_expiry_minutes", "OTP valid for (minutes)", "Security", "int",
         10, "How long an emailed verification code stays usable.", minimum=1, maximum=60),
    Spec("otp_max_attempts", "OTP guesses allowed", "Security", "int",
         5, "Wrong code entries before the code is burned.", minimum=3, maximum=10),
    Spec("max_image_mb", "Max product image size (MB)", "Catalog", "int",
         env_settings.MAX_IMAGE_SIZE_MB, "Uploads larger than this are rejected.",
         minimum=1, maximum=50),
    Spec("low_stock_threshold", "Low-stock warning at", "Catalog", "int",
         2, "Stock at or below this shows as low in the admin panel.", minimum=0, maximum=100),
    Spec("reservation_minutes", "Hold stock for (minutes)", "Orders", "int",
         60, "How long an unpaid checkout keeps stock reserved before it is released.",
         minimum=5, maximum=1440),
    Spec("require_login_checkout", "Require login to place an order", "Orders", "bool",
         True,
         "On: shoppers must have a verified account before checking out, so every "
         "order belongs to a real email. Off: guest checkout is allowed, which "
         "converts better but lets anyone order using someone else's address."),
    Spec("send_order_emails", "Send order emails", "Email", "bool",
         True, "Turn off to stop all transactional email (useful while testing)."),
]

BY_KEY = {s.key: s for s in SPECS}


def _coerce(spec: Spec, raw):
    try:
        if spec.kind == "int":
            v = int(raw)
            if spec.minimum is not None:
                v = max(spec.minimum, v)
            if spec.maximum is not None:
                v = min(spec.maximum, v)
            return v
        if spec.kind == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "yes", "on")
        return str(raw)
    except (TypeError, ValueError):
        return spec.default


def load_all(db: Session, tenant_id: int, *, fresh: bool = False) -> dict:
    """Every setting for a tenant: stored value where present, else default."""
    now = time.time()
    if not fresh:
        with _lock:
            hit = _cache.get(tenant_id)
            if hit and now - hit[0] < CACHE_TTL_SECONDS:
                return dict(hit[1])

    values = {s.key: s.default for s in SPECS}
    try:
        rows = db.execute(
            text("SELECT setting_key, setting_val FROM tenant_settings WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).all()
        for key, raw in rows:
            if key in BY_KEY:
                parsed = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                values[key] = _coerce(BY_KEY[key], parsed)
    except Exception as exc:  # noqa: BLE001
        # Never let a settings problem take the app down — fall back to defaults.
        logger.warning("Could not read tenant_settings (using defaults): %s", exc)

    with _lock:
        _cache[tenant_id] = (now, dict(values))
    return values


def get(db: Session, tenant_id: int, key: str):
    return load_all(db, tenant_id).get(key, BY_KEY[key].default if key in BY_KEY else None)


def set_many(db: Session, tenant_id: int, updates: dict) -> dict:
    """Validate + persist. Unknown keys are ignored rather than stored."""
    applied = {}
    for key, raw in (updates or {}).items():
        spec = BY_KEY.get(key)
        if not spec:
            continue
        value = _coerce(spec, raw)
        db.execute(
            text("""INSERT INTO tenant_settings (tenant_id, setting_key, setting_val)
                    VALUES (:t, :k, CAST(:v AS JSON))
                    ON DUPLICATE KEY UPDATE setting_val = CAST(:v AS JSON)"""),
            {"t": tenant_id, "k": key, "v": json.dumps(value)},
        )
        applied[key] = value
    db.commit()
    invalidate(tenant_id)
    return applied


def invalidate(tenant_id: int) -> None:
    with _lock:
        _cache.pop(tenant_id, None)


def describe(db: Session, tenant_id: int) -> list[dict]:
    """Specs + current values, for rendering the settings screen."""
    current = load_all(db, tenant_id, fresh=True)
    return [{
        "key": s.key, "label": s.label, "group": s.group, "kind": s.kind,
        "help": s.help, "default": s.default, "value": current.get(s.key, s.default),
        "min": s.minimum, "max": s.maximum,
    } for s in SPECS]
