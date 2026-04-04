"""
T1.3.2: Tenant-aware database connection

Provides get_tenant_connection(tenant_id) which returns a SQLAlchemy
engine configured to use the specified tenant's schema via search_path.

Strategy: Schemas-per-tenant (see docs/design/tenancy.md)
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from typing import Dict

# Use DATABASE_URL from environment, fallback to development default
BASE_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:devpassword@localhost:5432/deepSightAI-Trinetra"
)

# Connection pool cache: tenant_id -> Engine
_engine_pool: Dict[str, "Engine"] = {}


def get_tenant_connection(tenant_id: str):
    """
    Get a SQLAlchemy engine configured for the given tenant's schema.

    The engine uses connection pooling and sets search_path to:
        - tenant_<tenant_id> (primary)
        - public (fallback for shared tables if needed)

    Args:
        tenant_id: Unique tenant identifier (string or UUID)

    Returns:
        SQLAlchemy Engine instance bound to that tenant's schema.

    Note:
        For security, tenant_id should be validated before passing here
        to prevent SQL injection via search_path manipulation.
    """
    if tenant_id in _engine_pool:
        return _engine_pool[tenant_id]

    # Sanitize tenant_id: allow only alphanumeric, dash, underscore
    # This prevents injection via search_path
    if not isinstance(tenant_id, str):
        tenant_id = str(tenant_id)
    # Simple sanitization - in production use stricter validation
    safe_tenant_id = "".join(c for c in tenant_id if c.isalnum() or c in "-_")

    # Build connection string with search_path option
    # The 'options' parameter sets command-line options for psql connection
    engine = create_engine(
        BASE_DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=False,  # Set to True for SQL debugging
        connect_args={
            "options": f"-c search_path=tenant_{safe_tenant_id},public"
        }
    )

    _engine_pool[tenant_id] = engine
    return engine


def get_tenant_session(tenant_id: str):
    """
    Convenience: Get a Session factory bound to tenant's schema.

    Usage:
        Session = get_tenant_session("tenant-abc")
        with Session() as session:
            session.query(...).all()
    """
    engine = get_tenant_connection(tenant_id)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def validate_tenant_isolation(tenant_id: str) -> bool:
    """
    Verify that a connection for tenant_id is properly isolated.
    Used in health checks and testing.

    Returns True if connection works and search_path is set correctly.
    """
    try:
        engine = get_tenant_connection(tenant_id)
        with engine.connect() as conn:
            result = conn.execute(text("SHOW search_path"))
            search_path = result.scalar()
            expected = f"tenant_{tenant_id}, public"
            # Allow some flexibility in formatting
            return f"tenant_{tenant_id}" in str(search_path)
    except Exception as e:
        print(f"Tenant isolation validation failed: {e}")
        return False


# For testing: clear engine pool between tests
def clear_engine_pool():
    """
    Clear the connection pool cache.
    Used in tests to ensure fresh connections.
    """
    global _engine_pool
    for engine in _engine_pool.values():
        engine.dispose()
    _engine_pool.clear()


# Alias for backwards compatibility if needed
_clear_engine_pool = clear_engine_pool


# Shared Base class for models (if not using AuthService's Base)
# Typically repositories import Base from their respective service modules
Base = declarative_base()
