"""
T1.2.4: Create JWT validation middleware

Tests that the middleware correctly:
- Rejects requests without Authorization header (401)
- Rejects requests with invalid token (401)
- Accepts requests with valid RS256 token (200)
- Works as a FastAPI dependency
"""

import pytest
from pathlib import Path
from fastapi import FastAPI, Depends, Request
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.middleware import require_auth, set_jwt_public_key


def _generate_test_key_pair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private_pem, public_pem


def _create_test_token(payload: dict, private_key: bytes) -> str:
    from jose import jwt
    return jwt.encode(payload, private_key, algorithm="RS256")


@pytest.fixture(scope="function")
def app_with_auth():
    """Create a test FastAPI app with a protected endpoint."""
    # Generate a key pair for this test function
    private_key, public_key = _generate_test_key_pair()
    set_jwt_public_key(public_key)

    app = FastAPI()

    @app.get("/protected")
    def protected_endpoint(user_payload: dict = Depends(require_auth)):
        return {"status": "ok", "user_id": user_payload.get("sub")}

    return app, private_key


@pytest.fixture(scope="function")
def client(app_with_auth):
    app, _ = app_with_auth
    with TestClient(app) as c:
        yield c


class TestJWTValidationMiddleware:
    """Test JWT validation."""

    def test_missing_auth_header_returns_401(self, client):
        """Requests without Authorization header should return 401."""
        response = client.get("/protected")
        assert response.status_code == 401
        assert "authorization" in response.json()["detail"].lower() or "missing" in response.json()["detail"].lower()

    def test_invalid_token_returns_401(self, client):
        """Requests with malformed token should return 401."""
        response = client.get("/protected", headers={"Authorization": "Bearer invalidtoken"})
        assert response.status_code == 401

    def test_expired_token_returns_401(self, client, app_with_auth):
        """Expired tokens should be rejected."""
        import time
        app, private_key = app_with_auth
        expired_payload = {
            "sub": "123",
            "exp": int(time.time()) - 3600,  # expired 1 hour ago
            "iat": int(time.time()) - 7200,
        }
        token = _create_test_token(expired_payload, private_key)
        response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        # Could be either "expired" or "invalid token" - both indicate rejection
        detail = response.json()["detail"].lower()
        assert "expired" in detail or "invalid" in detail

    def test_valid_token_returns_200(self, client, app_with_auth):
        """Valid RS256 token should allow access."""
        app, private_key = app_with_auth
        payload = {"sub": "user123", "email": "test@example.com"}
        token = _create_test_token(payload, private_key)
        response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["user_id"] == "user123"

    def test_middleware_extracts_user_payload(self, client, app_with_auth):
        """Dependency should pass payload to endpoint."""
        app, private_key = app_with_auth
        payload = {"sub": "999", "roles": ["admin"], "tenant_id": 5}
        token = _create_test_token(payload, private_key)
        response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "999"

    def test_different_keys_rejected(self, client):
        """Token signed with a different key should be rejected."""
        key1_private, key1_public = _generate_test_key_pair()
        key2_private, _ = _generate_test_key_pair()
        set_jwt_public_key(key1_public)

        payload = {"sub": "123"}
        token = _create_test_token(payload, key2_private)
        response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401