"""
Canonical PascalCase re-export for Middleware (REL-54, AUTH-46).
"""

from deepSightAI.Trinetra.Shared.dsai_middleware import (
    dsai_require_auth,
    dsai_get_tenant_id,
    dsai_get_auth_context,
    dsai_set_jwt_public_key,
    dsai_load_public_key,
    RequestIDMiddleware,
    AuditMiddleware,
    require_auth,
    get_tenant_id,
    set_jwt_public_key,
    ALGORITHM,
    DSAI_ALGORITHM,
    DSAI_PROBE_PATHS,
)

get_auth_context = dsai_get_auth_context

__all__ = [
    "dsai_require_auth",
    "dsai_get_tenant_id",
    "dsai_set_jwt_public_key",
    "dsai_load_public_key",
    "RequestIDMiddleware",
    "AuditMiddleware",
    "require_auth",
    "get_tenant_id",
    "set_jwt_public_key",
    "ALGORITHM",
    "DSAI_ALGORITHM",
    "DSAI_PROBE_PATHS",
]
