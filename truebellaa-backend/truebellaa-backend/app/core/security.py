"""
Security helpers: password hashing (bcrypt) + JWT tokens.

Passwords are never stored in plain text — only their bcrypt hash. Tokens
are short-lived signed strings that prove "this request comes from a
logged-in user of tenant X with role Y" without a database hit each time.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---- passwords ----
def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


# ---- JWT ----
def create_access_token(subject: str, extra: dict | None = None,
                        minutes: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(subject), "iat": now, "exp": exp, "type": "access"}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str, extra: dict | None = None,
                         days: int | None = None) -> str:
    """`days` lets the caller pass the runtime-configured lifetime
    (Admin -> Settings); falls back to the .env value."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=days or settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(subject), "iat": now, "exp": exp, "type": "refresh"}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


# ---- misc ----
def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)
