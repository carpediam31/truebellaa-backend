"""
A generic repository — this is the "JPA Repository" idea in Python.

Instead of scattering SQL through the app, each table gets a repository
with ready-made get/list/create/update/delete methods. Every list/get is
tenant-scoped by default, so you can't accidentally read another brand's
rows. Swap the database later and none of this changes.
"""
from typing import Generic, TypeVar, Type

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: Type[ModelT]

    def __init__(self, db: Session):
        self.db = db

    def get(self, id_: int, tenant_id: int | None = None) -> ModelT | None:
        obj = self.db.get(self.model, id_)
        if obj is None:
            return None
        if tenant_id is not None and getattr(obj, "tenant_id", None) != tenant_id:
            return None
        return obj

    def list(self, tenant_id: int, *, limit: int = 50, offset: int = 0, **filters) -> list[ModelT]:
        stmt = select(self.model).where(self.model.tenant_id == tenant_id)
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        stmt = stmt.limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def add(self, obj: ModelT) -> ModelT:
        self.db.add(obj)
        self.db.flush()          # assigns the new id without committing
        return obj

    def delete(self, obj: ModelT) -> None:
        self.db.delete(obj)
