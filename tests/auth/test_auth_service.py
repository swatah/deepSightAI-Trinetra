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

# Import the app and models from AuthService
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "AuthService"))

from auth_service import app, User, Base, get_db, create_access_token, pwd_context

# Use SQLite in-memory database for tests to avoid needing Postgres
SQLITE_TEST_DB = "sqlite:////tmp/test_clipsight.db"


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

        # Verify token is valid JWT (can decode)
        token = data["access_token"]
        from jose import jwt
        from auth_service import SECRET_KEY, ALGORITHM
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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
        from auth_service import SECRET_KEY, ALGORITHM
        payload = jwt.decode(data["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
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


# Helper function needed in test
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)
