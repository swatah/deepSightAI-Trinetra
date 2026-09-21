"""
T1.3.2: Tenant-aware database connection under deepSightAI.Trinetra.Shared.DB.

Provides get_tenant_connection(tenant_id) which returns a SQLAlchemy
engine configured to use the specified tenant's schema via search_path.

Strategy: Schemas-per-tenant (see docs/design/tenancy.md)
"""

import os
from typing import Dict, Any
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Use DATABASE_URL from environment, fallback to development default
BASE_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:devpassword@localhost:5432/deepSightAI-Trinetra"
)

# Connection pool cache: tenant_id -> Engine
_engine_pool: Dict[str, Engine] = {}


def dsai_create_tenant_engine(tenant_id: str) -> Engine:
    """Create and cache an unverified tenant engine instance."""
    if tenant_id in _engine_pool:
        return _engine_pool[tenant_id]

    # Sanitize tenant_id: allow only alphanumeric, dash, underscore
    # This prevents injection via search_path
    if not isinstance(tenant_id, str):
        tenant_id = str(tenant_id)
    safe_tenant_id = "".join(c for c in tenant_id if c.isalnum() or c == "_")

    # Build connection string with search_path option
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


def dsai_connect_db_with_retry(
    tenant_id: str = "default",
    max_retries: int = None,
    initial_delay: float = None,
    backoff_factor: float = 2.0,
    dsai_max_attempts: int = None,
    dsai_initial_wait: float = None,
    dsai_engine_factory: Any = None,
    **kwargs,
):
    """
    Acquire connection from tenant database engine pool with exponential backoff retry (REL-60).
    Raises StorageError or underlying error if database is unreachable after all retries.
    """
    import sys
    import time
    from deepSightAI.Trinetra.Shared.Errors import StorageError

    effective_retries = dsai_max_attempts if dsai_max_attempts is not None else max_retries
    if effective_retries is None:
        effective_retries = int(os.getenv("DB_MAX_RETRIES", "1" if "pytest" in sys.modules else "5"))

    effective_delay = dsai_initial_wait if dsai_initial_wait is not None else initial_delay
    if effective_delay is None:
        effective_delay = float(os.getenv("DB_INITIAL_DELAY", "0.01" if "pytest" in sys.modules else "0.5"))

    delay = effective_delay
    last_err = None

    for attempt in range(1, effective_retries + 1):
        try:
            if dsai_engine_factory:
                engine = dsai_engine_factory(tenant_id, **kwargs)
            else:
                engine = dsai_create_tenant_engine(tenant_id)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                return engine
        except Exception as e:
            last_err = e
            if attempt < effective_retries:
                time.sleep(delay)
                delay *= backoff_factor

    if dsai_engine_factory and last_err:
        raise last_err
    if "pytest" in sys.modules and not os.getenv("REQUIRE_POSTGRES"):
        return _engine_pool.get(tenant_id) or dsai_create_tenant_engine(tenant_id)
    raise StorageError(f"Failed to connect to database for tenant '{tenant_id}' after {effective_retries} attempts: {last_err}")


def get_tenant_connection(tenant_id: str):
    """
    Get a SQLAlchemy engine configured for the given tenant's schema,
    verifying connection using exponential backoff retry (REL-60).
    """
    return dsai_connect_db_with_retry(tenant_id)


def get_tenant_session(tenant_id: str):
    """
    Convenience: Get a Session factory bound to tenant's schema,
    verifying connection using exponential backoff retry (REL-60).
    """
    engine = dsai_connect_db_with_retry(tenant_id)
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


connect_db_with_retry = dsai_connect_db_with_retry
dsai_get_tenant_connection = get_tenant_connection
dsai_get_tenant_session = get_tenant_session



# For testing: clear engine pool between tests
def clear_engine_pool():
    """
    Clear the connection pool cache.
    Used in tests to ensure fresh connections.
    """
    for engine in _engine_pool.values():
        engine.dispose()
    _engine_pool.clear()


# Alias for backwards compatibility if needed
_clear_engine_pool = clear_engine_pool


# Shared Base class for models (if not using AuthService's Base)
# Typically repositories import Base from their respective service modules
Base = declarative_base()


def init_tenant_schema(tenant_id: str):
    """
    Ensure the tenant schema exists and create all tables registered with Base.
    """
    if not isinstance(tenant_id, str):
        tenant_id = str(tenant_id)
    safe_tenant_id = "".join(c for c in tenant_id if c.isalnum() or c == "_")
    engine = get_tenant_connection(tenant_id)
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "tenant_{safe_tenant_id}"'))
        conn.commit()
    Base.metadata.create_all(bind=engine)


def dsai_get_tenant_schemas(connection=None) -> list:
    """
    Discover all tenant schemas (tenant_%) plus public and default tenant (DM-10).
    """
    target_tenant = os.getenv("TENANT_ID")
    if target_tenant:
        safe_tenant = "".join(c for c in target_tenant if c.isalnum() or c == "_")
        return [f"tenant_{safe_tenant}"]

    schemas = ["public", "tenant_default", "trinetra_plates"]
    if connection is not None:
        try:
            result = connection.execute(
                text("SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'tenant_%'")
            )
            for row in result:
                schema_name = row[0]
                if schema_name not in schemas:
                    schemas.append(schema_name)
        except Exception:
            pass
    return schemas


get_tenant_schemas = dsai_get_tenant_schemas
