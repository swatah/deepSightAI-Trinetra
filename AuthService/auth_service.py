"""
AuthService - Authentication & Authorization Microservice

FastAPI application handling user registration, login, JWT issuance, and
authorization checks for multi-tenant ClipSight system.

RUN: uvicorn auth_service:app --host 0.0.0.0 --port 8000
"""

import os
import json
import secrets
import string
import hashlib
import httpx
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Request, status, BackgroundTasks
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

from passlib.context import CryptContext
from jose import jwt, JWTError
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

# ============================================================================
# Configuration
# ============================================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:devpassword@localhost:5432/clipsight"
)

# JWT Configuration - RS256 (asymmetric) for better security
# In production, load from files: /run/secrets/jwt-private-key, /run/secrets/jwt-public-key
ALGORITHM = "RS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Generate RSA key pair for development (in production, load from secure storage)
def _generate_rsa_keys():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    # Serialize to PEM format for python-jose compatibility
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private_pem, public_pem

PRIVATE_KEY, PUBLIC_KEY = _generate_rsa_keys()

# ============================================================================
# OAuth2 Configuration (Social Login - optional)
# ============================================================================
oauth_clients = {
    "google": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", "test-google-client"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", "test-google-secret"),
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile"
    },
    "github": {
        "client_id": os.getenv("GITHUB_CLIENT_ID", "test-github-client"),
        "client_secret": os.getenv("GITHUB_CLIENT_SECRET", "test-github-secret"),
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "read:user user:email"
    }
}

# Placeholder for mock provider (used in tests)
mock_provider = None

# ============================================================================
# Database Setup
# ============================================================================

Base = declarative_base()

# Engine and SessionLocal will be initialized lazily on first use
_engine = None
_SessionLocal = None


def init_db(database_url=None):
    """Initialize database engine and session factory. Called explicitly in production, or by tests to override."""
    global _engine, _SessionLocal
    url = database_url or DATABASE_URL
    _engine = create_engine(url)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    # Create tables (development only; use Alembic in production)
    Base.metadata.create_all(bind=_engine)


def get_db():
    """Dependency for database session."""
    if _SessionLocal is None:
        # Auto-initialize with default DATABASE_URL if not explicitly initialized
        init_db()
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# SQLAlchemy Models
# ============================================================================

class User(Base):
    """User account table."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    email_verified = Column(Boolean, default=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    avatar_url = Column(String, nullable=True)
    mfa_enabled = Column(Boolean, default=False)
    mfa_secret = Column(String, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Tenant(Base):
    """Tenant/organization table."""
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    description = Column(String, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserTenant(Base):
    """Junction: user <-> tenant membership."""
    __tablename__ = "user_tenants"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), default="active")
    joined_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User")
    tenant = relationship("Tenant")


class Role(Base):
    """Role definitions within a tenant."""
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(50), nullable=False)
    description = Column(String, nullable=True)
    permissions = Column(String)  # JSON array as comma-separated or JSON string
    system_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class APIKey(Base):
    """API keys for programmatic access."""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    prefix = Column(String(12), unique=True, nullable=False)  # e.g., 'clp_live_xxx'
    key_hash = Column(String(255), nullable=False)  # Argon2id hash of full key
    name = Column(String(100), nullable=False)
    permissions = Column(String)  # JSON array string
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User")
    tenant = relationship("Tenant")


class UserRole(Base):
    """Junction: user_tenant <-> role."""
    __tablename__ = "user_roles"

    id = Column(Integer, primary_key=True, index=True)
    user_tenant_id = Column(Integer, ForeignKey("user_tenants.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow)


class PasswordResetToken(Base):
    """Password reset tokens for user-initiated password changes."""
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), nullable=False)  # SHA256 hash of the plain token
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================================
# Security Utilities
# ============================================================================

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# OAuth2 configuration (optional - for social login)
# Use environment variables in production: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, etc.
OAUTH_CLIENTS = {
    "google": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", "test-google-client"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", "test-google-secret"),
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile"
    },
    "github": {
        "client_id": os.getenv("GITHUB_CLIENT_ID", "test-github-client"),
        "client_secret": os.getenv("GITHUB_CLIENT_SECRET", "test-github-secret"),
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "read:user user:email"
    }
}

# Placeholder for mock provider (used in tests)
mock_provider = None


class EmailSender:
    """Email sender abstraction. Override for testing."""
    def send_password_reset_email(self, to_email: str, reset_token: str):
        """Send a password reset email. In production, implement actual email sending."""
        # For development, log to console.
        print(f"[Email] Password reset link for {to_email}: token={reset_token}")


# Global email sender instance (can be overridden in tests)
email_sender = EmailSender()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password using Argon2id."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token signed with RS256."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    return jwt.encode(to_encode, PRIVATE_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate JWT using public key. Returns payload or None."""
    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# ============================================================================
# Pydantic Schemas
# ============================================================================

class UserCreate(BaseModel):
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="Plain password")
    full_name: str = Field(..., description="User's full name")


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    email_verified: bool


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: Optional[int] = None
    email: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Label for the API key")
    permissions: List[str] = Field(default=[], description="Permissions granted to this key")
    expires_in_days: int = Field(default=365, ge=1, le=3650, description="Expiration period in days")


