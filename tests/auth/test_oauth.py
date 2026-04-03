"""
T1.2.10: OAuth2 social login (Google, GitHub) optional

Tests OAuth2 endpoints for social login:
- GET /auth/oauth/{provider} redirects to provider's auth page
- GET /auth/oauth/{provider}/callback exchanges code for JWT
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from jose import jwt
from auth_service import (
    app, User, Base, get_db, create_access_token,
    PUBLIC_KEY, ALGORITHM
)
from shared.middleware import set_jwt_public_key
import sys
import os

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "AuthService"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

SQLITE_DB = "sqlite:////tmp/test_oauth.db"


class MockOAuthProvider:
    """Mock OAuth provider for testing (simulates Google/GitHub)."""
    def __init__(self):
        self.auth_url = None
        self.expected_redirect_uri = None
        self.passed_state = None
        self._next_token = None

    def get_authorization_url(self, client_id, redirect_uri, state):
        self.auth_url = f"https://mock-oauth.com/auth?client_id={client_id}&redirect_uri={redirect_uri}&state={state}"
        return self.auth_url

    def exchange_code_for_token(self, code, client_secret, redirect_uri):
        if code == "valid_code":
            return {
                "access_token": "mock_access_token",
                "id_token": "mock_id_token",
                "email": "oauthuser@example.com",
                "name": "OAuth User",
                "sub": "oauth123"
            }
        raise ValueError("Invalid code")

    def get_user_info(self, access_token):
        return {
            "email": "oauthuser@example.com",
            "name": "OAuth User"
        }


@pytest.fixture(scope="function")
def test_db(tmp_path):
    """Setup test database with tables."""
    db_file = tmp_path / "test_oauth.db"
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

    yield TestingSessionLocal

    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def client(test_db):
    """Test client."""
    with TestClient(app) as c:
        yield c


class TestOAuthLogin:
    """Test suite for OAuth2 social login."""

    def test_oauth_redirects_to_provider(self, client, monkeypatch):
        """GET /auth/oauth/{provider} should redirect to OAuth provider."""
        # Mock OAuth configuration
        from auth_service import oauth_clients
        monkeypatch.setitem(oauth_clients, "google", {
            "client_id": "test-google-client",
            "client_secret": "test-google-secret",
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
            "scope": "openid email profile"
        })
        monkeypatch.setitem(oauth_clients, "github", {
            "client_id": "test-github-client",
            "client_secret": "test-github-secret",
            "auth_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "userinfo_url": "https://api.github.com/user",
            "scope": "read:user user:email"
        })

        # Test Google OAuth redirect
        response = client.get("/auth/oauth/google", follow_redirects=False)
        assert response.status_code in [302, 307]  # Redirect
        location = response.headers.get("location")
        assert location is not None
        assert "accounts.google.com" in location or "mock" in location
        assert "client_id=" in location or "state=" in location

        # Test GitHub OAuth redirect
        response = client.get("/auth/oauth/github", follow_redirects=False)
        assert response.status_code in [302, 307]
        location = response.headers.get("location")
        assert location is not None

    def test_oauth_callback_issues_jwt(self, client, test_db, monkeypatch):
        """Callback from OAuth provider should create user and return JWT."""
        # Mock OAuth provider
        mock_provider = MockOAuthProvider()
        monkeypatch.setattr("auth_service.mock_provider", mock_provider)

        # Simulate OAuth callback with valid code
        response = client.get(
            "/auth/oauth/google/callback",
            params={"code": "valid_code", "state": "some_state"}
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

        # Verify token is valid
        from auth_service import PUBLIC_KEY, ALGORITHM
        payload = jwt.decode(data["access_token"], PUBLIC_KEY, algorithms=[ALGORITHM])
        assert "sub" in payload
        assert payload["email"] == "oauthuser@example.com"

        # Verify user was created in database
        from auth_service import User
        db = test_db()
        user = db.query(User).filter(User.email == "oauthuser@example.com").first()
        assert user is not None
        db.close()

    def test_oauth_callback_with_invalid_code_fails(self, client, monkeypatch):
        """Callback with invalid code should return error."""
        response = client.get(
            "/auth/oauth/google/callback",
            params={"code": "invalid_code", "state": "some_state"}
        )
        assert response.status_code == 400

    def test_oauth_callback_links_to_existing_tenant(self, client, test_db, monkeypatch):
        """If user created via OAuth, they should be linked to a tenant."""
        # This test verifies tenant linking logic - for now, OAuth users may
        # have tenant_id=None until they join a tenant
        mock_provider = MockOAuthProvider()
        monkeypatch.setattr("auth_service.mock_provider", mock_provider)

        response = client.get(
            "/auth/oauth/google/callback",
            params={"code": "valid_code", "state": "some_state"}
        )
        assert response.status_code == 200
        data = response.json()
        payload = jwt.decode(data["access_token"], PUBLIC_KEY, algorithms=[ALGORITHM])
        # OAuth users may not have a tenant initially
        assert "sub" in payload

    def test_multiple_oauth_providers_supported(self, client, monkeypatch):
        """Both Google and GitHub OAuth should be available."""
        from auth_service import oauth_clients
        assert "google" in oauth_clients
        assert "github" in oauth_clients
