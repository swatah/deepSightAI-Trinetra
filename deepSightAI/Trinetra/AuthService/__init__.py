"""
AuthService package - Authentication, Authorization, RBAC, and JWT management.
"""

from .auth_service import app, User, Base, get_db, create_access_token, pwd_context
from .rbac import require_permission

__all__ = [
    "app",
    "User",
    "Base",
    "get_db",
    "create_access_token",
    "pwd_context",
    "require_permission",
]
