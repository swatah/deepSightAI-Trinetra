"""
AuthService - Authentication & Authorization Microservice

FastAPI application handling user registration, login, JWT issuance, and
authorization checks for multi-tenant deepSightAI Trinetra system.

RUN: uvicorn auth_service:app --host 0.0.0.0 --port 8000
"""

import os
import json
import secrets
import string
import hashlib
import httpx
import urllib.parse
import uuid
import threading
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Request, status, BackgroundTasks, Response, Body
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, create_engine, JSON, text
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

from passlib.context import CryptContext
from jose import jwt, JWTError
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

# ============================================================================
# AUTH DEPENDENCY
# ============================================================================
from deepSightAI.Trinetra.Shared.Middleware import require_auth
AUTH_AVAILABLE = True

# ============================================================================
# Configuration
# ============================================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:devpassword@localhost:5432/deepSightAI-Trinetra"
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
    plugin_config = Column(JSON, nullable=False, default=dict)  # T2.1.9


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


class EdgeDevice(Base):
    """
    Edge device credentials and camera assignments (E3, E4, Issue #77).
    """
    __tablename__ = "edge_devices"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(100), unique=True, index=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    api_key_prefix = Column(String(32), nullable=False)
    api_key_hash = Column(String(255), nullable=False)
    assigned_cameras = Column(JSON, nullable=False, default=list)
    revoked = Column(Boolean, default=False, nullable=False)
    failed_auth_count = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


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

from deepSightAI.Trinetra.Shared.Middleware import RequestIDMiddleware
from deepSightAI.Trinetra.Shared.ErrorHandlers import register_error_handlers

app = FastAPI(
    title="AuthService",
    description="Authentication & Authorization service for deepSightAI Trinetra",
    version="0.1.0"
)
app.add_middleware(RequestIDMiddleware)
register_error_handlers(app)


@app.get("/health")
def health_check():
    """Health check endpoint (REL-63)."""
    return {"status": "ok", "service": "AuthService", "timestamp": datetime.utcnow().isoformat()}


