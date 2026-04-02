"""
T1.2.5: Tenant extraction from JWT

Provides utility to extract tenant_id from request state after JWT validation.
The JWT validation middleware (require_auth) sets request.state.tenant_id
from the token's 'tenant_id' claim.
"""

from fastapi import Request, HTTPException


def get_tenant_id(request: Request):
    """
    FastAPI dependency to get tenant_id from request state.

    Should be used after the JWT validation middleware has run.
    Expects request.state.tenant_id to be set by require_auth.

    Returns:
        The tenant_id (could be int, str, or UUID) from token claims.

    Raises:
        HTTPException 400 if tenant_id is not available.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(
            status_code=400,
            detail="tenant_id not available in request state. Ensure JWT middleware is applied."
        )
    return tenant_id
