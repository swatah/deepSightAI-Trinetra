"""
Canonical PascalCase re-export for ErrorHandlers (REL-52).
"""

from deepSightAI.Trinetra.Shared.dsai_error_handlers import (
    dsai_register_error_handlers,
    dsai_extract_request_id,
    dsai_trinetra_error_handler,
    dsai_http_exception_handler,
    dsai_validation_exception_handler,
    dsai_unhandled_exception_handler,
    register_error_handlers,
    extract_request_id,
)

__all__ = [
    "dsai_register_error_handlers",
    "dsai_extract_request_id",
    "dsai_trinetra_error_handler",
    "dsai_http_exception_handler",
    "dsai_validation_exception_handler",
    "dsai_unhandled_exception_handler",
    "register_error_handlers",
    "extract_request_id",
]
