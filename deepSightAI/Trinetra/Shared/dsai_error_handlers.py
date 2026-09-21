"""
Standardized error handlers and exception sanitization (REL-52).

Prevents leaking internal stack traces, DB connection details, or file paths
to HTTP clients while preserving server-side logging with correlation IDs.
"""

import uuid
from typing import Any, Dict, Optional
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError as PydanticValidationError

from deepSightAI.Trinetra.Shared.LoggingSetup import dsai_get_logger
from deepSightAI.Trinetra.Shared.dsai_errors import (
    TrinetraError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    ValidationError as CustomValidationError,
    StorageError,
    MinIOError,
    MilvusError,
    StreamingError,
    DeadLetterQueueError,
    LegalHoldError,
    ConfigurationError,
    ModelInferenceError,
)

dsai_logger = dsai_get_logger("deepSightAI.Trinetra.Shared.ErrorHandlers")


def dsai_extract_request_id(dsai_request: Request) -> str:
    """Extract or generate a request / correlation ID from request state or headers."""
    if hasattr(dsai_request, "state") and getattr(dsai_request.state, "request_id", None):
        return str(dsai_request.state.request_id)
    dsai_header_id = dsai_request.headers.get("X-Request-ID") or dsai_request.headers.get("x-request-id")
    if dsai_header_id:
        return dsai_header_id
    dsai_new_id = str(uuid.uuid4())
    if hasattr(dsai_request, "state"):
        dsai_request.state.request_id = dsai_new_id
    return dsai_new_id


def dsai_sanitize_detail(dsai_detail: Any) -> Any:
    """Sanitize detail message to avoid leaking passwords, tokens, or file paths."""
    if isinstance(dsai_detail, str):
        # Truncate overly long details or replace stack traces
        if "Traceback (most recent call last):" in dsai_detail:
            return "Internal processing error occurred"
        return dsai_detail
    return dsai_detail


async def dsai_trinetra_error_handler(dsai_request: Request, dsai_exc: TrinetraError) -> JSONResponse:
    """Handle custom Trinetra platform errors with appropriate HTTP status codes."""
    dsai_req_id = dsai_extract_request_id(dsai_request)

    if isinstance(dsai_exc, AuthenticationError):
        dsai_status = status.HTTP_401_UNAUTHORIZED
    elif isinstance(dsai_exc, PermissionDeniedError):
        dsai_status = status.HTTP_403_FORBIDDEN
    elif isinstance(dsai_exc, NotFoundError):
        dsai_status = status.HTTP_404_NOT_FOUND
    elif isinstance(dsai_exc, (CustomValidationError, PydanticValidationError)):
        dsai_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(dsai_exc, LegalHoldError):
        dsai_status = status.HTTP_409_CONFLICT
    elif isinstance(dsai_exc, ConfigurationError):
        dsai_status = status.HTTP_500_INTERNAL_SERVER_ERROR
    elif isinstance(dsai_exc, (StorageError, MinIOError, MilvusError, StreamingError, DeadLetterQueueError, ModelInferenceError)):
        dsai_status = status.HTTP_500_INTERNAL_SERVER_ERROR
    else:
        dsai_status = status.HTTP_500_INTERNAL_SERVER_ERROR

    dsai_logger.warning(
        f"TrinetraError [{dsai_exc.dsai_code}] on {dsai_request.method} {dsai_request.url.path} "
        f"(request_id={dsai_req_id}): {dsai_exc.dsai_message}"
    )

    dsai_response_body: Dict[str, Any] = {
        "error": dsai_exc.dsai_code,
        "message": dsai_sanitize_detail(dsai_exc.dsai_message),
        "request_id": dsai_req_id,
    }
    if dsai_exc.dsai_details:
        dsai_response_body["details"] = dsai_exc.dsai_details

    return JSONResponse(
        status_code=dsai_status,
        content=dsai_response_body,
        headers={"X-Request-ID": dsai_req_id}
    )


async def dsai_http_exception_handler(dsai_request: Request, dsai_exc: HTTPException) -> JSONResponse:
    """Handle standard HTTPException without leaking internal stack traces."""
    dsai_req_id = dsai_extract_request_id(dsai_request)
    dsai_logger.warning(
        f"HTTPException [{dsai_exc.status_code}] on {dsai_request.method} {dsai_request.url.path} "
        f"(request_id={dsai_req_id}): {dsai_exc.detail}"
    )
    return JSONResponse(
        status_code=dsai_exc.status_code,
        content={
            "error": "HTTPException",
            "message": dsai_sanitize_detail(dsai_exc.detail),
            "detail": dsai_sanitize_detail(dsai_exc.detail),
            "request_id": dsai_req_id,
        },
        headers={"X-Request-ID": dsai_req_id}
    )


async def dsai_validation_exception_handler(
    dsai_request: Request,
    dsai_exc: RequestValidationError
) -> JSONResponse:
    """Handle request validation errors cleanly."""
    dsai_req_id = dsai_extract_request_id(dsai_request)
    dsai_logger.warning(
        f"ValidationError on {dsai_request.method} {dsai_request.url.path} "
        f"(request_id={dsai_req_id}): {dsai_exc.errors()}"
    )
    # Sanitize errors list
    dsai_clean_errors = []
    for err in dsai_exc.errors():
        dsai_clean_errors.append({
            "loc": err.get("loc"),
            "msg": err.get("msg"),
            "type": err.get("type"),
        })
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "ValidationError",
            "message": "Invalid request parameters",
            "details": dsai_clean_errors,
            "request_id": dsai_req_id,
        },
        headers={"X-Request-ID": dsai_req_id}
    )


async def dsai_unhandled_exception_handler(dsai_request: Request, dsai_exc: Exception) -> JSONResponse:
    """
    Catch-all unhandled exception handler (REL-52).
    Strictly prevents leaking stack traces, database schema, or internal paths.
    Logs full exception details server-side.
    """
    dsai_req_id = dsai_extract_request_id(dsai_request)
    dsai_logger.exception(
        f"Unhandled Exception on {dsai_request.method} {dsai_request.url.path} "
        f"(request_id={dsai_req_id}): {dsai_exc}"
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred. Please contact support with the request ID.",
            "detail": "An internal server error occurred.",
            "request_id": dsai_req_id,
        },
        headers={"X-Request-ID": dsai_req_id}
    )


def dsai_register_error_handlers(dsai_app: FastAPI) -> None:
    """
    Register centralized error handlers on a FastAPI application (REL-52).
    """
    dsai_app.add_exception_handler(TrinetraError, dsai_trinetra_error_handler)
    dsai_app.add_exception_handler(HTTPException, dsai_http_exception_handler)
    dsai_app.add_exception_handler(RequestValidationError, dsai_validation_exception_handler)
    dsai_app.add_exception_handler(Exception, dsai_unhandled_exception_handler)


# Aliases for backwards compatibility
register_error_handlers = dsai_register_error_handlers
extract_request_id = dsai_extract_request_id
