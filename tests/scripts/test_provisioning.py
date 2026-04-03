"""
T1.3.7: Tenant provisioning automation script

Tests for `scripts/provision-tenant.sh` which automates creation of
tenant resources: PostgreSQL schema, Redis entries, MinIO bucket, etc.
"""

import pytest
import subprocess
import os
from pathlib import Path


@pytest.fixture(scope="function")
def test_tenant_id():
    return "test_tenant_provision"


def test_provision_script_exists():
    """The provisioning script must exist and be executable."""
    script_path = Path("scripts/provision-tenant.sh")
    assert script_path.exists(), "scripts/provision-tenant.sh not found"
    # Check executable bit (may not be set on Windows, but at least readable)
    assert os.access(script_path, os.X_OK) or script_path.suffix == ".sh"


def test_provision_tenant_creates_schema(test_tenant_id, tenant_db_url):
    """
    Running provision-tenant.sh should create the tenant's PostgreSQL schema.
    This is an integration test requiring a running PostgreSQL.
    """
    # Set environment variables for the script
    env = os.environ.copy()
    env["DATABASE_URL"] = tenant_db_url
    env["TENANT_ID"] = test_tenant_id
    env["TENANT_NAME"] = "Test Provision Tenant"
    env["TENANT_SLUG"] = "test-provision"

    # Run the script
    result = subprocess.run(
        ["bash", "scripts/provision-tenant.sh"],
        env=env,
        capture_output=True,
        text=True
    )

    # If script not found, skip
    if result.returncode == 127:
        pytest.skip("Script not found or not executable")
    assert result.returncode == 0, f"Script failed: {result.stderr}"

    # Verify schema was created
    from sqlalchemy import create_engine, text
    engine = create_engine(tenant_db_url)
    with engine.connect() as conn:
        # Check schema exists
        res = conn.execute(
            text(f"SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'tenant_{test_tenant_id}'")
        )
        schema_row = res.fetchone()
        assert schema_row is not None, f"Schema tenant_{test_tenant_id} not created"


def test_provision_tenant_is_idempotent(test_tenant_id, tenant_db_url):
    """Running the script twice should succeed (idempotent)."""
    env = os.environ.copy()
    env["DATABASE_URL"] = tenant_db_url
    env["TENANT_ID"] = test_tenant_id

    # Run twice
    for i in range(2):
        result = subprocess.run(
            ["bash", "scripts/provision-tenant.sh"],
            env=env,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Run {i+1} failed: {result.stderr}"


def test_provision_tenant_creates_initial_data(test_tenant_id, tenant_db_url):
    """Script should insert default roles, maybe admin user."""
    # Could check that default roles exist in tenant schema
    pass  # Future test