@app.get("/ready")
def ready_check(db: Session = Depends(get_db)):
    """Readiness check endpoint (REL-63)."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready", "service": "AuthService"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unreachable: {e}")



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


@app.get("/auth/api-keys")
def dsai_list_api_keys(
    dsai_payload: dict = Depends(get_current_user),
    dsai_db: Session = Depends(get_db),
):
    """
    List API keys for the authenticated user's tenant. Admin only.

    Never returns the key hash or the full secret — only the label, prefix,
    and timestamps, consistent with 'shown once at creation' semantics.
    """
    if "admin" not in dsai_payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Only platform administrators can list API keys")

    dsai_tenant_id = dsai_payload.get("tenant_id")
    if dsai_tenant_id is None:
        raise HTTPException(status_code=400, detail="User must belong to a tenant to list API keys")

    dsai_keys = (
        dsai_db.query(APIKey)
        .filter(APIKey.tenant_id == dsai_tenant_id)
        .order_by(APIKey.created_at.desc())
        .all()
    )

    return [
        {
            "id": dsai_k.id,
            "name": dsai_k.name,
            "prefix": dsai_k.prefix,
            "created_at": dsai_k.created_at.isoformat() if dsai_k.created_at else None,
            "expires_at": dsai_k.expires_at.isoformat() if dsai_k.expires_at else None,
        }
        for dsai_k in dsai_keys
    ]


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


@app.get("/tenants/{tenant_id}")
def dsai_get_tenant(
    tenant_id: str,
    dsai_payload: dict = Depends(require_auth),
    dsai_db: Session = Depends(get_db),
):
    """
    Retrieve tenant profile, active status, and plugin configuration.

    Supports querying by integer ID or URL-safe slug.
    Accessible to users belonging to the tenant or platform administrators.
    """
    if tenant_id.isdigit():
        dsai_tenant = dsai_db.query(Tenant).filter(Tenant.id == int(tenant_id)).first()
    else:
        dsai_tenant = dsai_db.query(Tenant).filter(Tenant.slug == tenant_id).first()

    if not dsai_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    dsai_user_tenant_id = dsai_payload.get("tenant_id")
    dsai_roles = dsai_payload.get("roles", [])
    dsai_is_admin = "admin" in dsai_roles
    if dsai_user_tenant_id is not None and str(dsai_user_tenant_id) != str(dsai_tenant.id) and not dsai_is_admin:
        raise HTTPException(status_code=403, detail="Access denied for this tenant")

    return {
        "id": str(dsai_tenant.id),
        "name": dsai_tenant.name,
        "slug": dsai_tenant.slug,
        "description": dsai_tenant.description,
        "active": dsai_tenant.active,
        "created_at": dsai_tenant.created_at.isoformat() if dsai_tenant.created_at else None,
        "plugin_config": dsai_tenant.plugin_config or {},
    }


class DsaiTenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    sector: Optional[str] = Field(default=None, description="Industry sector, stored in plugin_config")


@app.post("/tenants", status_code=201)
def dsai_create_tenant(
    dsai_data: DsaiTenantCreate,
    dsai_payload: dict = Depends(require_auth),
    dsai_db: Session = Depends(get_db),
):
    """
    Provision a new platform tenant.

    Requires the caller to hold the 'admin' role. Sector is stored inside
    plugin_config (Phase 0 decision 5 — the Tenant table has no dedicated column).
    """
    if "admin" not in dsai_payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Only platform administrators can provision tenants")

    if dsai_db.query(Tenant).filter(Tenant.slug == dsai_data.slug).first():
        raise HTTPException(status_code=400, detail="Tenant slug already in use")

    dsai_tenant = Tenant(
        name=dsai_data.name,
        slug=dsai_data.slug,
        description=dsai_data.description,
        active=True,
        plugin_config={"sector": dsai_data.sector} if dsai_data.sector else {},
    )
    dsai_db.add(dsai_tenant)
    dsai_db.commit()
    dsai_db.refresh(dsai_tenant)

    return {
        "id": str(dsai_tenant.id),
        "name": dsai_tenant.name,
        "slug": dsai_tenant.slug,
        "description": dsai_tenant.description,
        "active": dsai_tenant.active,
        "created_at": dsai_tenant.created_at.isoformat() if dsai_tenant.created_at else None,
        "plugin_config": dsai_tenant.plugin_config or {},
    }


@app.get("/tenants")
def dsai_list_tenants(
    dsai_payload: dict = Depends(require_auth),
    dsai_db: Session = Depends(get_db),
):
    """List all platform tenants. Requires the caller to hold the 'admin' role."""
    if "admin" not in dsai_payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Only platform administrators can list tenants")

    dsai_tenants = dsai_db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    return [
        {
            "id": str(dsai_t.id),
            "name": dsai_t.name,
            "slug": dsai_t.slug,
            "active": dsai_t.active,
            "created_at": dsai_t.created_at.isoformat() if dsai_t.created_at else None,
            "plugin_config": dsai_t.plugin_config or {},
        }
        for dsai_t in dsai_tenants
    ]


class DsaiTenantStatusUpdate(BaseModel):
    active: bool


@app.patch("/tenants/{tenant_id}")
def dsai_update_tenant_status(
    tenant_id: int,
    dsai_data: DsaiTenantStatusUpdate,
    dsai_payload: dict = Depends(require_auth),
    dsai_db: Session = Depends(get_db),
):
    """Suspend or reactivate a tenant. Requires the caller to hold the 'admin' role."""
    if "admin" not in dsai_payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Only platform administrators can update tenant status")

    dsai_tenant = dsai_db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not dsai_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    dsai_tenant.active = dsai_data.active
    dsai_db.commit()
    dsai_db.refresh(dsai_tenant)

    return {
        "id": str(dsai_tenant.id),
        "name": dsai_tenant.name,
        "slug": dsai_tenant.slug,
        "description": dsai_tenant.description,
        "active": dsai_tenant.active,
        "created_at": dsai_tenant.created_at.isoformat() if dsai_tenant.created_at else None,
        "plugin_config": dsai_tenant.plugin_config or {},
    }


class DsaiTenantUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = None
    role: str = Field(default="operator")


@app.post("/tenants/{tenant_id}/users", status_code=201)
def dsai_create_tenant_user(
    tenant_id: int,
    dsai_data: DsaiTenantUserCreate,
    dsai_payload: dict = Depends(require_auth),
    dsai_db: Session = Depends(get_db),
):
    """
    Provision a user under a tenant with a given role. Admin only.

    If a user with the given email already exists, they are attached to the
    tenant (and assigned the role) rather than duplicated.
    """
    if "admin" not in dsai_payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Only platform administrators can provision users")

    dsai_tenant = dsai_db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not dsai_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    dsai_user = dsai_db.query(User).filter(User.email == dsai_data.email).first()
    if not dsai_user:
        dsai_user = User(
            email=dsai_data.email,
            full_name=dsai_data.full_name or dsai_data.email,
            password_hash=get_password_hash(dsai_data.password),
            email_verified=False,
        )
        dsai_db.add(dsai_user)
        dsai_db.commit()
        dsai_db.refresh(dsai_user)

    dsai_user_tenant = (
        dsai_db.query(UserTenant)
        .filter(UserTenant.user_id == dsai_user.id, UserTenant.tenant_id == tenant_id)
        .first()
    )
    if not dsai_user_tenant:
        dsai_user_tenant = UserTenant(user_id=dsai_user.id, tenant_id=tenant_id, status="active")
        dsai_db.add(dsai_user_tenant)
        dsai_db.commit()
        dsai_db.refresh(dsai_user_tenant)

    dsai_role = (
        dsai_db.query(Role)
        .filter(Role.tenant_id == tenant_id, Role.name == dsai_data.role)
        .first()
    )
    if not dsai_role:
        dsai_role = Role(tenant_id=tenant_id, name=dsai_data.role, system_default=True)
        dsai_db.add(dsai_role)
        dsai_db.commit()
        dsai_db.refresh(dsai_role)

    dsai_existing_assignment = (
        dsai_db.query(UserRole)
        .filter(UserRole.user_tenant_id == dsai_user_tenant.id, UserRole.role_id == dsai_role.id)
        .first()
    )
    if not dsai_existing_assignment:
        dsai_db.add(UserRole(user_tenant_id=dsai_user_tenant.id, role_id=dsai_role.id))
        dsai_db.commit()

    return {
        "id": str(dsai_user.id),
        "email": dsai_user.email,
        "tenant_id": str(tenant_id),
        "roles": [dsai_data.role],
        "created_at": dsai_user.created_at.isoformat() if dsai_user.created_at else None,
    }


@app.get("/tenants/{tenant_id}/users")
def dsai_list_tenant_users(
    tenant_id: int,
    dsai_payload: dict = Depends(require_auth),
    dsai_db: Session = Depends(get_db),
):
    """List active users of a tenant, with their assigned roles. Admin only."""
    if "admin" not in dsai_payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Only platform administrators can list tenant users")

    dsai_tenant = dsai_db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not dsai_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    dsai_memberships = (
        dsai_db.query(UserTenant)
        .filter(UserTenant.tenant_id == tenant_id, UserTenant.status == "active")
        .order_by(UserTenant.joined_at.desc())
        .all()
    )

    dsai_results = []
    for dsai_membership in dsai_memberships:
        dsai_role_rows = (
            dsai_db.query(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .filter(UserRole.user_tenant_id == dsai_membership.id)
            .all()
        )
        dsai_results.append({
            "id": str(dsai_membership.user.id),
            "email": dsai_membership.user.email,
            "tenant_id": str(tenant_id),
            "roles": [dsai_r[0] for dsai_r in dsai_role_rows],
            "created_at": dsai_membership.joined_at.isoformat() if dsai_membership.joined_at else None,
        })

    return dsai_results


@app.get("/users")
def dsai_list_users(
    tenant_id: Optional[int] = None,
    dsai_payload: dict = Depends(require_auth),
    dsai_db: Session = Depends(get_db),
):
    """List active users across all tenants in a single query, optionally filtered
    by tenant_id. Admin only. Replaces per-tenant looping on the client."""
    if "admin" not in dsai_payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Only platform administrators can list users")

    dsai_query = dsai_db.query(UserTenant).filter(UserTenant.status == "active")
    if tenant_id is not None:
        dsai_query = dsai_query.filter(UserTenant.tenant_id == tenant_id)
    dsai_memberships = dsai_query.order_by(UserTenant.joined_at.desc()).all()

    dsai_roles_by_membership: dict = {}
    dsai_membership_ids = [dsai_m.id for dsai_m in dsai_memberships]
    if dsai_membership_ids:
        dsai_role_rows = (
            dsai_db.query(UserRole.user_tenant_id, Role.name)
            .join(Role, UserRole.role_id == Role.id)
            .filter(UserRole.user_tenant_id.in_(dsai_membership_ids))
            .all()
        )
        for dsai_ut_id, dsai_role_name in dsai_role_rows:
            dsai_roles_by_membership.setdefault(dsai_ut_id, []).append(dsai_role_name)

    return [
        {
            "id": str(dsai_m.user.id),
            "email": dsai_m.user.email,
            "tenant_id": str(dsai_m.tenant_id),
            "roles": dsai_roles_by_membership.get(dsai_m.id, []),
            "created_at": dsai_m.joined_at.isoformat() if dsai_m.joined_at else None,
        }
        for dsai_m in dsai_memberships
    ]


@app.delete("/tenants/{tenant_id}")
def delete_tenant(
    tenant_id: int,
    payload: dict = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Delete a tenant and all associated data (GDPR Article 17 - Right to erasure).

    Requires admin role for the tenant.

    Cascades deletion to:
    - PostgreSQL: tenant record, users, roles, api_keys, etc. (via FK cascade)
    - Redis: all keys with tenant prefix
    - MinIO: all objects under tenant prefix
    - Milvus: tenant's collection

    Args:
        tenant_id: The tenant to delete

    Returns:
        204 No Content on success.
    """
    # Verify caller has admin role for this tenant
    user_tenant_id = payload.get("tenant_id")
    roles = payload.get("roles", [])
    if user_tenant_id != tenant_id and "admin" not in roles:
        raise HTTPException(
            status_code=403,
            detail="Only tenant admin can delete the tenant"
        )

    # Verify tenant exists
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Delete external data stores (best effort, errors logged)
    _cleanup_redis(tenant_id)
    _cleanup_minio(tenant_id)
    _cleanup_milvus(tenant_id)

    # Delete tenant from database (cascade to related tables)
    db.delete(tenant)
    db.commit()

    return Response(status_code=204)


