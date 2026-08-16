"""
Locale resolution + a helper to pick the right translation with fallback.

The requested language comes from the `X-Locale` header or `?lang=` query.
If the tenant hasn't enabled it, or a specific row isn't translated, we
fall back to the tenant's default locale — the storefront never shows blank.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenancy import TenantLocale, Tenant


def resolve_locale(db: Session, tenant: Tenant, requested: str | None) -> str:
    """Return a locale code that is actually enabled for this tenant."""
    default = tenant.default_locale_code or "en"
    if not requested:
        return default
    requested = requested.split(",")[0].split("-")[0].strip().lower()
    enabled = db.execute(
        select(TenantLocale.locale_code).where(
            TenantLocale.tenant_id == tenant.id,
            TenantLocale.is_active == True,  # noqa: E712
        )
    ).scalars().all()
    return requested if requested in enabled else default


def pick_translation(translations: list, locale: str, default_locale: str = "en"):
    """
    From a list of translation rows (each has .locale_code), return the one
    matching `locale`, else the default-locale one, else the first available.
    """
    by_code = {t.locale_code: t for t in translations}
    return by_code.get(locale) or by_code.get(default_locale) or (translations[0] if translations else None)
