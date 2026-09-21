"""
Structured JSON Logging for deepSightAI Trinetra (REL-53).

Provides JSON-formatted structured logging for all microservices.
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any


class DSAIJsonFormatter(logging.Formatter):
    """Formats log records as JSON lines with standardized fields."""

    def __init__(self, dsai_service_name: Optional[str] = None):
        super().__init__()
        self.dsai_service_name = dsai_service_name or os.getenv("SERVICE_NAME", "trinetra-service")

    def format(self, record: logging.LogRecord) -> str:
        dsai_log_record: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": getattr(record, "service", self.dsai_service_name),
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include standard context fields if present
        for dsai_field in ["tenant_id", "camera_id", "video_id", "correlation_id", "job_id"]:
            if hasattr(record, dsai_field):
                dsai_log_record[dsai_field] = getattr(record, dsai_field)

        # Include exception info if available
        if record.exc_info:
            dsai_log_record["exception"] = self.formatException(record.exc_info)

        # Include extra dictionary if passed in record.__dict__
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            dsai_log_record.update(record.extra_data)

        return json.dumps(dsai_log_record)


def dsai_setup_logging(
    dsai_service_name: str = "trinetra-service",
    dsai_level: str = "INFO",
    dsai_stream=sys.stdout
) -> logging.Logger:
    """
    Configure root/service logger with structured JSON formatting.

    Args:
        dsai_service_name: Name of the microservice
        dsai_level: Logging level (e.g. INFO, DEBUG)
        dsai_stream: Stream to output logs to (defaults to sys.stdout)

    Returns:
        Configured Logger instance.
    """
    dsai_env_level = os.getenv("LOG_LEVEL", dsai_level).upper()
    dsai_numeric_level = getattr(logging, dsai_env_level, logging.INFO)

    dsai_root = logging.getLogger()
    dsai_root.setLevel(dsai_numeric_level)

    # Remove existing stream handlers to prevent duplicate lines
    for dsai_handler in list(dsai_root.handlers):
        if isinstance(dsai_handler, logging.StreamHandler):
            dsai_root.removeHandler(dsai_handler)

    dsai_json_handler = logging.StreamHandler(dsai_stream)
    dsai_json_handler.setLevel(dsai_numeric_level)
    dsai_json_handler.setFormatter(DSAIJsonFormatter(dsai_service_name=dsai_service_name))
    dsai_root.addHandler(dsai_json_handler)

    dsai_svc_logger = logging.getLogger(dsai_service_name)
    dsai_svc_logger.setLevel(dsai_numeric_level)
    return dsai_svc_logger


def dsai_get_logger(dsai_name: str) -> logging.Logger:
    """Return a logger instance with the given name."""
    return logging.getLogger(dsai_name)


# Aliases for compatibility
setup_logging = dsai_setup_logging
get_logger = dsai_get_logger
JsonFormatter = DSAIJsonFormatter