class APIKeyResponse(BaseModel):
    id: int
    prefix: str
    key: str  # full key, shown only once
    name: str
    permissions: List[str]
    expires_at: datetime


class PasswordResetRequest(BaseModel):
    email: EmailStr = Field(..., description="Email address of the account to reset")


class PasswordResetConfirm(BaseModel):
    token: str = Field(..., description="Password reset token")
    new_password: str = Field(..., min_length=8, description="New password")


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="AuthService",
    description="Authentication & Authorization service for ClipSight",
    version="0.1.0"
)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/auth/register", response_model=Token)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """
    Register a new user account.

    - Validates email uniqueness
    - Hashes password with Argon2id
    - Creates user in database
    - Returns JWT access token

    """
    # Check for existing user
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create new user
    user = User(
        email=user_data.email,
        full_name=user_data.full_name,
        password_hash=get_password_hash(user_data.password),
        email_verified=False,
        last_login_at=None
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Issue JWT with tenant_id=None, roles=[] (user will join tenant separately)
    token = create_access_token(data={
        "sub": str(user.id),
        "email": user.email,
        "tenant_id": None,
        "roles": []
    })

    return Token(access_token=token, token_type="bearer")


@app.post("/auth/login", response_model=Token)
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate user and return JWT with tenant context and roles.

    Validates email/password, updates last_login_at, issues token.
    Includes: sub, email, tenant_id (if any), roles (list), exp, iat.
    """
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login
    user.last_login_at = datetime.utcnow()
    db.commit()

    # Get user's tenant(s) and roles
    # For simplicity, take first active tenant membership
    user_tenant = (
        db.query(UserTenant)
        .filter(UserTenant.user_id == user.id, UserTenant.status == "active")
        .first()
    )

    tenant_id = None
    roles = []

    if user_tenant:
        tenant_id = user_tenant.tenant_id
        # Fetch role names for this user in this tenant
        user_roles = (
            db.query(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .filter(UserRole.user_tenant_id == user_tenant.id)
            .all()
        )
        roles = [r[0] for r in user_roles]

    # Build token payload with required claims
    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "tenant_id": tenant_id,
        "roles": roles,
    }

    token = create_access_token(data=token_data)
    return Token(access_token=token, token_type="bearer")


def get_current_user(request: Request) -> dict:
    """
    Dependency to extract and verify JWT from Authorization header.
    Reuses decode_token to validate signature and expiration.
    Returns the decoded payload.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header"
        )
    token = auth_header.split(" ", 1)[1].strip()
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    return payload


@app.post("/auth/api-keys", response_model=APIKeyResponse)
def create_api_key(
    data: APIKeyCreate,
    payload: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate a new API key for the authenticated user's tenant.

    - User must be authenticated (JWT in Authorization header)
    - API key is scoped to the user's current tenant
    - Full key is returned once; only its hash is stored
    - Permissions restrict what the key can do (future)
    """
    user_id = int(payload["sub"])
    tenant_id = payload.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="User must belong to a tenant to create API keys")

    # Ensure user belongs to tenant (redundancy check)
    user_tenant = (
        db.query(UserTenant)
        .filter(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id, UserTenant.status == "active")
        .first()
    )
    if not user_tenant:
        raise HTTPException(status_code=400, detail="User is not an active member of the tenant")

    # Generate API key: prefix (8 chars) + suffix (32 hex)
    alphabet = string.ascii_letters + string.digits
    prefix = "cp_" + "".join(secrets.choice(alphabet) for _ in range(8))
    suffix = secrets.token_hex(16)  # 32 hex chars
    full_key = prefix + suffix

    # Hash the full key using Argon2id (same as passwords)
    key_hash = pwd_context.hash(full_key)

    # Compute expiration
    expires_at = datetime.utcnow() + timedelta(days=data.expires_in_days)

    # Store in database
    api_key = APIKey(
        tenant_id=tenant_id,
        user_id=user_id,
        prefix=prefix,
        key_hash=key_hash,
        name=data.name,
        permissions=json.dumps(data.permissions) if data.permissions else "[]",
        expires_at=expires_at,
        created_at=datetime.utcnow()
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return APIKeyResponse(
        id=api_key.id,
        prefix=prefix,
        key=full_key,  # return full key only once
        name=data.name,
        permissions=data.permissions,
        expires_at=expires_at
    )


@app.post("/auth/password-reset")
def request_password_reset(
    data: PasswordResetRequest,
    db: Session = Depends(get_db)
):
    """
    Initiate a password reset flow.

    - Looks up user by email.
    - If user exists, generates a one-time reset token and sends email.
    - Returns 200 regardless to avoid email enumeration (security).
    """
    # Look for user
    user = db.query(User).filter(User.email == data.email).first()
    if user:
        # Generate a random token
        plain_token = secrets.token_urlsafe(32)
        # Hash it with SHA256 for storage
        token_hash = hashlib.sha256(plain_token.encode()).hexdigest()
        # Create token record, expires in 1 hour
        expires = datetime.utcnow() + timedelta(hours=1)
        reset_token = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires,
            used_at=None
        )
        db.add(reset_token)
        db.commit()
        # Send email (could be background task to not block response)
        try:
            email_sender.send_password_reset_email(user.email, plain_token)
        except Exception as e:
            # Log but don't fail; user still gets success response
            print(f"Error sending password reset email: {e}")
    # Always return the same message regardless of user existence
    return {"message": "If an account exists with that email, a password reset email has been sent."}


