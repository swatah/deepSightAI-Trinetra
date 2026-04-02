"""
AuthService - Authentication & Authorization Microservice

FastAPI application handling user registration, login, JWT issuance, and
authorization checks for multi-tenant ClipSight system.

RUN: uvicorn auth_service:app --host 0.0.0.0 --port 8000
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, create_engine
)
from sqlalchemy.ext.declarative import declarative_base
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
# Database Setup
# ============================================================================

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency for database session."""
    db = SessionLocal()
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


class UserRole(Base):
    """Junction: user_tenant <-> role."""
    __tablename__ = "user_roles"

    id = Column(Integer, primary_key=True, index=True)
    user_tenant_id = Column(Integer, ForeignKey("user_tenants.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow)


# Create tables if they don't exist (development only; use Alembic in production)
Base.metadata.create_all(bind=engine)


# ============================================================================
# Security Utilities
# ============================================================================

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


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
    id: int
    email: str
    full_name: str
    email_verified: bool

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: Optional[int] = None
    email: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


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


# TODO: Implement additional endpoints:
# - POST /auth/logout (token revocation)
# - POST /auth/password-reset
# - POST /auth/refresh (refresh tokens)
# - GET /auth/me (user profile)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
