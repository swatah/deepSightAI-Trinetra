"""
T1.2.9: Password reset flow (email)

Tests the POST /auth/password-reset endpoint which initiates a password reset
by sending an email with a reset token. The email sending is mocked in tests.
Also tests the confirmation endpoint to reset the password with the token.
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

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "AuthService"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

SQLITE_DB = "sqlite:////tmp/test_password_reset.db"


class MockEmailSender:
    """Mock email sender to capture emails in tests."""
    def __init__(self):
        self.sent_emails = []

    def send_password_reset_email(self, to_email: str, reset_token: str):
        self.sent_emails.append({
            "to": to_email,
            "reset_token": reset_token
        })


@pytest.fixture(scope="function")
def test_db(tmp_path):
    """Setup test database with tables."""
    db_file = tmp_path / "test_password_reset.db"
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


@pytest.fixture
def mock_email():
    """Replace the email sender with a mock."""
    from auth_service import email_sender
    original = email_sender
    mock = MockEmailSender()
    # Temporarily replace the sender in the module
    import auth_service
    auth_service.email_sender = mock
    yield mock
    # Restore
    auth_service.email_sender = original


class TestPasswordReset:
    """Test suite for password reset flow."""

    def test_request_password_reset_sends_email_if_user_exists(self, client, test_db, mock_email):
        """POST /auth/password-reset should send email with reset token for existing user."""
        # Create a user in the database
        from auth_service import User, get_password_hash
        db = test_db()
        user = User(
            email="resetrequest@example.com",
            full_name="Reset User",
            password_hash=get_password_hash("OldPass123!"),
            email_verified=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
        db.close()

        # Request password reset
        response = client.post("/auth/password-reset", json={"email": "resetrequest@example.com"})
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        assert "message" in data
        # Check that an email was "sent"
        assert len(mock_email.sent_emails) == 1
        sent = mock_email.sent_emails[0]
        assert sent["to"] == "resetrequest@example.com"
        assert "reset_token" in sent
        # The reset token should be a JWT or random string. We'll verify it's usable.
        reset_token = sent["reset_token"]

        # Verify token can be used to reset password
        new_password = "NewSecurePass123!"
        confirm_response = client.post(
            "/auth/password-reset/confirm",
            json={"token": reset_token, "new_password": new_password}
        )
        assert confirm_response.status_code == 200, f"Confirm failed: {confirm_response.text}"

        # Verify password was changed
        db = test_db()
        updated_user = db.query(User).filter(User.id == user_id).first()
        assert updated_user is not None
        from passlib.context import CryptContext
        pwd_ctx = CryptContext(schemes=["argon2"], deprecated="auto")
        assert pwd_ctx.verify(new_password, updated_user.password_hash)
        # Old password should no longer match
        assert not pwd_ctx.verify("OldPass123!", updated_user.password_hash)
        db.close()

    def test_request_password_reset_for_nonexistent_user_still_returns_200(self, client, mock_email):
        """Password reset request should return 200 even if email not registered (security)."""
        response = client.post("/auth/password-reset", json={"email": "notfound@example.com"})
        assert response.status_code == 200
        # No email should be sent
        assert len(mock_email.sent_emails) == 0

    def test_password_reset_confirm_fails_with_invalid_token(self, client, test_db):
        """Confirming with an invalid or expired token should fail."""
        # Invalid token
        response = client.post(
            "/auth/password-reset/confirm",
            json={"token": "invalid-token", "new_password": "NewPass123!"}
        )
        assert response.status_code == 400
        # Possibly detail indicates invalid token

    def test_password_reset_confirm_requires_new_password(self, client):
        """Confirm must include a new password."""
        response = client.post(
            "/auth/password-reset/confirm",
            json={"token": "some-token"}
        )
        assert response.status_code == 422  # Unprocessable entity (validation error)

    def test_password_reset_email_contains_usable_link(self, client, test_db, mock_email):
        """The reset email should contain a token that can redeem for password change."""
        # Create user
        from auth_service import User, get_password_hash
        db = test_db()
        user = User(
            email="linktest@example.com",
            full_name="Link Test",
            password_hash=get_password_hash("Original123!"),
            email_verified=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.close()

        # Request reset
        response = client.post("/auth/password-reset", json={"email": "linktest@example.com"})
        assert response.status_code == 200
        assert len(mock_email.sent_emails) == 1
        token = mock_email.sent_emails[0]["reset_token"]

        # Confirm with token and new password
        new_pass = "NewPass!456"
        confirm = client.post(
            "/auth/password-reset/confirm",
            json={"token": token, "new_password": new_pass}
        )
        assert confirm.status_code == 200

        # Verify password changed
        db = test_db()
        user = db.query(User).filter(User.id == user.id).first()
        from passlib.context import CryptContext
        pwd_ctx = CryptContext(schemes=["argon2"], deprecated="auto")
        assert pwd_ctx.verify(new_pass, user.password_hash)
        db.close()
