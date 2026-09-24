"""
T1.2.2: Create AuthService FastAPI app

Tests that the AuthService implements the POST /auth/register endpoint correctly.
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from deepSightAI.Trinetra.AuthService.auth_service import (
    app,
    User,
    Tenant,
    UserTenant,
    Role,
    UserRole,
    APIKey,
    Base,
    get_db,
    create_access_token,
    pwd_context,
)

# Use SQLite in-memory database for tests to avoid needing Postgres
SQLITE_TEST_DB = "sqlite:////tmp/test_deepSightAI-Trinetra.db"


@pytest.fixture(scope="function")
def test_db():
    """Create a fresh database for each test."""
    engine = create_engine(SQLITE_TEST_DB)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Override the get_db dependency
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield TestingSessionLocal

    # Cleanup
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def client(test_db):
    """FastAPI test client."""
    with TestClient(app) as c:
        yield c


class TestAuthService:
    """Test suite for AuthService."""

    def test_health_check(self, client):
        """Service should respond to health check."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_register_creates_user_and_returns_jwt(self, client, test_db):
        """
        POST /auth/register should:
        - Create a new user in the database
        - Return a JWT token in the response body
        - Token should contain user_id and email
        """
        payload = {
            "email": "test@example.com",
            "password": "SecurePass123!",
            "full_name": "Test User"
        }

        response = client.post("/auth/register", json=payload)
        assert response.status_code == 200, f"Failed: {response.text}"

        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

        # Verify token is valid JWT (can decode with RS256)
        token = data["access_token"]
        from jose import jwt
        from auth_service import PUBLIC_KEY, ALGORITHM
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        assert "sub" in payload  # user_id
        assert "email" in payload
        assert payload["email"] == "test@example.com"

        # Verify user was created in database
        db = test_db()
        user = db.query(User).filter(User.email == "test@example.com").first()
        assert user is not None
        assert user.full_name == "Test User"
        assert user.email_verified is False
        # Verify password is hashed (not plaintext)
        assert user.password_hash != "SecurePass123!"
        assert pwd_context.verify("SecurePass123!", user.password_hash)

    def test_register_duplicate_email_fails(self, client, test_db):
        """Cannot register with an already-used email."""
        payload = {
            "email": "duplicate@example.com",
            "password": "Password123!",
            "full_name": "First User"
        }

        # First registration
        response1 = client.post("/auth/register", json=payload)
        assert response1.status_code == 200

        # Second registration with same email
        response2 = client.post("/auth/register", json=payload)
        assert response2.status_code == 400
        assert "already registered" in response2.json()["detail"].lower()

    def test_register_password_minimum_length(self, client):
        """Enforce password minimum length (8 chars)."""
        payload = {
            "email": "shortpass@example.com",
            "password": "short",
            "full_name": "Short Pass User"
        }
        response = client.post("/auth/register", json=payload)
        assert response.status_code == 422  # Validation error from Pydantic

    def test_login_success(self, client, test_db):
        """Valid credentials should return JWT."""
        # First create a user directly in DB
        password = "MyPassword123!"
        user = User(
            email="login@example.com",
            full_name="Login Test User",
            password_hash=get_password_hash(password),
            email_verified=True
        )
        db = test_db()
        db.add(user)
        db.commit()
        db.refresh(user)

        # Now attempt login
        response = client.post("/auth/login", json={"email": "login@example.com", "password": password})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

        # Verify token contains correct user_id
        from jose import jwt
        from auth_service import PUBLIC_KEY, ALGORITHM
        payload = jwt.decode(data["access_token"], PUBLIC_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == str(user.id)
        assert payload["email"] == user.email

    def test_login_invalid_credentials(self, client, test_db):
        """Invalid email/password returns 401."""
        response = client.post("/auth/login", json={
            "email": "nonexistent@example.com",
            "password": "wrongpass"
        })
        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()

    def test_login_updates_last_login_at(self, client, test_db):
        """Successful login should update user.last_login_at."""
        password = "TestPass123!"
        user = User(
            email="lastlogin@example.com",
            full_name="Last Login Test",
            password_hash=get_password_hash(password),
            last_login_at=None
        )
        db = test_db()
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.last_login_at is None

        # Login
        response = client.post("/auth/login", json={"email": user.email, "password": password})
        assert response.status_code == 200

        # Check last_login_at was updated
        db.refresh(user)
        assert user.last_login_at is not None

    def test_dsai_get_tenant_profile(self, client, test_db):
        """GET /tenants/{tenant_id} should return tenant profile and plugin_config."""
        dsai_db = test_db()
        dsai_tenant = Tenant(
            name="Alpha Corp",
            slug="alpha-corp",
            description="Alpha test tenant",
            active=True,
            plugin_config={"sector": "commercial"},
        )
        dsai_db.add(dsai_tenant)
        dsai_db.commit()
        dsai_db.refresh(dsai_tenant)

        # Issue admin token
        dsai_token = create_access_token({
            "sub": "1",
            "email": "admin@example.com",
            "tenant_id": dsai_tenant.id,
            "roles": ["admin"],
        })

        # Fetch by slug
        dsai_resp_slug = client.get(
            f"/tenants/{dsai_tenant.slug}",
            headers={"Authorization": f"Bearer {dsai_token}"},
        )
        assert dsai_resp_slug.status_code == 200
        dsai_data_slug = dsai_resp_slug.json()
        assert dsai_data_slug["slug"] == "alpha-corp"
        assert dsai_data_slug["plugin_config"]["sector"] == "commercial"

        # Fetch by numeric ID
        dsai_resp_id = client.get(
            f"/tenants/{dsai_tenant.id}",
            headers={"Authorization": f"Bearer {dsai_token}"},
        )
        assert dsai_resp_id.status_code == 200
        assert dsai_resp_id.json()["name"] == "Alpha Corp"

        # Not found
        dsai_resp_404 = client.get(
            "/tenants/non-existent-tenant",
            headers={"Authorization": f"Bearer {dsai_token}"},
        )
        assert dsai_resp_404.status_code == 404

    def test_dsai_create_tenant_requires_admin(self, client, test_db):
        """POST /tenants should reject callers without the 'admin' role."""
        dsai_token = create_access_token({
            "sub": "1", "email": "operator@example.com", "tenant_id": None, "roles": ["operator"],
        })
        dsai_resp = client.post(
            "/tenants",
            json={"name": "Beta Corp", "slug": "beta-corp", "sector": "commercial"},
            headers={"Authorization": f"Bearer {dsai_token}"},
        )
        assert dsai_resp.status_code == 403

    def test_dsai_create_tenant_persists_sector_in_plugin_config(self, client, test_db):
        """POST /tenants should create a tenant and store sector in plugin_config."""
        dsai_token = create_access_token({
            "sub": "1", "email": "admin@example.com", "tenant_id": None, "roles": ["admin"],
        })
        dsai_resp = client.post(
            "/tenants",
            json={"name": "Beta Corp", "slug": "beta-corp", "sector": "logistics"},
            headers={"Authorization": f"Bearer {dsai_token}"},
        )
        assert dsai_resp.status_code == 201
        dsai_data = dsai_resp.json()
        assert dsai_data["slug"] == "beta-corp"
        assert dsai_data["plugin_config"]["sector"] == "logistics"

        # Duplicate slug should be rejected
        dsai_dup = client.post(
            "/tenants",
            json={"name": "Beta Corp 2", "slug": "beta-corp", "sector": "logistics"},
            headers={"Authorization": f"Bearer {dsai_token}"},
        )
        assert dsai_dup.status_code == 400

    def test_dsai_list_tenants_requires_admin_and_returns_created_tenants(self, client, test_db):
        """GET /tenants should list tenants, admin only."""
        dsai_db = test_db()
        dsai_db.add(Tenant(name="Gamma Corp", slug="gamma-corp", active=True, plugin_config={"sector": "commercial"}))
        dsai_db.commit()

        dsai_operator_token = create_access_token({
            "sub": "1", "email": "operator@example.com", "tenant_id": None, "roles": ["operator"],
        })
        assert client.get("/tenants", headers={"Authorization": f"Bearer {dsai_operator_token}"}).status_code == 403

        dsai_admin_token = create_access_token({
            "sub": "1", "email": "admin@example.com", "tenant_id": None, "roles": ["admin"],
        })
        dsai_resp = client.get("/tenants", headers={"Authorization": f"Bearer {dsai_admin_token}"})
        assert dsai_resp.status_code == 200
        dsai_slugs = [t["slug"] for t in dsai_resp.json()]
        assert "gamma-corp" in dsai_slugs

    def test_dsai_create_tenant_user_provisions_membership_and_role(self, client, test_db):
        """POST /tenants/{tenant_id}/users should create the user, membership, and role assignment."""
        dsai_db = test_db()
        dsai_tenant = Tenant(name="Delta Corp", slug="delta-corp", active=True, plugin_config={})
        dsai_db.add(dsai_tenant)
        dsai_db.commit()
        dsai_db.refresh(dsai_tenant)

        dsai_admin_token = create_access_token({
            "sub": "1", "email": "admin@example.com", "tenant_id": None, "roles": ["admin"],
        })
        dsai_resp = client.post(
            f"/tenants/{dsai_tenant.id}/users",
            json={"email": "officer@delta.example", "password": "supersecret1", "role": "operator"},
            headers={"Authorization": f"Bearer {dsai_admin_token}"},
        )
        assert dsai_resp.status_code == 201
        dsai_data = dsai_resp.json()
        assert dsai_data["email"] == "officer@delta.example"
        assert dsai_data["roles"] == ["operator"]

        dsai_user = dsai_db.query(User).filter(User.email == "officer@delta.example").first()
        assert dsai_user is not None
        dsai_membership = (
            dsai_db.query(UserTenant)
            .filter(UserTenant.user_id == dsai_user.id, UserTenant.tenant_id == dsai_tenant.id)
            .first()
        )
        assert dsai_membership is not None
        dsai_role = dsai_db.query(Role).filter(Role.tenant_id == dsai_tenant.id, Role.name == "operator").first()
        assert dsai_role is not None
        dsai_assignment = (
            dsai_db.query(UserRole)
            .filter(UserRole.user_tenant_id == dsai_membership.id, UserRole.role_id == dsai_role.id)
            .first()
        )
        assert dsai_assignment is not None

        # Calling again with the same email should attach the existing user, not duplicate it
        dsai_resp2 = client.post(
            f"/tenants/{dsai_tenant.id}/users",
            json={"email": "officer@delta.example", "password": "irrelevant1", "role": "viewer"},
            headers={"Authorization": f"Bearer {dsai_admin_token}"},
        )
        assert dsai_resp2.status_code == 201
        assert dsai_db.query(User).filter(User.email == "officer@delta.example").count() == 1

    def test_dsai_create_tenant_user_requires_admin(self, client, test_db):
        """POST /tenants/{tenant_id}/users should reject callers without the 'admin' role."""
        dsai_db = test_db()
        dsai_tenant = Tenant(name="Epsilon Corp", slug="epsilon-corp", active=True, plugin_config={})
        dsai_db.add(dsai_tenant)
        dsai_db.commit()
        dsai_db.refresh(dsai_tenant)

        dsai_token = create_access_token({
            "sub": "1", "email": "operator@example.com", "tenant_id": dsai_tenant.id, "roles": ["operator"],
        })
        dsai_resp = client.post(
            f"/tenants/{dsai_tenant.id}/users",
            json={"email": "x@example.com", "password": "supersecret1", "role": "operator"},
            headers={"Authorization": f"Bearer {dsai_token}"},
        )
        assert dsai_resp.status_code == 403

    def test_dsai_update_tenant_status_requires_admin_and_toggles_active(self, client, test_db):
        """PATCH /tenants/{tenant_id} should require 'admin' and update the active flag."""
        dsai_db = test_db()
        dsai_tenant = Tenant(name="Zeta Corp", slug="zeta-corp", active=True, plugin_config={})
        dsai_db.add(dsai_tenant)
        dsai_db.commit()
        dsai_db.refresh(dsai_tenant)

        dsai_operator_token = create_access_token({
            "sub": "1", "email": "operator@example.com", "tenant_id": dsai_tenant.id, "roles": ["operator"],
        })
        dsai_denied = client.patch(
            f"/tenants/{dsai_tenant.id}",
            json={"active": False},
            headers={"Authorization": f"Bearer {dsai_operator_token}"},
        )
        assert dsai_denied.status_code == 403

        dsai_admin_token = create_access_token({
            "sub": "1", "email": "admin@example.com", "tenant_id": None, "roles": ["admin"],
        })
        dsai_resp = client.patch(
            f"/tenants/{dsai_tenant.id}",
            json={"active": False},
            headers={"Authorization": f"Bearer {dsai_admin_token}"},
        )
        assert dsai_resp.status_code == 200
        assert dsai_resp.json()["active"] is False

        dsai_db.refresh(dsai_tenant)
        assert dsai_tenant.active is False

    def test_dsai_list_tenant_users_requires_admin_and_returns_roles(self, client, test_db):
        """GET /tenants/{tenant_id}/users should list members with their roles, admin only."""
        dsai_db = test_db()
        dsai_tenant = Tenant(name="Eta Corp", slug="eta-corp", active=True, plugin_config={})
        dsai_db.add(dsai_tenant)
        dsai_db.commit()
        dsai_db.refresh(dsai_tenant)

        dsai_admin_token = create_access_token({
            "sub": "1", "email": "admin@example.com", "tenant_id": None, "roles": ["admin"],
        })
        dsai_create_resp = client.post(
            f"/tenants/{dsai_tenant.id}/users",
            json={"email": "member@eta.example", "password": "supersecret1", "role": "viewer"},
            headers={"Authorization": f"Bearer {dsai_admin_token}"},
        )
        assert dsai_create_resp.status_code == 201

        dsai_operator_token = create_access_token({
            "sub": "1", "email": "operator@example.com", "tenant_id": dsai_tenant.id, "roles": ["operator"],
        })
        assert client.get(
            f"/tenants/{dsai_tenant.id}/users",
            headers={"Authorization": f"Bearer {dsai_operator_token}"},
        ).status_code == 403

        dsai_list_resp = client.get(
            f"/tenants/{dsai_tenant.id}/users",
            headers={"Authorization": f"Bearer {dsai_admin_token}"},
        )
        assert dsai_list_resp.status_code == 200
        dsai_emails = [u["email"] for u in dsai_list_resp.json()]
        assert "member@eta.example" in dsai_emails
        dsai_member = next(u for u in dsai_list_resp.json() if u["email"] == "member@eta.example")
        assert dsai_member["roles"] == ["viewer"]

    def test_dsai_list_users_across_tenants_in_single_call(self, client, test_db):
        """GET /users should list members across all tenants in one call, filterable by tenant_id, admin only."""
        dsai_db = test_db()
        dsai_tenant_a = Tenant(name="Iota Corp", slug="iota-corp", active=True, plugin_config={})
        dsai_tenant_b = Tenant(name="Kappa Corp", slug="kappa-corp", active=True, plugin_config={})
        dsai_db.add_all([dsai_tenant_a, dsai_tenant_b])
        dsai_db.commit()
        dsai_db.refresh(dsai_tenant_a)
        dsai_db.refresh(dsai_tenant_b)

        dsai_admin_token = create_access_token({
            "sub": "1", "email": "admin@example.com", "tenant_id": None, "roles": ["admin"],
        })
        assert client.post(
            f"/tenants/{dsai_tenant_a.id}/users",
            json={"email": "member-a@iota.example", "password": "supersecret1", "role": "viewer"},
            headers={"Authorization": f"Bearer {dsai_admin_token}"},
        ).status_code == 201
        assert client.post(
            f"/tenants/{dsai_tenant_b.id}/users",
            json={"email": "member-b@kappa.example", "password": "supersecret1", "role": "operator"},
            headers={"Authorization": f"Bearer {dsai_admin_token}"},
        ).status_code == 201

        dsai_operator_token = create_access_token({
            "sub": "1", "email": "operator@example.com", "tenant_id": dsai_tenant_a.id, "roles": ["operator"],
        })
        assert client.get(
            "/users", headers={"Authorization": f"Bearer {dsai_operator_token}"}
        ).status_code == 403

        dsai_all_resp = client.get("/users", headers={"Authorization": f"Bearer {dsai_admin_token}"})
        assert dsai_all_resp.status_code == 200
        dsai_all_emails = {u["email"] for u in dsai_all_resp.json()}
        assert "member-a@iota.example" in dsai_all_emails
        assert "member-b@kappa.example" in dsai_all_emails

        dsai_scoped_resp = client.get(
            f"/users?tenant_id={dsai_tenant_a.id}",
            headers={"Authorization": f"Bearer {dsai_admin_token}"},
        )
        assert dsai_scoped_resp.status_code == 200
        dsai_scoped_emails = {u["email"] for u in dsai_scoped_resp.json()}
        assert dsai_scoped_emails == {"member-a@iota.example"}

    def test_dsai_list_api_keys_requires_admin_and_omits_secrets(self, client, test_db):
        """GET /auth/api-keys should list keys for the caller's tenant without exposing the hash."""
        dsai_db = test_db()
        dsai_tenant = Tenant(name="Theta Corp", slug="theta-corp", active=True, plugin_config={})
        dsai_db.add(dsai_tenant)
        dsai_db.commit()
        dsai_db.refresh(dsai_tenant)

        dsai_user = User(
            email="keyowner@theta.example",
            full_name="Key Owner",
            password_hash=get_password_hash("supersecret1"),
            email_verified=True,
        )
        dsai_db.add(dsai_user)
        dsai_db.commit()
        dsai_db.refresh(dsai_user)

        dsai_db.add(APIKey(
            tenant_id=dsai_tenant.id,
            user_id=dsai_user.id,
            prefix="cp_testkey1",
            key_hash="irrelevant-hash",
            name="CI Ingest Key",
            permissions="[]",
            expires_at=datetime.utcnow() + timedelta(days=30),
        ))
        dsai_db.commit()

        dsai_operator_token = create_access_token({
            "sub": str(dsai_user.id), "email": dsai_user.email, "tenant_id": dsai_tenant.id, "roles": ["operator"],
        })
        assert client.get(
            "/auth/api-keys", headers={"Authorization": f"Bearer {dsai_operator_token}"}
        ).status_code == 403

        dsai_admin_token = create_access_token({
            "sub": str(dsai_user.id), "email": dsai_user.email, "tenant_id": dsai_tenant.id, "roles": ["admin"],
        })
        dsai_resp = client.get("/auth/api-keys", headers={"Authorization": f"Bearer {dsai_admin_token}"})
        assert dsai_resp.status_code == 200
        dsai_keys = dsai_resp.json()
        assert len(dsai_keys) == 1
        assert dsai_keys[0]["name"] == "CI Ingest Key"
        assert dsai_keys[0]["prefix"] == "cp_testkey1"
        assert "key_hash" not in dsai_keys[0]
        assert "key" not in dsai_keys[0]


# Helper function needed in test
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)
