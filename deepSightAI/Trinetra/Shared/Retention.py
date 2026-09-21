"""
Canonical PascalCase re-export for Retention (DM-8, DM-9).
"""

from deepSightAI.Trinetra.Shared.dsai_retention import (
    CropRetentionPolicy,
    DataRetentionManager,
    dsai_crop_policy,
    dsai_retention_manager,
    DSAI_DEFAULT_FRAME_RETENTION_DAYS,
    DSAI_DEFAULT_CROP_RETENTION_DAYS,
    DSAI_DEFAULT_DETECTION_RETENTION_DAYS,
    DSAI_DEFAULT_PLATE_RETENTION_DAYS,
    DSAI_DEFAULT_ALERT_RETENTION_DAYS,
)

__all__ = [
    "CropRetentionPolicy",
    "DataRetentionManager",
    "dsai_crop_policy",
    "dsai_retention_manager",
    "DSAI_DEFAULT_FRAME_RETENTION_DAYS",
    "DSAI_DEFAULT_CROP_RETENTION_DAYS",
    "DSAI_DEFAULT_DETECTION_RETENTION_DAYS",
    "DSAI_DEFAULT_PLATE_RETENTION_DAYS",
    "DSAI_DEFAULT_ALERT_RETENTION_DAYS",
]
