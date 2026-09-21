"""
Authentication, Authorization, Correlation, and Audit Middleware (REL-54, AUTH-46).

Provides:
- dsai_require_auth: FastAPI dependency validating RS256 JWT tokens.
- dsai_request_id_middleware: Middleware extracting/propagating X-Request-ID headers.
- dsai_audit_middleware: Middleware logging API requests to AuditService.
"""

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable, List

from fastapi import Request, HTTPException, Depends
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from jose import jwt, JWTError

from deepSightAI.Trinetra.Shared.LoggingSetup import dsai_get_logger
from deepSightAI.Trinetra.Shared.dsai_errors import AuthenticationError, PermissionDeniedError

dsai_logger = dsai_get_logger("deepSightAI.Trinetra.Shared.Middleware")

DSAI_ALGORITHM = "RS256"
_dsai_public_key = None

DSAI_PROBE_PATHS = {
    "/health",
    "/ready",
    "/healthz",
    "/readyz",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
}


def dsai_set_jwt_public_key(dsai_public_key_bytes: bytes) -> None:
    """Set the RSA public key for JWT verification (used in testing and dynamic key configuration)."""
    global _dsai_public_key
    _dsai_public_key = dsai_public_key_bytes


def dsai_load_public_key() -> bytes:
    """Load the RSA public key for JWT verification from file or environment variable."""
    global _dsai_public_key
    if _dsai_public_key is not None:
        return _dsai_public_key

    dsai_key_path = os.getenv("JWT_PUBLIC_KEY_PATH")
    if dsai_key_path and os.path.exists(dsai_key_path):
        with open(dsai_key_path, "rb") as dsai_f:
            _dsai_public_key = dsai_f.read()
        return _dsai_public_key

    try:
        from deepSightAI.Trinetra.AuthService.auth_service import PUBLIC_KEY as DSAI_AUTH_PUBLIC_KEY
        _dsai_public_key = DSAI_AUTH_PUBLIC_KEY
        return _dsai_public_key
    except ImportError:
        pass

    raise RuntimeError(
        "JWT public key not configured. Call dsai_set_jwt_public_key() or set JWT_PUBLIC_KEY_PATH."
    )


def dsai_require_auth(dsai_request: Request) -> Dict[str, Any]:
    """
    FastAPI dependency that validates JWT from Authorization header (AUTH-46).
    Raises 401 HTTPException if token is missing, invalid, or expired.
    Permits unauthenticated access only to health/ready/metrics probe paths.
    Sets:
        dsai_request.state.user = payload
        dsai_request.state.tenant_id = payload.get("tenant_id")
    """
    # Allow probe and documentation endpoints without auth
    if dsai_request.url.path in DSAI_PROBE_PATHS:
        return {}

    dsai_auth_header = dsai_request.headers.get("Authorization")
    if not dsai_auth_header or not dsai_auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Expected: Bearer <token>"
        )

    dsai_token = dsai_auth_header.split(" ", 1)[1].strip()
    if not dsai_token:
        raise HTTPException(status_code=401, detail="Empty token")

    dsai_key = dsai_load_public_key()

    try:
        dsai_payload = jwt.decode(dsai_token, dsai_key, algorithms=[DSAI_ALGORITHM])
    except JWTError as dsai_err:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(dsai_err)}")

    dsai_request.state.user = dsai_payload
    dsai_request.state.tenant_id = dsai_payload.get("tenant_id")

    return dsai_payload


def dsai_get_tenant_id(dsai_request: Request) -> Any:
    """Returns tenant_id from request.state. Assumes dsai_require_auth has already run."""
    dsai_tenant_id = getattr(dsai_request.state, "tenant_id", None)
    if dsai_tenant_id is None:
        raise HTTPException(status_code=400, detail="tenant_id not available")
    return dsai_tenant_id


