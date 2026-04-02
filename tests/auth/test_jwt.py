"""
T1.2.3: Implement JWT token issuance (RS256)

Tests that JWT tokens:
- Use RS256 algorithm (not HS256)
- Include proper claims: sub, tenant_id, roles, exp, iat
- Are properly signed and verifiable
- Expire after configured time
"""

import pytest
import time
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "AuthService"))

from auth_service import (
    app, User, Tenant, UserTenant, Role, UserRole,
    Base, get_db, create_access_token, decode_token
)

# Use SQLite in-memory but with shared file
SQLITE_TEST_DB = "sqlite:////tmp/test_jwt.db"


@pytest.fixture(scope="function")
def test_db():
    """Create a fresh database with RSA keys for each test."""
    engine = create_engine(SQLITE_TEST_DB)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Override get_db
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Generate RSA key pair for RS256 and serialize to PEM
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    # Store in module for token creation/verification
    import auth_service
    auth_service.PRIVATE_KEY = private_pem
    auth_service.PUBLIC_KEY = public_pem
    auth_service.ALGORITHM = "RS256"

    yield TestingSessionLocal

    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def client(test_db):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def setup_user_with_tenant_and_roles(test_db):
    """Create a user with tenant membership and roles."""
    db = test_db()
    # Create tenant
    tenant = Tenant(name="Test Tenant", slug="test-tenant", active=True)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    # Create user
    from auth_service import get_password_hash
    user = User(
        email="jwt_user@example.com",
        full_name="JWT User",
        password_hash=get_password_hash("Password123!"),
        email_verified=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Link user to tenant
    user_tenant = UserTenant(user_id=user.id, tenant_id=tenant.id, status="active")
    db.add(user_tenant)
    db.commit()
    db.refresh(user_tenant)

    # Create role with permissions
    role = Role(
        tenant_id=tenant.id,
        name="editor",
        description="Editor role",
        permissions='["videos:read:tenant", "videos:create:*"]'
    )
    db.add(role)
    db.commit()
    db.refresh(role)

    # Assign role to user
    user_role = UserRole(user_tenant_id=user_tenant.id, role_id=role.id)
    db.add(user_role)
    db.commit()

    return {
        "user": user,
        "tenant": tenant,
        "user_tenant": user_tenant,
        "role": role
    }


class TestJWTIssuance:
    """Test JWT token creation with RS256."""

    def test_login_returns_rs256_token(self, client, test_db, setup_user_with_tenant_and_roles):
        """Login should return a token signed with RS256."""
        response = client.post("/auth/login", json={
            "email": "jwt_user@example.com",
            "password": "Password123!"
        })
        assert response.status_code == 200
        data = response.json()
        token = data["access_token"]

        # Check token header for algorithm
        from jose import jwt
        header = jwt.get_unverified_header(token)
        assert header["alg"] == "RS256", "Token must use RS256 algorithm"

    def test_token_contains_required_claims(self, client, test_db, setup_user_with_tenant_and_roles):
        """Token must include sub, tenant_id, roles, exp, iat."""
        response = client.post("/auth/login", json={
            "email": "jwt_user@example.com",
            "password": "Password123!"
        })
        assert response.status_code == 200
        token = response.json()["access_token"]

        from auth_service import PUBLIC_KEY, ALGORITHM
        from jose import jwt

        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])

        # Check required claims
        assert "sub" in payload
        assert "tenant_id" in payload
        assert "roles" in payload
        assert "exp" in payload
        assert "iat" in payload

        # Verify types
        assert isinstance(payload["sub"], (str, int))
        assert isinstance(payload["tenant_id"], (str, int))
        assert isinstance(payload["roles"], list)
        assert isinstance(payload["exp"], (int, float))
        assert isinstance(payload["iat"], (int, float))

    def test_token_expiration_is_reasonable(self, client, test_db, setup_user_with_tenant_and_roles):
        """Token should expire in approximately ACCESS_TOKEN_EXPIRE_MINUTES."""
        response = client.post("/auth/login", json={
            "email": "jwt_user@example.com",
            "password": "Password123!"
        })
        token = response.json()["access_token"]

        from auth_service import PUBLIC_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
        from jose import jwt

        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        exp_timestamp = payload["exp"]
        iat_timestamp = payload["iat"]

        # Calculate actual TTL
        ttl_seconds = exp_timestamp - iat_timestamp
        expected_seconds = ACCESS_TOKEN_EXPIRE_MINUTES * 60

        # Allow 60-second tolerance due to execution time
        assert abs(ttl_seconds - expected_seconds) < 60, \
            f"Token TTL should be ~{expected_seconds}s, got {ttl_seconds}s"

    def test_token_roles_from_user_tenant_roles(self, client, test_db, setup_user_with_tenant_and_roles):
        """Token should include role names from the user's roles in the tenant."""
        response = client.post("/auth/login", json={
            "email": "jwt_user@example.com",
            "password": "Password123!"
        })
        token = response.json()["access_token"]

        from auth_service import PUBLIC_KEY, ALGORITHM
        from jose import jwt

        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])

        assert "roles" in payload
        assert "editor" in payload["roles"]

    def test_register_creates_rs256_token(self, client, test_db):
        """Registration should also return RS256 token."""
        response = client.post("/auth/register", json={
            "email": "newjwt@example.com",
            "password": "SecurePass123!",
            "full_name": "New JWT User"
        })
        assert response.status_code == 200
        token = response.json()["access_token"]

        from auth_service import PUBLIC_KEY, ALGORITHM
        from jose import jwt

        header = jwt.get_unverified_header(token)
        assert header["alg"] == "RS256"

        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        assert "sub" in payload
        assert "tenant_id" in payload  # Should be None or first tenant after creation
        assert "roles" in payload
        assert "exp" in payload
        assert "iat" in payload

    def test_rs256_token_can_be_verified_with_public_key(self, client, test_db, setup_user_with_tenant_and_roles):
        """Token signature should be verifiable with the public key."""
        response = client.post("/auth/login", json={
            "email": "jwt_user@example.com",
            "password": "Password123!"
        })
        token = response.json()["access_token"]

        from auth_service import PUBLIC_KEY, ALGORITHM
        from jose import jwt

        # This should not raise exception
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        assert payload is not None

    def test_rs256_token_verification_fails_with_wrong_key(self, client, test_db, setup_user_with_tenant_and_roles):
        """Token should fail verification with a different key."""
        response = client.post("/auth/login", json={
            "email": "jwt_user@example.com",
            "password": "Password123!"
        })
        token = response.json()["access_token"]

        from jose import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa

        # Generate a different key
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()

        with pytest.raises(jwt.JWTError):
            jwt.decode(token, other_key, algorithms=["RS256"])
