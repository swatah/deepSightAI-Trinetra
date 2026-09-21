"""
Data and Crop Retention Policies with Legal-Hold Overrides (DM-8, DM-9, GOV-1, GOV-2).

Enforces:
1. Crop storage retention policy: which detections get image persistence vs embedding-only.
2. Data retention and legal-hold override: legal hold prevents any data deletion.
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Set, List

logger = logging.getLogger("deepSightAI.Trinetra.Shared.Retention")

# Default Retention Windows (in days)
DSAI_DEFAULT_FRAME_RETENTION_DAYS = 7
DSAI_DEFAULT_CROP_RETENTION_DAYS = 7
DSAI_DEFAULT_DETECTION_RETENTION_DAYS = 30
DSAI_DEFAULT_PLATE_RETENTION_DAYS = 90
DSAI_DEFAULT_ALERT_RETENTION_DAYS = 365

# In-memory registry of active legal holds (tenant_id -> set of camera_ids or "*" for entire tenant)
_DSAI_ACTIVE_LEGAL_HOLDS: Dict[str, Set[str]] = {}


def _dsai_get_redis_client():
    try:
        from deepSightAI.Trinetra.Shared.Streaming.RedisClient import create_redis_client
        client = create_redis_client()
        return client
    except Exception:
        return None


class CropRetentionPolicy:
    """
    Evaluates whether a detected object should have its cropped image persisted
    to object storage (MinIO) or only store the vector embedding in Milvus (DM-8).
    """

    def __init__(
        self,
        dsai_min_confidence: float = 0.5,
        dsai_store_crops: bool = True,
        dsai_persist_classes: Optional[Set[str]] = None,
    ):
        self.dsai_min_confidence = dsai_min_confidence
        self.dsai_store_crops = dsai_store_crops
        self.dsai_persist_classes = dsai_persist_classes or {"person", "vehicle"}

    def dsai_should_persist_crop(
        self,
        dsai_object_class: Optional[str] = None,
        dsai_confidence: Optional[float] = None,
        dsai_tenant_config: Optional[Dict[str, Any]] = None,
        *,
        object_class: Optional[str] = None,
        confidence: Optional[float] = None,
        tenant_config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Determine if detection crop should be saved to MinIO.

        Returns False (embedding-only) if:
        - store_crops is globally disabled
        - detection confidence is below min_confidence threshold
        - object class is not in persist_classes
        - tenant configuration overrides crop persistence to False
        """
        cls_val = object_class if object_class is not None else dsai_object_class
        conf_val = confidence if confidence is not None else (dsai_confidence if dsai_confidence is not None else 0.0)
        cfg_val = tenant_config if tenant_config is not None else dsai_tenant_config

        if cfg_val:
            if not cfg_val.get("store_crops", self.dsai_store_crops):
                return False
            dsai_threshold = cfg_val.get("min_confidence", self.dsai_min_confidence)
            dsai_classes = set(cfg_val.get("persist_classes", self.dsai_persist_classes))
        else:
            if not self.dsai_store_crops:
                return False
            dsai_threshold = self.dsai_min_confidence
            dsai_classes = self.dsai_persist_classes

        if conf_val < dsai_threshold:
            return False

        if cls_val not in dsai_classes:
            return False

        return True

    should_persist_crop = dsai_should_persist_crop


class DataRetentionManager:
    """
    Manages data lifecycle and deletion policies across detections, plate reads,
    and alerts, enforcing legal-hold overrides (DM-9, GOV-1).
    """

    @staticmethod
    def dsai_set_legal_hold(dsai_tenant_id: str, dsai_camera_id: Optional[str] = None, dsai_enabled: bool = True):
        """
        Enable or disable a legal hold for a tenant or specific camera feed.
        Persists in both in-memory registry and Redis key dsai:legal_hold:{tenant_id} (GOV-1).
        """
        if dsai_tenant_id not in _DSAI_ACTIVE_LEGAL_HOLDS:
            _DSAI_ACTIVE_LEGAL_HOLDS[dsai_tenant_id] = set()

        dsai_target = dsai_camera_id if dsai_camera_id else "*"
        if dsai_enabled:
            _DSAI_ACTIVE_LEGAL_HOLDS[dsai_tenant_id].add(dsai_target)
            logger.info(f"Legal hold ENABLED for tenant={dsai_tenant_id}, target={dsai_target}")
        else:
            _DSAI_ACTIVE_LEGAL_HOLDS[dsai_tenant_id].discard(dsai_target)
            logger.info(f"Legal hold REMOVED for tenant={dsai_tenant_id}, target={dsai_target}")

        redis_client = _dsai_get_redis_client()
        if redis_client:
            try:
                redis_key = f"dsai:legal_hold:{dsai_tenant_id}"
                if dsai_enabled:
                    redis_client.sadd(redis_key, dsai_target)
                else:
                    redis_client.srem(redis_key, dsai_target)
            except Exception as r_e:
                logger.debug(f"Redis legal hold sync skipped: {r_e}")

    @staticmethod
    def dsai_is_legal_hold_active(dsai_tenant_id: str, dsai_camera_id: Optional[str] = None) -> bool:
        """
        Check if an active legal hold applies to the given tenant and camera.
        Checks both memory and distributed Redis key dsai:legal_hold:{tenant_id} (GOV-1).
        """
        dsai_holds = _DSAI_ACTIVE_LEGAL_HOLDS.get(dsai_tenant_id, set())
        if "*" in dsai_holds:
            return True
        if dsai_camera_id and dsai_camera_id in dsai_holds:
            return True

        redis_client = _dsai_get_redis_client()
        if redis_client:
            try:
                redis_key = f"dsai:legal_hold:{dsai_tenant_id}"
                if redis_client.sismember(redis_key, "*"):
                    return True
                if dsai_camera_id and redis_client.sismember(redis_key, dsai_camera_id):
                    return True
            except Exception as r_e:
                logger.debug(f"Redis legal hold check skipped: {r_e}")

        return False

    @staticmethod
    def dsai_evaluate_expiration(
        dsai_created_at: datetime,
        dsai_retention_days: int,
        dsai_tenant_id: str,
        dsai_camera_id: Optional[str] = None,
        dsai_now: Optional[datetime] = None,
    ) -> bool:
        """
        Check if a record is eligible for deletion.

        CRITICAL: If an active legal hold exists, this method ALWAYS returns False
        regardless of record age.
        """
        if DataRetentionManager.dsai_is_legal_hold_active(dsai_tenant_id, dsai_camera_id):
            return False

        dsai_current_time = dsai_now or datetime.now(timezone.utc)
        if dsai_created_at.tzinfo is None:
            dsai_created_at = dsai_created_at.replace(tzinfo=timezone.utc)

        dsai_age = dsai_current_time - dsai_created_at
        return dsai_age > timedelta(days=dsai_retention_days)

    set_legal_hold = dsai_set_legal_hold
    is_legal_hold_active = dsai_is_legal_hold_active
    evaluate_expiration = dsai_evaluate_expiration


# Global instances and aliases
dsai_crop_policy = CropRetentionPolicy()
dsai_retention_manager = DataRetentionManager()
