"""
T1.2.7: API Key generation for programmatic access

Tests that POST /auth/api-keys generates a new API key, stores its hash,
and returns the full key only once.
"""

import pytest
import json
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "AuthService"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from auth_service import app, APIKey, Base, get_db
from shared.middleware import set_jwt_public_key
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from jose import jwt

SQLITE_DB = "sqlite:////tmp/test_api_keys.db"


@pytest.fixture(scope="function")
def test_db(tmp_path):
    """Setup test database with tables."""
    db_file = tmp_path / "test_api_keys.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Generate RSA keys
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    set_jwt_public_key(public_pem)

    # Override auth_service's PUBLIC_KEY so its decode_token uses this key
    import auth_service
    auth_service.PUBLIC_KEY = public_pem

    # Create tenant and user
    from auth_service import User, Tenant, UserTenant
    db = TestingSessionLocal()
    tenant = Tenant(name="Test Tenant", slug="test-tenant", active=True)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    tenant_id = tenant.id

    user = User(
        email="apiuser@example.com",
        full_name="API User",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$c2FsdFZhbHVl$fakehash",
        email_verified=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id
    user_email = user.email

    ut = UserTenant(user_id=user_id, tenant_id=tenant_id, status="active")
    db.add(ut)
    db.commit()
    db.close()

    # Create JWT
    now = int(datetime.utcnow().timestamp())
    payload = {
        "sub": str(user_id),
        "email": user_email,
        "tenant_id": tenant_id,
        "roles": [],
        "exp": now + 3600,
        "iat": now
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256")
    app.state.test_token = token

    yield TestingSessionLocal

    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def client(test_db):
    with TestClient(app) as c:
        yield c


class TestAPIKeyGeneration:
    """Test API key creation."""

    def test_create_api_key_returns_key_and_prefix(self, client):
        token = client.app.state.test_token
        response = client.post(
            "/auth/api-keys",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Test Key", "permissions": ["videos:create", "videos:read"], "expires_in_days": 30}
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        assert "id" in data
        assert "prefix" in data
        assert "key" in data
        assert data["name"] == "Test Key"
        assert data["permissions"] == ["videos:create", "videos:read"]
        assert data["prefix"] in data["key"]
        assert data["key"].startswith("cp_")
        assert len(data["key"]) > 20

    def test_api_key_is_stored_hashed(self, client, test_db):
        token = client.app.state.test_token
        response = client.post(
            "/auth/api-keys",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Hashed Key"}
        )
        assert response.status_code == 200
        full_key = response.json()["key"]
        key_id = response.json()["id"]

        from auth_service import APIKey
        db = test_db()
        stored = db.query(APIKey).filter(APIKey.id == key_id).first()
        db.close()
        assert stored is not None
        assert stored.key_hash != full_key
        from passlib.context import CryptContext
        pwd_ctx = CryptContext(schemes=["argon2"], deprecated="auto")
        assert pwd_ctx.verify(full_key, stored.key_hash)

    def test_multiple_keys_have_different_prefixes(self, client):
        token = client.app.state.test_token
        prefixes = []
        for i in range(3):
            resp = client.post(
                "/auth/api-keys",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": f"Key {i}"}
            )
            assert resp.status_code == 200
            prefixes.append(resp.json()["prefix"])
        assert len(set(prefixes)) == 3

    def test_create_key_without_auth_fails(self, client):
        response = client.post("/auth/api-keys", json={"name": "No Auth"})
        assert response.status_code == 401

    def test_api_key_has_tenant_association(self, client, test_db):
        token = client.app.state.test_token
        response = client.post(
            "/auth/api-keys",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Tenant Key"}
        )
        assert response.status_code == 200
        key_id = response.json()["id"]
        from auth_service import APIKey
        db = test_db()
        api_key = db.query(APIKey).filter(APIKey.id == key_id).first()
        db.close()
        assert api_key.tenant_id is not None
        assert api_key.user_id is not None

    def test_expiration_set_correctly(self, client):
        token = client.app.state.test_token
        now = datetime.utcnow()
        response = client.post(
            "/auth/api-keys",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Expiring Key", "expires_in_days": 7}
        )
        assert response.status_code == 200
        expires_at_str = response.json()["expires_at"]
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        diff = expires_at - now
        assert 6.5 < diff.days < 7.5
