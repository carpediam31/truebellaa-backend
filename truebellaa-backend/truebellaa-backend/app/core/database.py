"""
Database engines + sessions — the heart of the "JPA for Python" setup.

We create TWO SQLAlchemy engines:
  * write_engine  -> the PRIMARY database (all INSERT/UPDATE/DELETE)
  * read_engine   -> a READ REPLICA (heavy SELECTs: browsing, listings)

Because SQLAlchemy hides raw SQL behind Python models, switching the
database later (e.g. MySQL -> PostgreSQL) is a URL change, not a rewrite.
That is exactly the database-independence you wanted from Java's JPA.

FastAPI endpoints ask for a session with a dependency:
  * get_write_db -> use for anything that writes, or must read-its-own-write
  * get_read_db  -> use for pure reads that can tolerate tiny replica lag
"""
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from app.core.config import settings

# pool_pre_ping avoids "server has gone away" errors on idle connections.
write_engine = create_engine(
    settings.primary_url, pool_pre_ping=True, pool_recycle=1800, future=True
)
read_engine = create_engine(
    settings.replica_url, pool_pre_ping=True, pool_recycle=1800, future=True
)

WriteSession = sessionmaker(bind=write_engine, autoflush=False, expire_on_commit=False, future=True)
ReadSession = sessionmaker(bind=read_engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    """Base class every ORM model inherits from."""
    pass


def get_write_db() -> Generator[Session, None, None]:
    """A session bound to the PRIMARY. Commits on success, rolls back on error."""
    db = WriteSession()
    try:
        yield db
    finally:
        db.close()


def get_read_db() -> Generator[Session, None, None]:
    """A read-only session bound to the REPLICA."""
    db = ReadSession()
    try:
        yield db
    finally:
        db.close()


def set_audit_actor(db: Session, user_id: int | None) -> None:
    """
    Tell the database WHO is making this change, so the price-history
    trigger (see 07_audit_and_history.sql) can attribute it. The app calls
    this right after opening a write session for a logged-in staff member.
    """
    db.execute(text("SET @app_user_id = :uid"), {"uid": user_id or 0})
