"""
T1.3.2: Tenant-aware database connection

Tests get_tenant_connection(tenant_id) returns SQLAlchemy engine
configured with correct search_path for tenant's schema.
"""

import pytest
import os
from sqlalchemy import create_engine, text


@pytest.fixture(scope="function")
def tenant_db_url():
    """
    Setup PostgreSQL test database with tenant schemas.
    Requires DATABASE_URL env var (set in Docker test environment).
    """
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:test@postgres-test:5432/clipsight_test"
    )
    engine = create_engine(database_url)

    # Create test tenant schemas
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS tenant_alpha CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS tenant_beta CASCADE"))
        conn.execute(text("CREATE SCHEMA tenant_alpha"))
        conn.execute(text("CREATE SCHEMA tenant_beta"))
        # Create a simple table in each schema
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant_alpha.test_table (
                id SERIAL PRIMARY KEY,
                data TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant_beta.test_table (
                id SERIAL PRIMARY KEY,
                data TEXT
            )
        """))

    yield database_url

    # Teardown: drop schemas
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS tenant_alpha CASCADE"))
            conn.execute(text("DROP SCHEMA IF EXISTS tenant_beta CASCADE"))
    except Exception as e:
        print(f"Teardown error: {e}")
    finally:
        engine.dispose()


@pytest.mark.integration
class TestTenantAwareDBConnection:
    """T1.3.2: Verify get_tenant_connection implementation."""

    def test_get_tenant_connection_function_exists(self, tenant_db_url):
        """shared.db should have get_tenant_connection(tenant_id)."""
        from shared.db import get_tenant_connection
        assert callable(get_tenant_connection), \
            "shared.db must implement get_tenant_connection(tenant_id)"

    def test_get_tenant_connection_returns_engine(self, tenant_db_url):
        """get_tenant_connection should return SQLAlchemy Engine."""
        from shared.db import get_tenant_connection
        from sqlalchemy import Engine

        # Set DATABASE_URL for shared.db
        os.environ["DATABASE_URL"] = tenant_db_url

        engine = get_tenant_connection("tenant-alpha")
        assert isinstance(engine, Engine), \
            "get_tenant_connection must return SQLAlchemy Engine"

    def test_tenant_schema_isolation(self, tenant_db_url):
        """Different tenants should get connections with different search_paths."""
        from shared.db import get_tenant_connection, clear_engine_pool
        from sqlalchemy import text

        os.environ["DATABASE_URL"] = tenant_db_url
        clear_engine_pool()

        engine_alpha = get_tenant_connection("tenant-alpha")
        engine_beta = get_tenant_connection("tenant-beta")

        # Verify search_path for alpha
        with engine_alpha.connect() as conn:
            result = conn.execute(text("SHOW search_path"))
            path_alpha = result.scalar()
            assert "tenant_alpha" in str(path_alpha), \
                f"search_path should include tenant_alpha, got {path_alpha}"

        # Verify search_path for beta
        with engine_beta.connect() as conn:
            result = conn.execute(text("SHOW search_path"))
            path_beta = result.scalar()
            assert "tenant_beta" in str(path_beta), \
                f"search_path should include tenant_beta, got {path_beta}"

        clear_engine_pool()

    def test_data_isolation_between_tenants(self, tenant_db_url):
        """Data in one tenant's schema should not be visible in another's."""
        from shared.db import get_tenant_connection, clear_engine_pool
        from sqlalchemy import text

        os.environ["DATABASE_URL"] = tenant_db_url
        clear_engine_pool()

        # Insert data into tenant_alpha
        engine_alpha = get_tenant_connection("tenant-alpha")
        with engine_alpha.begin() as conn:
            conn.execute(
                text("INSERT INTO test_table (data) VALUES ('alpha_data')")
            )

        # Query from tenant_beta - should see 0 rows
        engine_beta = get_tenant_connection("tenant-beta")
        with engine_beta.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM test_table"))
            count = result.scalar()
            assert count == 0, f"Tenant beta should have 0 rows, found {count}"

        # Verify tenant_alpha has its data
        with engine_alpha.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM test_table"))
            count = result.scalar()
            assert count == 1, f"Tenant alpha should have 1 row, found {count}"

        clear_engine_pool()
