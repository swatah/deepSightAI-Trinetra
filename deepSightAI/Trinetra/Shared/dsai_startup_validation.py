"""
Fail-fast startup configuration validation (Issue #86).

Validates required environment variables, configuration keys, and connection
parameters during service boot. Halts startup immediately with a clear diagnostic
message if any required configuration is missing or malformed.
"""

import os
import sys
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger("deepSightAI.Trinetra.Shared.StartupValidation")


class ConfigValidationError(Exception):
    """Exception raised when required configuration is missing or invalid."""
    pass


StartupValidationError = ConfigValidationError


DSAI_SERVICE_REQUIRED_VARS: Dict[str, List[str]] = {
    "extractor": ["MINIO_URL", "REGISTRY_URL"],
    "embedder": ["REDIS_URL", "MINIO_URL", "MILVUS_HOST"],
    "main_api": ["REGISTRY_URL", "MINIO_URL"],
    "registry": ["REDIS_URL"],
    "auth_service": ["DATABASE_URL"],
    "edge_ingest": ["REDIS_URL"],
}


class StartupValidator:
    """Validates configuration requirements at process boot time."""

    @staticmethod
    def dsai_validate_environment(
        dsai_service_name: str,
        dsai_custom_required: Optional[List[str]] = None,
        dsai_fail_fast: bool = True
    ) -> Dict[str, str]:
        """
        Validate that all required environment variables are set and non-empty.

        Args:
            dsai_service_name: Name of the microservice
            dsai_custom_required: Optional list of additional required variables
            dsai_fail_fast: If True, raises ConfigValidationError immediately
        """
        dsai_required = list(DSAI_SERVICE_REQUIRED_VARS.get(dsai_service_name, []))
        if dsai_custom_required:
            dsai_required.extend(dsai_custom_required)

        dsai_missing: List[str] = []
        dsai_collected: Dict[str, str] = {}

        for dsai_var in dsai_required:
            dsai_val = os.getenv(dsai_var)
            if dsai_val is None or str(dsai_val).strip() == "":
                dsai_missing.append(dsai_var)
            else:
                dsai_collected[dsai_var] = str(dsai_val).strip()

        if dsai_missing:
            dsai_err_msg = (
                f"FATAL: Service '{dsai_service_name}' failed startup validation. "
                f"Missing or empty required environment variable(s): {', '.join(dsai_missing)}. "
                "Process cannot start safely without complete configuration."
            )
            logger.critical(dsai_err_msg)
            if dsai_fail_fast:
                raise ConfigValidationError(dsai_err_msg)

        return dsai_collected

    @staticmethod
    def dsai_validate_numeric_range(
        dsai_param_name: str,
        dsai_value: Any,
        dsai_min: Optional[float] = None,
        dsai_max: Optional[float] = None
    ) -> float:
        """Validate that a numeric parameter falls within an acceptable range."""
        try:
            dsai_num = float(dsai_value)
        except (ValueError, TypeError):
            raise ConfigValidationError(
                f"Configuration parameter '{dsai_param_name}' must be numeric, got: {dsai_value}"
            )

        if dsai_min is not None and dsai_num < dsai_min:
            raise ConfigValidationError(
                f"Configuration parameter '{dsai_param_name}' value {dsai_num} is below minimum {dsai_min}"
            )
        if dsai_max is not None and dsai_num > dsai_max:
            raise ConfigValidationError(
                f"Configuration parameter '{dsai_param_name}' value {dsai_num} exceeds maximum {dsai_max}"
            )

        return dsai_num


def dsai_validate_startup_config(
    dsai_service_name: str,
    dsai_custom_required: Optional[List[str]] = None,
    dsai_fail_fast: bool = True
) -> Dict[str, str]:
    """Top-level helper for fail-fast startup config validation."""
    return StartupValidator.dsai_validate_environment(
        dsai_service_name=dsai_service_name,
        dsai_custom_required=dsai_custom_required,
        dsai_fail_fast=dsai_fail_fast
    )
