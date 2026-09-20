"""
T1.2.6: RBAC - role-based permission checks

Provides `require_permission` dependency that enforces role-based access.
Assumes JWT validation middleware (`require_auth`) has already run and
set request.state.user with the decoded token payload (including 'roles').
"""

from fastapi import Request, HTTPException, Depends
from typing import List


def require_permission(required_permission: str):
    """
    Factory that returns a FastAPI dependency enforcing the given permission.

    Usage:
        @app.post("/endpoint")
        def endpoint(dep=Depends(require_permission("videos:create"))):
            ...

    The returned dependency expects `request: Request` to be injectable and
    also relies on request.state.user being populated by `require_auth`.
    """
    def dependency(request: Request):
        user_payload = getattr(request.state, "user", None)
        if user_payload is None:
            raise HTTPException(
                status_code=401,
                detail="Authentication required before permission check"
            )

        roles = user_payload.get("roles", [])
        if not isinstance(roles, list):
            roles = []

        if required_permission not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Missing required permission: {required_permission}"
            )

        # Permission granted; could return user_payload or True if needed
        return True

    return dependency

