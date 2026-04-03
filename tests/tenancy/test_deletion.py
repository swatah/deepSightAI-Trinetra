"""
T1.3.8: Tenant deletion (GDPR Article 17)

Tests DELETE /tenants/{id} cascades deletion to all related data.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from pathlib import Path
import sys

# Add AuthService to path so we can import auth_service
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "AuthService"))

from auth_service import app, get_db, require_auth, Base, Tenant, User, UserTenant, Role, UserRole, get_password_hash
from shared.middleware import set_jwt_public_key
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from jose import jwt

SQLITE_DB = "sqlite:////tmp/test_deletion.db"


class FakeAuth:
    """Mock auth dependency."""
    @staticmethod
    def get_payload():
        return {
            "sub": "999",
            "email": "admin@example.com",
            "tenant_id": 1,
            "roles": ["admin"]
        }


@pytest.fixture(scope="function")
def test_db(tmp_path):
    """Setup test database."""
    db_file = tmp_path / "test_deletion.db"
    engine = create_engine(f"sqlite:///{db_file}")

    # Enable foreign key constraints in SQLite (required for cascade)
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Override auth to return admin payload
    def override_auth():
        return FakeAuth.get_payload()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_auth] = override_auth

    # Also set JWT public key (required by require_auth)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    set_jwt_public_key(public_pem)

    yield TestingSessionLocal

    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture
def client(test_db):
    return TestClient(app)


class TestTenantDeletion:
    """Test DELETE /tenants/{id}."""

    def test_endpoint_requires_auth(self, client):
        """Without auth, should return 401."""
        # Clear auth override to simulate no auth
        original = app.dependency_overrides.pop(require_auth, None)
        response = client.delete("/tenants/1")
        assert response.status_code == 401
        # Restore
        if original:
            app.dependency_overrides[require_auth] = original

    def test_delete_tenant_cascades_in_db(self, client, test_db):
        """Deleting a tenant should remove it and cascade related records."""
        # Create a tenant
        db = test_db()
        tenant = Tenant(name="ToDelete", slug="todelete", active=True)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        tenant_id = tenant.id

        # Create a user and link
        user = User(
            email="deleteme@example.com",
            full_name="Delete Me",
            password_hash=get_password_hash("pass"),
            email_verified=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        ut = UserTenant(user_id=user.id, tenant_id=tenant.id, status="active")
        db.add(ut)
        db.commit()
        db.refresh(ut)

        # Create role
        role = Role(tenant_id=tenant.id, name="admin", description="Admin", permissions="[]")
        db.add(role)
        db.commit()
        db.refresh(role)

        user_role = UserRole(user_tenant_id=ut.id, role_id=role.id)
        db.add(user_role)
        db.commit()
        db.close()

        # Delete tenant
        response = client.delete(f"/tenants/{tenant_id}")
        assert response.status_code in [200, 204], f"Expected success, got {response.status_code}: {response.text}"

        # Verify tenant is gone
        db = test_db()
        deleted = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        assert deleted is None

        # Verify related data also gone due to cascade
        remaining_ut = db.query(UserTenant).filter(UserTenant.tenant_id == tenant_id).first()
        assert remaining_ut is None
        remaining_roles = db.query(Role).filter(Role.tenant_id == tenant_id).first()
        assert remaining_roles is None
        db.close()

    def test_delete_nonexistent_tenant_returns_404(self, client):
        """Deleting a non-existent tenant returns 404."""
        response = client.delete("/tenants/99999")
        assert response.status_code == 404