def dsai_get_auth_context(dsai_request: Request) -> Dict[str, Any]:
    """
    Extract authentication context (tenant_id, user_id, roles, scopes)
    from request.state.user, falling back to verified Authorization header (AUTH-50).
    X-Tenant-ID alone never grants unauthenticated access.
    """
    dsai_user = getattr(dsai_request.state, "user", None)
    if isinstance(dsai_user, dict):
        return dsai_user

    dsai_auth_header = dsai_request.headers.get("Authorization") or dsai_request.headers.get("authorization")
    if dsai_auth_header and dsai_auth_header.startswith("Bearer "):
        dsai_token = dsai_auth_header[7:].strip()
        try:
            from deepSightAI.Trinetra.AuthService.auth_service import decode_token
            dsai_decoded = decode_token(dsai_token)
            if dsai_decoded and isinstance(dsai_decoded, dict):
                # Cross-check optional X-Tenant-ID header against authenticated claim
                dsai_x_tenant = dsai_request.headers.get("X-Tenant-ID") or dsai_request.headers.get("x-tenant-id")
                dsai_token_tenant = dsai_decoded.get("tenant_id")
                dsai_roles = dsai_decoded.get("roles", [])
                if dsai_x_tenant and dsai_token_tenant and dsai_x_tenant != dsai_token_tenant and "admin" not in dsai_roles:
                    raise HTTPException(
                        status_code=403,
                        detail=f"X-Tenant-ID header '{dsai_x_tenant}' does not match authenticated token tenant '{dsai_token_tenant}'"
                    )
                return dsai_decoded
        except HTTPException:
            raise
        except Exception:
            pass

    return {}


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    HTTP middleware extracting or generating X-Request-ID and attaching it
    to request state and response headers (REL-54).
    """

    async def dispatch(self, dsai_request: Request, dsai_call_next: Callable) -> Response:
        dsai_req_id = (
            dsai_request.headers.get("X-Request-ID")
            or dsai_request.headers.get("x-request-id")
            or str(uuid.uuid4())
        )
        dsai_request.state.request_id = dsai_req_id

        dsai_response = await dsai_call_next(dsai_request)
        dsai_response.headers["X-Request-ID"] = dsai_req_id
        return dsai_response


class AuditMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware to automatically log all API requests to AuditService.
    Propagates request_id across audit log entries.
    """

    def __init__(
        self,
        app,
        dsai_audit_service: Any,
        dsai_include_ip: bool = True,
        dsai_skip_paths: Optional[List[str]] = None,
    ):
        super().__init__(app)
        self.dsai_audit_service = dsai_audit_service
        self.dsai_include_ip = dsai_include_ip
        self.dsai_skip_paths = dsai_skip_paths or []

    async def dispatch(self, dsai_request: Request, dsai_call_next: Callable) -> Response:
        for dsai_skip in self.dsai_skip_paths:
            if dsai_request.url.path.startswith(dsai_skip):
                return await dsai_call_next(dsai_request)

        dsai_start_time = time.time()
        dsai_req_id = (
            getattr(dsai_request.state, "request_id", None)
            or dsai_request.headers.get("X-Request-ID")
            or str(uuid.uuid4())
        )
        dsai_request.state.request_id = dsai_req_id

        dsai_method = dsai_request.method
        dsai_path = dsai_request.url.path
        dsai_user_agent = dsai_request.headers.get("user-agent")
        dsai_tenant_id = getattr(dsai_request.state, "tenant_id", None)
        dsai_user_obj = getattr(dsai_request.state, "user", {})
        dsai_user_id = dsai_user_obj.get("sub") if isinstance(dsai_user_obj, dict) else None

        dsai_exception_occurred = False
        dsai_error_message = None
        dsai_status_code = 500

        try:
            dsai_response = await dsai_call_next(dsai_request)
            dsai_status_code = dsai_response.status_code
            dsai_response.headers["X-Request-ID"] = dsai_req_id
            return dsai_response
        except Exception as dsai_exc:
            dsai_exception_occurred = True
            dsai_error_message = str(dsai_exc)
            raise
        finally:
            dsai_elapsed = time.time() - dsai_start_time
            if dsai_exception_occurred:
                dsai_outcome = "FAILURE"
                dsai_status = 500
            else:
                if 200 <= dsai_status_code < 400:
                    dsai_outcome = "SUCCESS"
                    dsai_status = dsai_status_code
                else:
                    dsai_outcome = "FAILURE"
                    dsai_status = dsai_status_code

            dsai_log_entry = {
                "tenant_id": dsai_tenant_id or "anonymous",
                "user_id": dsai_user_id or "anonymous",
                "action": self._dsai_map_method_to_action(dsai_method, dsai_path, dsai_status),
                "resource": {
                    "type": "api_endpoint",
                    "id": dsai_path,
                    "name": f"{dsai_method} {dsai_path}"
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "outcome": dsai_outcome,
                "metadata": {
                    "http_status": dsai_status,
                    "elapsed_ms": int(dsai_elapsed * 1000),
                    "request_id": dsai_req_id,
                }
            }

            if self.dsai_include_ip:
                dsai_ip = (
                    dsai_request.headers.get("x-forwarded-for")
                    or dsai_request.headers.get("x-real-ip")
                    or (dsai_request.client.host if dsai_request.client else None)
                )
                dsai_log_entry["ip_address"] = dsai_ip

            if dsai_user_agent:
                dsai_log_entry["user_agent"] = dsai_user_agent

            if dsai_error_message:
                dsai_log_entry["metadata"]["error_message"] = dsai_error_message

            try:
                self.dsai_audit_service.handle_log(dsai_log_entry)
            except Exception as dsai_e:
                dsai_logger.error(f"Failed to audit log: {dsai_e}")

    def _dsai_map_method_to_action(self, dsai_method: str, dsai_path: str, dsai_status_code: int) -> str:
        dsai_method = dsai_method.upper()
        if dsai_method == "GET":
            return "READ"
        elif dsai_method == "POST":
            return "CREATE"
        elif dsai_method in ("PUT", "PATCH"):
            return "UPDATE"
        elif dsai_method == "DELETE":
            return "DELETE"
        else:
            return "ACCESS"


# Backwards compatibility re-exports
require_auth = dsai_require_auth
get_tenant_id = dsai_get_tenant_id
set_jwt_public_key = dsai_set_jwt_public_key
ALGORITHM = DSAI_ALGORITHM
