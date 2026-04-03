"""
T2.1.9: Plugin configuration API (tenant admin)

Tests PUT /tenants/{id}/plugins to enable/disable plugins.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "AuthService"))

from auth_service import app, get_db, require_auth, Base, Tenant
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from jose import jwt
import os

# Use file-based SQLite for test to share across connections
# SQLite_DB = "sqlite:////tmp/test_plugin_config.db"


class FakeAuth:
    """Mock auth dependency with admin role."""
    @staticmethod
    def get_payload(tenant_id=1):
        return {
            "sub": "999",
            "email": "admin@example.com",
            "tenant_id": tenant_id,
            "roles": ["admin"]
        }


@pytest.fixture(scope="function")
def test_db(tmp_path):
    """Setup test database with Tenant table including plugin_config."""
    db_path = tmp_path / "test_plugin_config.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield TestingSessionLocal

    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()
    # Optionally delete file, but OS will clean tmp_path


@pytest.fixture
def client(test_db):
    return TestClient(app)


def create_tenant(db, tenant_id=1, name="TestTenant", slug="test"):
    """Helper to create a tenant in the test database."""
    tenant = Tenant(id=tenant_id, name=name, slug=slug, active=True)
    db.add(tenant)
    db.commit()
    return tenant


class TestPluginConfigAPI:
    """Test PUT /tenants/{tenant_id}/plugins."""

    def test_endpoint_requires_auth(self, client, test_db):
        """Without auth, should return 401."""
        # Override require_auth to simulate no token by raising 401
        from fastapi import HTTPException
        def no_auth():
            raise HTTPException(status_code=401, detail="Not authenticated")
        app.dependency_overrides[require_auth] = no_auth
        response = client.put("/tenants/1/plugins", json={"plugins": {}})
        assert response.status_code == 401
        app.dependency_overrides.pop(require_auth)

    def test_requires_admin_role(self, client, test_db):
        """Non-admin user should get 403."""
        def override_auth():
            return {"sub": "1", "email": "user@example.com", "tenant_id": 1, "roles": ["user"]}
        app.dependency_overrides[require_auth] = override_auth
        response = client.put("/tenants/1/plugins", json={"plugins": {}})
        assert response.status_code == 403
        app.dependency_overrides.pop(require_auth)

    def test_update_plugin_config(self, client, test_db):
        """Tenant admin can update plugin configuration."""
        db = test_db()
        create_tenant(db, tenant_id=1, name="Acme", slug="acme")
        db.close()

        def override_auth():
            return FakeAuth.get_payload(tenant_id=1)
        app.dependency_overrides[require_auth] = override_auth

        new_config = {
            "plugins": {
                "lpr": {"enabled": True, "config": {"model": "v1"}},
                "weapon_detection": {"enabled": False, "config": {}}
            }
        }
        response = client.put("/tenants/1/plugins", json=new_config)
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Plugin configuration updated"
        assert data["tenant_id"] == 1

        # Verify persistence: get tenant from DB and check plugin_config
        db = test_db()
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        assert tenant.plugin_config == new_config
        db.close()

        app.dependency_overrides.pop(require_auth)

    def test_invalid_tenant_returns_404(self, client):
        """Updating non-existent tenant returns 404."""
        def override_auth():
            return FakeAuth.get_payload(tenant_id=999)
        app.dependency_overrides[require_auth] = override_auth
        response = client.put("/tenants/999/plugins", json={"plugins": {}})
        assert response.status_code == 404
        app.dependency_overrides.pop(require_auth)

    def test_plugin_config_schema_validation(self, client, test_db):
        """Invalid plugin config schema should return 400."""
        db = test_db()
        create_tenant(db, tenant_id=1)
        db.close()

        def override_auth():
            return FakeAuth.get_payload(tenant_id=1)
        app.dependency_overrides[require_auth] = override_auth

        # Missing 'plugins' key
        response = client.put("/tenants/1/plugins", json={"other": "value"})
        assert response.status_code == 400

        # plugins not a dict
        response = client.put("/tenants/1/plugins", json={"plugins": "invalid"})
        assert response.status_code == 400

        app.dependency_overrides.pop(require_auth)