@app.post("/auth/password-reset/confirm")
def confirm_password_reset(
    data: PasswordResetConfirm,
    db: Session = Depends(get_db)
):
    """
    Complete the password reset using the token sent via email.

    - Verifies the token matches a stored, unexpired, unused reset token.
    - If valid, updates the user's password.
    - Marks the token as used.
    """
    # Compute hash of provided token
    token_hash = hashlib.sha256(data.token.encode()).hexdigest()
    # Find a matching unused, non-expired token
    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > datetime.utcnow()
    ).first()
    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token"
        )
    # Get user
    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if not user:
        # This should not happen if referential integrity is enforced, but handle gracefully
        raise HTTPException(status_code=404, detail="User not found for reset token")
    # Update password
    user.password_hash = get_password_hash(data.new_password)
    # Mark token as used
    reset_token.used_at = datetime.utcnow()
    db.commit()
    return {"message": "Password has been reset successfully."}


# ============================================================================
# OAuth2 Social Login (Google, GitHub - optional)
# ============================================================================

@app.get("/auth/oauth/{provider}")
async def oauth_login(provider: str, request: Request):
    """
    Initiate OAuth2 flow by redirecting to the provider's authorization page.
    Supported providers: google, github.
    """
    if provider not in oauth_clients:
        raise HTTPException(status_code=404, detail=f"Unsupported OAuth provider: {provider}")
    config = oauth_clients[provider]
    state = secrets.token_urlsafe(16)
    redirect_uri = request.url_for("oauth_callback", provider=provider)
    params = {
        "client_id": config["client_id"],
        "redirect_uri": str(redirect_uri),
        "response_type": "code",
        "scope": config["scope"],
        "state": state,
        "access_type": "offline",
        "prompt": "consent"
    }
    auth_url = f"{config['auth_url']}?{urllib.parse.urlencode(params)}"
    if mock_provider is not None:
        auth_url = mock_provider.get_authorization_url(
            client_id=config["client_id"],
            redirect_uri=str(redirect_uri),
            state=state
        )
    return RedirectResponse(auth_url, status_code=302)


@app.get("/auth/oauth/{provider}/callback")
async def oauth_callback(provider: str, request: Request, db: Session = Depends(get_db)):
    """
    OAuth2 callback: exchange authorization code for tokens, fetch user info,
    create local user account if needed, and return a JWT.
    """
    if provider not in oauth_clients:
        raise HTTPException(status_code=404, detail=f"Unsupported OAuth provider: {provider}")
    config = oauth_clients[provider]
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code parameter")
    redirect_uri = request.url_for("oauth_callback", provider=provider)

    try:
        if mock_provider is not None:
            token_data = mock_provider.exchange_code_for_token(
                code=code,
                client_secret=config["client_secret"],
                redirect_uri=str(redirect_uri)
            )
            email = token_data.get("email")
            full_name = token_data.get("name")
        else:
            # Exchange code for access token with provider
            token_resp_data = {
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": str(redirect_uri)
            }
            headers = {"Accept": "application/json"}
            async with httpx.AsyncClient() as client:
                token_exchange = await client.post(config["token_url"], data=token_resp_data, headers=headers, timeout=30.0)
                if token_exchange.status_code != 200:
                    raise HTTPException(status_code=400, detail="OAuth token exchange failed")
                token_json = token_exchange.json()
                access_token = token_json.get("access_token")
                if not access_token:
                    raise HTTPException(status_code=400, detail="No access token returned")
                # Fetch user info from provider
                userinfo_resp = await client.get(
                    config["userinfo_url"],
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=30.0
                )
                if userinfo_resp.status_code != 200:
                    raise HTTPException(status_code=400, detail="Failed to fetch user info")
                userinfo = userinfo_resp.json()
                email = userinfo.get("email")
                full_name = userinfo.get("name") or userinfo.get("login")
                if not email:
                    raise HTTPException(status_code=400, detail="OAuth provider did not return an email")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth error: {str(e)}") from e

    # Find or create user
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            full_name=full_name or "OAuth User",
            password_hash=get_password_hash(secrets.token_urlsafe(32)),
            email_verified=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # Issue JWT
    token = create_access_token(data={
        "sub": str(user.id),
        "email": user.email,
        "tenant_id": None,
        "roles": []
    })
    return Token(access_token=token, token_type="bearer")


# TODO: Implement additional endpoints:
# - /auth/logout (token revocation)
# - /auth/refresh (refresh tokens)
# - /auth/me (user profile)


if __name__ == "__main__":
    # Initialize database when run as script (production/dev server)
    init_db()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
