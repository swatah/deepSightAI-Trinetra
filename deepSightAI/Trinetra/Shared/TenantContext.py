"""
T1.2.5: Tenant extraction from JWT under deepSightAI.Trinetra.Shared.TenantContext.
"""

from fastapi import Request, HTTPException


def get_tenant_id(request: Request):
    """
    FastAPI dependency to get tenant_id from request state.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(
            status_code=400,
            detail="tenant_id not available in request state. Ensure JWT middleware is applied."
        )
    return tenant_id
