"""
T1.2.5: Implement tenant extraction from JWT

Tests that tenant_id is correctly extracted from JWT claims and
available via tenant extraction utility.
"""

import pytest
from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.middleware import require_auth, set_jwt_public_key
from shared.tenant_context import get_tenant_id


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


def _create_token(payload: dict, private_key: bytes) -> str:
    from jose import jwt
    return jwt.encode(payload, private_key, algorithm="RS256")


@pytest.fixture(scope="function")
def app_with_tenant_endpoint():
    private_key, public_key = _generate_test_key_pair()
    set_jwt_public_key(public_key)

    app = FastAPI()

    @app.get("/tenant")
    def get_my_tenant(tenant_id = Depends(get_tenant_id)):
        return {"tenant_id": tenant_id}

    # We need to require auth first to set request.state.tenant_id, then get_tenant_id uses it.
    # We can chain dependencies: but better to create a combined dependency
    # Instead, we'll include both Depends in endpoint
    # Actually we need to ensure require_auth runs before get_tenant_id. FastAPI guarantees order of Depends based on function signature order.
    @app.get("/tenant2")
    def get_my_tenant2(payload: dict = Depends(require_auth), tenant_id = Depends(get_tenant_id)):
        return {"tenant_id": tenant_id, "user_id": payload.get("sub")}

    return app, private_key


@pytest.fixture(scope="function")
def client(app_with_tenant_endpoint):
    app, _ = app_with_tenant_endpoint
    with TestClient(app) as c:
        yield c


class TestTenantContext:
    """Test tenant extraction from JWT."""

    def test_tenant_id_extracted_from_token(self, client, app_with_tenant_endpoint):
        app, private_key = app_with_tenant_endpoint
        payload = {
            "sub": "user456",
            "tenant_id": 42,
            "roles": ["viewer"]
        }
        token = _create_token(payload, private_key)
        response = client.get("/tenant2", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == 42
        assert data["user_id"] == "user456"

    def test_missing_tenant_id_returns_400(self, client, app_with_tenant_endpoint):
        """If token lacks tenant_id, get_tenant_id should error."""
        app, private_key = app_with_tenant_endpoint
        payload = {
            "sub": "user789"
            # No tenant_id
        }
        token = _create_token(payload, private_key)
        response = client.get("/tenant2", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 400
        assert "tenant_id" in response.json()["detail"].lower()

    def test_tenant_id_available_to_endpoints(self, client, app_with_tenant_endpoint):
        """Endpoints can retrieve tenant_id after auth."""
        app, private_key = app_with_tenant_endpoint
        payload = {
            "sub": "user999",
            "tenant_id": "org-123",
            "roles": ["admin"]
        }
        token = _create_token(payload, private_key)
        response = client.get("/tenant2", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["tenant_id"] == "org-123"
