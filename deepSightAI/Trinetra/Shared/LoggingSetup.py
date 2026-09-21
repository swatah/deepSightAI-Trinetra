"""
Canonical PascalCase re-export for LoggingSetup (REL-53).
"""

from deepSightAI.Trinetra.Shared.dsai_logging_setup import (
    DSAIJsonFormatter,
    dsai_setup_logging,
    dsai_get_logger,
    setup_logging,
    get_logger,
    JsonFormatter,
)

__all__ = [
    "DSAIJsonFormatter",
    "dsai_setup_logging",
    "dsai_get_logger",
    "setup_logging",
    "get_logger",
    "JsonFormatter",
]
