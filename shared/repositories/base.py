"""
T1.3.3: Base repository class ensuring tenant-aware database access.

All concrete repositories must inherit from BaseRepository and use
the tenant-scoped session provided by get_tenant_session().
"""

from shared.db import get_tenant_session
from sqlalchemy.orm import Session
from typing import TypeVar, Generic, Type
from datetime import datetime

T = TypeVar('T')  # Model type


class BaseRepository(Generic[T]):
    """
    Generic repository base class that enforces tenant isolation.

    Each repository instance is bound to a specific tenant_id.
    All queries operate within that tenant's schema.
    """

    def __init__(self, tenant_id: str):
        """
        Initialize repository for a tenant.

        Args:
            tenant_id: The tenant identifier. Determines which schema to use.
        """
        self.tenant_id = tenant_id
        self.Session = get_tenant_session(tenant_id)

    def _add(self, obj: T) -> T:
        with self.Session() as session:
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return obj

    def _get(self, model: Type[T], **kwargs) -> T | None:
        with self.Session() as session:
            return session.query(model).filter_by(**kwargs).first()

    def _list(self, model: Type[T], **filters) -> List[T]:
        with self.Session() as session:
            query = session.query(model)
            if filters:
                query = query.filter_by(**filters)
            return query.all()

    def _delete(self, obj: T) -> None:
        with self.Session() as session:
            session.delete(obj)
            session.commit()

    # Could add more generic methods: update, count, etc.
