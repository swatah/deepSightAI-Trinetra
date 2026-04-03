"""
T1.2.4: JWT validation middleware & T1.5.3: Audit middleware

Provides `require_auth` dependency for FastAPI endpoints to enforce
JWT authentication using RS256. Validates signature and expiration.

Also extracts tenant_id and sets request.state.tenant_id.

Additionally provides `AuditMiddleware` to automatically log all API requests.
"""

from fastapi import Request, HTTPException, Depends
from starlette.middleware.base import BaseHTTPMiddleware
from jose import jwt, JWTError
from typing import Dict, Any, Optional, Callable
import os
import time
import uuid
from datetime import datetime

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


class AuditMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware to automatically log all API requests to AuditService.

    On each request, constructs an audit log entry and sends it asynchronously
    to the audit log system (via AuditService or Kafka).

    Attributes:
        audit_service: An AuditService instance or mock with handle_log method.
        include_ip: Whether to include client IP address.
        skip_paths: List of path prefixes to skip logging (e.g., /health).
    """

    def __init__(
        self,
        app,
        audit_service: Any,
        include_ip: bool = True,
        skip_paths: Optional[list] = None,
    ):
        super().__init__(app)
        self.audit_service = audit_service
        self.include_ip = include_ip
        self.skip_paths = skip_paths or []

    async def dispatch(self, request: Request, call_next: Callable):
        # Skip logging for certain paths
        for skip in self.skip_paths:
            if request.url.path.startswith(skip):
                return await call_next(request)

        start_time = time.time()
        # Generate a request ID for correlation
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Extract basic request info (common for success and failure)
        method = request.method
        path = request.url.path
        user_agent = request.headers.get("user-agent")
        # Get user info from request state (might be set by auth middleware)
        tenant_id = getattr(request.state, "tenant_id", None)
        user_obj = getattr(request.state, "user", {})
        user_id = user_obj.get("sub") if isinstance(user_obj, dict) else None

        # Track whether an exception occurred
        exception_occurred = False
        error_message = None
        status_code = 500  # default for exceptions

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            exception_occurred = True
            error_message = str(exc)
            # Create a plain response to return? No, re-raise after logging
            # We'll log and then re-raise to allow FastAPI exception handlers to handle
        finally:
            elapsed = time.time() - start_time
            # Determine outcome
            if exception_occurred:
                outcome = "FAILURE"
                status = 500
            else:
                if 200 <= status_code < 400:
                    outcome = "SUCCESS"
                    status = status_code
                else:
                    outcome = "FAILURE"
                    status = status_code

            # Build audit log entry
            log_entry = {
                "tenant_id": tenant_id or "anonymous",
                "user_id": user_id or "anonymous",
                "action": self._map_method_to_action(method, path, status),
                "resource": {
                    "type": "api_endpoint",
                    "id": path,
                    "name": f"{method} {path}"
                },
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "outcome": outcome,
                "metadata": {
                    "http_status": status,
                    "elapsed_ms": int(elapsed * 1000),
                    "request_id": request_id,
                }
            }

            if self.include_ip:
                ip = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip") or (request.client.host if request.client else None)
                log_entry["ip_address"] = ip

            if user_agent:
                log_entry["user_agent"] = user_agent

            if error_message:
                log_entry["metadata"]["error_message"] = error_message

            # Send to audit service (fire-and-forget, but best effort)
            try:
                self.audit_service.handle_log(log_entry)
            except Exception as e:
                import logging
                logging.getLogger("audit_middleware").error(f"Failed to audit log: {e}")

        # If an exception was raised, re-raise after logging
        if exception_occurred:
            raise

        return response

    def _map_method_to_action(self, method: str, path: str, status_code: int) -> str:
        """Map HTTP method to audit action type."""
        method = method.upper()
        if method == "GET":
            return "READ"
        elif method == "POST":
            return "CREATE"
        elif method == "PUT" or method == "PATCH":
            return "UPDATE"
        elif method == "DELETE":
            return "DELETE"
        else:
            return "ACCESS"
