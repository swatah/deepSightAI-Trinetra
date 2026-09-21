"""
Standardized Exception Hierarchy for deepSightAI Trinetra (REL-51).

All custom exceptions in the platform inherit from TrinetraError.
"""

from typing import Optional, Dict, Any


class TrinetraError(Exception):
    """Base exception for all Trinetra platform errors."""

    def __init__(
        self,
        dsai_message: str = "An error occurred in deepSightAI Trinetra",
        dsai_code: Optional[str] = None,
        dsai_details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(dsai_message)
        self.dsai_message = dsai_message
        self.dsai_code = dsai_code or self.__class__.__name__
        self.dsai_details = dsai_details or {}

    def dsai_to_dict(self) -> Dict[str, Any]:
        """Serialize exception to structured dictionary."""
        return {
            "error": self.dsai_code,
            "message": self.dsai_message,
            "details": self.dsai_details,
        }

    to_dict = dsai_to_dict


class AuthenticationError(TrinetraError):
    """Raised when authentication fails (HTTP 401)."""
    pass


class PermissionDeniedError(TrinetraError):
    """Raised when access is denied due to missing roles/permissions (HTTP 403)."""
    pass


class NotFoundError(TrinetraError):
    """Raised when a requested resource is not found (HTTP 404)."""
    pass


class ValidationError(TrinetraError):
    """Raised when request payload or data validation fails (HTTP 422)."""
    pass


class StorageError(TrinetraError):
    """Base error for object storage operations."""
    pass


class MinIOError(StorageError):
    """Raised on MinIO upload, download, or bucket management failures."""
    pass


class MilvusError(TrinetraError):
    """Raised on Milvus connection, collection, or search failures."""
    pass


class StreamingError(TrinetraError):
    """Base error for streaming / message broker operations."""
    pass


class DeadLetterQueueError(StreamingError):
    """Raised when routing to or consuming from DLQ fails."""
    pass


class RecoverableOrphanError(StreamingError):
    """Raised when an extracted frame cannot be published to Redis and is recorded as orphan."""
    pass


class ModelInferenceError(TrinetraError):
    """Raised on AI model inference or plugin execution failures."""
    pass


class ConfigurationError(TrinetraError):
    """Raised when configuration values are missing or invalid."""
    pass


class LegalHoldError(TrinetraError):
    """Raised when an operation attempts to purge data under active legal hold."""
    pass
