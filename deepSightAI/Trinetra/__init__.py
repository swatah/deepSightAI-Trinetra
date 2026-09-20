"""
deepSightAI Trinetra package.

Provides unified access to Trinetra video search, live alerting, and microservices.
"""

from . import Shared
from . import ServerAndExtractor
from . import AuthService
from . import SearchService
from . import Embedder
from . import AuditService
from . import UI

# Convenient top-level model and service exports
from .ServerAndExtractor.extractor import (
    HttpRtspRequest,
    HttpFileRequest,
    FileJobRequest,
    RtspJobRequest,
)
from .AuthService import User, require_permission

__all__ = [
    "Shared",
    "ServerAndExtractor",
    "AuthService",
    "SearchService",
    "Embedder",
    "AuditService",
    "UI",
    "HttpRtspRequest",
    "HttpFileRequest",
    "FileJobRequest",
    "RtspJobRequest",
    "User",
    "require_permission",
]
