"""
T1.2.4: JWT validation middleware

Provides `require_auth` dependency for FastAPI endpoints to enforce
JWT authentication using RS256. Validates signature and expiration.

Also extracts tenant_id and sets request.state.tenant_id.
"""

from fastapi import Request, HTTPException, Depends
from jose import jwt, JWTError
from typing import Dict, Any
import os

# Default algorithm
ALGORITHM = "RS256"

# Public key (can be set via set_jwt_public_key or loaded from env)
_PUBLIC_KEY = None


def set_jwt_public_key(public_key: bytes):
    """
    Set the RSA public key for JWT verification.
    This is mainly used for tests; in production, load from file/environment.
    """
    global _PUBLIC_KEY
    _PUBLIC_KEY = public_key


def _load_public_key() -> bytes:
    """
    Load public key for JWT verification.
    In production, read from file or environment variable.
    """
    global _PUBLIC_KEY
    if _PUBLIC_KEY is not None:
        return _PUBLIC_KEY

    # Try environment variable (path to PEM file)
    key_path = os.getenv("JWT_PUBLIC_KEY_PATH")
    if key_path and os.path.exists(key_path):
        with open(key_path, "rb") as f:
            _PUBLIC_KEY = f.read()
        return _PUBLIC_KEY

    # For development, fall back to AuthService's key if importable
    try:
        from AuthService.auth_service import PUBLIC_KEY as AUTH_PUBLIC_KEY
        _PUBLIC_KEY = AUTH_PUBLIC_KEY
        return _PUBLIC_KEY
    except ImportError:
        pass

    raise RuntimeError(
        "JWT public key not configured. Call set_jwt_public_key() or set JWT_PUBLIC_KEY_PATH."
    )


def require_auth(request: Request) -> Dict[str, Any]:
    """
    FastAPI dependency that validates JWT from Authorization header.
    Raises 401 if token is missing, invalid, or expired.
    On success, returns the decoded token payload and also sets:
        request.state.user = payload
        request.state.tenant_id = payload.get("tenant_id")
    """
    # Extract token from Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Expected: Bearer <token>"
        )

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")

    public_key = _load_public_key()

    try:
        payload = jwt.decode(token, public_key, algorithms=[ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

    # Attach to request state for downstream use
    request.state.user = payload
    request.state.tenant_id = payload.get("tenant_id")

    return payload


# Optional: convenience dependency that returns just tenant_id
def get_tenant_id(request: Request) -> Any:
    """
    Returns tenant_id from request.state. Assumes require_auth has already run.
    Use after require_auth in dependencies.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="tenant_id not available")
    return tenant_id