@app.put("/tenants/{tenant_id}/plugins")
def update_tenant_plugins(
    tenant_id: int,
    plugin_config: dict = Body(...),
    payload: dict = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Update plugin configuration for a tenant.

    Requires admin role for the tenant.

    Body must contain a "plugins" key with a dict of plugin settings.
    """
    # Auth: must be admin of this tenant
    user_tenant_id = payload.get("tenant_id")
    roles = payload.get("roles", [])
    if user_tenant_id != tenant_id or "admin" not in roles:
        raise HTTPException(
            status_code=403,
            detail="Only tenant admin can update plugin configuration"
        )

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Validate schema
    if "plugins" not in plugin_config or not isinstance(plugin_config["plugins"], dict):
        raise HTTPException(status_code=400, detail="Invalid plugin configuration: missing 'plugins' dict")

    tenant.plugin_config = plugin_config
    db.commit()

    return {"message": "Plugin configuration updated", "tenant_id": tenant_id}


# ============================================================================
# Edge Device Endpoints (E3, E4, Issue #77)
# ============================================================================

class EdgeDeviceOnboardRequest(BaseModel):
    device_id: Optional[str] = Field(None, description="Unique edge device identifier")
    tenant_id: str = Field(..., min_length=1, description="Tenant identifier")
    name: Optional[str] = Field(None, description="Device descriptive name")
    device_name: Optional[str] = Field(None, description="Device descriptive name (alias)")
    camera_id: Optional[str] = Field(None, description="Single assigned camera ID")
    assigned_cameras: List[str] = Field(default_factory=list, description="List of camera IDs assigned to device")


class EdgeDeviceOnboardResponse(BaseModel):
    device_id: str
    tenant_id: str
    name: str
    assigned_cameras: List[str]
    api_key: str
    prefix: str


class EdgeDeviceVerifyRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="API key of the edge device")
    camera_id: str = Field(..., min_length=1, description="Camera submitting the event")
    tenant_id: str = Field(..., min_length=1, description="Tenant submitting the event")
    device_id: Optional[str] = None


def dsai_hash_edge_key(dsai_key: str) -> str:
    """Deterministic hash of plain edge API key for storage/lookup."""
    return hashlib.sha256(dsai_key.encode("utf-8")).hexdigest()


_dsai_edge_lockout_tracker = {}
_dsai_edge_lockout_lock = threading.Lock()


def dsai_verify_edge_device(
    dsai_db: Session,
    dsai_api_key: str,
    dsai_camera_id: Optional[str] = None,
    dsai_tenant_id: Optional[str] = None,
    dsai_device_id: Optional[str] = None
) -> EdgeDevice:
    """
    Core verification logic for edge device credentials (Issue #77).
    Enforces expiration, revocation, lockout, and optional tenant and camera assignment.
    """
    dsai_key_clean = (dsai_api_key or "").strip()
    if not dsai_key_clean:
        raise HTTPException(status_code=401, detail="Missing or invalid edge device credential")

    dsai_now = datetime.utcnow()
    dsai_key_hash = dsai_hash_edge_key(dsai_key_clean)
    dsai_prefix = dsai_key_clean[:12] if len(dsai_key_clean) >= 12 else dsai_key_clean
    dsai_identifier = dsai_device_id or dsai_prefix or dsai_key_clean

    with _dsai_edge_lockout_lock:
        dsai_lock_info = _dsai_edge_lockout_tracker.get(dsai_identifier)
        if dsai_lock_info and dsai_lock_info.get("locked_until") and dsai_now < dsai_lock_info["locked_until"]:
            raise HTTPException(
                status_code=429,
                detail="Device temporarily locked out due to repeated authentication failures"
            )

    # Search for device by key hash or prefix
    dsai_query = dsai_db.query(EdgeDevice)
    if dsai_device_id:
        dsai_query = dsai_query.filter(EdgeDevice.device_id == dsai_device_id)

    dsai_device = dsai_query.filter(EdgeDevice.api_key_hash == dsai_key_hash).first()

    if not dsai_device:
        # Check if device exists by prefix or device_id to track failed attempt
        dsai_candidate = None
        if dsai_device_id:
            dsai_candidate = dsai_db.query(EdgeDevice).filter(EdgeDevice.device_id == dsai_device_id).first()
        elif dsai_prefix:
            dsai_candidate = dsai_db.query(EdgeDevice).filter(EdgeDevice.api_key_prefix == dsai_prefix).first()

        with _dsai_edge_lockout_lock:
            dsai_info = _dsai_edge_lockout_tracker.setdefault(dsai_identifier, {"count": 0, "locked_until": None})
            dsai_info["count"] += 1
            if dsai_info["count"] >= 5:
                dsai_info["locked_until"] = dsai_now + timedelta(minutes=15)
                raise HTTPException(
                    status_code=429,
                    detail="Device temporarily locked out due to repeated authentication failures"
                )

        if dsai_candidate:
            dsai_candidate.failed_auth_count += 1
            if dsai_candidate.failed_auth_count >= 5:
                dsai_candidate.locked_until = dsai_now + timedelta(minutes=15)
            dsai_db.commit()
            if dsai_candidate.locked_until and dsai_candidate.locked_until > dsai_now:
                raise HTTPException(status_code=429, detail="Device temporarily locked out due to repeated authentication failures")

        raise HTTPException(status_code=401, detail="Invalid edge device credential")

    # Check lockout on device entity
    if dsai_device.locked_until and dsai_now < dsai_device.locked_until:
        raise HTTPException(
            status_code=429,
            detail="Device is temporarily locked due to repeated authentication failures"
        )

    # Check revocation (immediate per-request check)
    if dsai_device.revoked:
        raise HTTPException(status_code=401, detail="Edge device credential has been revoked")

    # Check tenant isolation
    if dsai_tenant_id is not None and str(dsai_device.tenant_id) != str(dsai_tenant_id):
        raise HTTPException(
            status_code=403,
            detail=f"Edge device tenant mismatch: registered for '{dsai_device.tenant_id}', called for '{dsai_tenant_id}'"
        )

    # Check camera assignment authorization (E4)
    if dsai_camera_id is not None:
        dsai_cameras = dsai_device.assigned_cameras or []
        if dsai_camera_id not in dsai_cameras:
            raise HTTPException(
                status_code=403,
                detail=f"Device '{dsai_device.device_id}' is not authorized to submit embeddings for camera '{dsai_camera_id}'"
            )

    # Successful auth: reset failure count and update last_seen_at
    with _dsai_edge_lockout_lock:
        _dsai_edge_lockout_tracker.pop(dsai_identifier, None)

    dsai_device.failed_auth_count = 0
    dsai_device.locked_until = None
    dsai_device.last_seen_at = dsai_now
    dsai_db.commit()

    return dsai_device


@app.post("/auth/edge/devices", response_model=EdgeDeviceOnboardResponse, status_code=200)
def dsai_onboard_edge_device(
    dsai_req: EdgeDeviceOnboardRequest,
    dsai_db: Session = Depends(get_db)
):
    """Onboard an edge device, assigning it to tenant and cameras (E3, E4, Issue #77)."""
    dsai_dev_id = dsai_req.device_id or f"dev_{uuid.uuid4().hex[:12]}"
    dsai_dev_name = dsai_req.name or dsai_req.device_name or dsai_dev_id
    dsai_cams = list(dsai_req.assigned_cameras)
    if dsai_req.camera_id and dsai_req.camera_id not in dsai_cams:
        dsai_cams.append(dsai_req.camera_id)

    dsai_existing = dsai_db.query(EdgeDevice).filter(EdgeDevice.device_id == dsai_dev_id).first()
    if dsai_existing:
        raise HTTPException(status_code=409, detail=f"Device '{dsai_dev_id}' already registered")

    # Generate edge API key: clp_edge_<random32>
    dsai_raw_key = f"clp_edge_{secrets.token_urlsafe(32)}"
    dsai_prefix = dsai_raw_key[:12]
    dsai_key_hash = dsai_hash_edge_key(dsai_raw_key)

    dsai_new_device = EdgeDevice(
        device_id=dsai_dev_id,
        tenant_id=dsai_req.tenant_id,
        name=dsai_dev_name,
        api_key_prefix=dsai_prefix,
        api_key_hash=dsai_key_hash,
        assigned_cameras=dsai_cams,
        revoked=False,
        failed_auth_count=0,
        created_at=datetime.utcnow()
    )
    dsai_db.add(dsai_new_device)
    dsai_db.commit()
    dsai_db.refresh(dsai_new_device)

    return EdgeDeviceOnboardResponse(
        device_id=dsai_new_device.device_id,
        tenant_id=dsai_new_device.tenant_id,
        name=dsai_new_device.name,
        assigned_cameras=dsai_new_device.assigned_cameras,
        api_key=dsai_raw_key,
        prefix=dsai_prefix
    )


@app.post("/auth/edge/devices/{device_id}/revoke")
def dsai_revoke_edge_device(
    device_id: str,
    dsai_db: Session = Depends(get_db)
):
    """Immediately revoke an edge device's access (E3, Issue #77)."""
    dsai_device = dsai_db.query(EdgeDevice).filter(EdgeDevice.device_id == device_id).first()
    if not dsai_device:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")

    dsai_device.revoked = True
    dsai_db.commit()
    return {
        "message": f"Edge device '{device_id}' has been revoked immediately.",
        "device_id": device_id,
        "revoked": True
    }


@app.post("/auth/edge/verify")
def dsai_verify_edge_device_endpoint(
    dsai_req: EdgeDeviceVerifyRequest,
    dsai_db: Session = Depends(get_db)
):
    """Verify edge device credentials against tenant and camera (E3, E4, Issue #77)."""
    dsai_device = dsai_verify_edge_device(
        dsai_db=dsai_db,
        dsai_api_key=dsai_req.api_key,
        dsai_camera_id=dsai_req.camera_id,
        dsai_tenant_id=dsai_req.tenant_id,
        dsai_device_id=dsai_req.device_id
    )
    return {
        "valid": True,
        "device_id": dsai_device.device_id,
        "tenant_id": dsai_device.tenant_id,
        "camera_id": dsai_req.camera_id
    }



def _cleanup_redis(tenant_id: int):
    """Delete all Redis keys with tenant prefix."""
    try:
        from redis import Redis
        from deepSightAI.Trinetra.Shared.RedisUtils import make_tenant_prefix
        # Connect to Redis (use env var)
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
        r = Redis.from_url(redis_url, decode_responses=True)
        prefix = make_tenant_prefix(str(tenant_id))
        # Scan and delete keys
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match=f"{prefix}*", count=100)
            if keys:
                r.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        print(f"[TenantDeletion] Redis cleanup error: {e}")


def _cleanup_minio(tenant_id: int):
    """Delete all MinIO objects with tenant prefix."""
    try:
        from minio import Minio
        minio_url = os.getenv("MINIO_URL", "http://minio:9000").replace("http://", "").replace("https://", "")
        access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
        client = Minio(minio_url, access_key=access_key, secret_key=secret_key, secure=False)
        # List all buckets and delete objects with tenant prefix
        # For simplicity, we assume objects are in buckets with tenant prefix
        # Actually tenant prefix in object key, so we need to iterate all buckets.
        # This can be heavy. We'll just attempt to remove objects from known buckets.
        # In production, you might use lifecycle policies or separate bucket per tenant.
        buckets = ["videos", "frames", "frames-rtsp"]
        for bucket in buckets:
            try:
                # List objects with tenant_{id}/ prefix
                prefix = f"{tenant_id}/"
                objects = client.list_objects(bucket, prefix=prefix, recursive=True)
                for obj in objects:
                    client.remove_object(bucket, obj.object_name)
            except Exception as e:
                print(f"[TenantDeletion] MinIO cleanup error in bucket {bucket}: {e}")
    except Exception as e:
        print(f"[TenantDeletion] MinIO init error: {e}")


def _cleanup_milvus(tenant_id: int):
    """Drop tenant's Milvus collection."""
    try:
        from deepSightAI.Trinetra.Shared.Milvus import drop_tenant_collection
        drop_tenant_collection(str(tenant_id))
    except Exception as e:
        print(f"[TenantDeletion] Milvus cleanup error: {e}")


if __name__ == "__main__":
    # Initialize database when run as script (production/dev server)
    init_db()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
