"""
Canonical PascalCase re-export for Errors hierarchy (REL-51).
"""

from deepSightAI.Trinetra.Shared.dsai_errors import (
    TrinetraError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    ValidationError,
    StorageError,
    MinIOError,
    MilvusError,
    StreamingError,
    DeadLetterQueueError,
    RecoverableOrphanError,
    ModelInferenceError,
    ConfigurationError,
    LegalHoldError,
)

__all__ = [
    "TrinetraError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ValidationError",
    "StorageError",
    "MinIOError",
    "MilvusError",
    "StreamingError",
    "DeadLetterQueueError",
    "RecoverableOrphanError",
    "ModelInferenceError",
    "ConfigurationError",
    "LegalHoldError",
]
