"""
Storage management utilities for MinIO.

Provides bucket lifecycle policy configuration (e.g. 7-day retention for raw frames)
and fallback scheduled cleanup utilities.
"""

import logging
from typing import Optional
from minio import Minio
from minio.lifecycleconfig import LifecycleConfig, Rule, Expiration
from minio.commonconfig import Filter

logger = logging.getLogger("shared.storage")

DEFAULT_FRAME_RETENTION_DAYS = 7


def configure_bucket_lifecycle(
    minio_client: Minio,
    bucket_name: str,
    retention_days: int = DEFAULT_FRAME_RETENTION_DAYS
) -> bool:
    """
    Configures a MinIO bucket lifecycle rule to automatically expire objects
    after the specified retention period.

    Args:
        minio_client: Initialized MinIO client
        bucket_name: Name of the bucket (e.g. 'frames')
        retention_days: Days after which objects expire (default: 7)

    Returns:
        True if configuration succeeded, False otherwise
    """
    try:
        lifecycle_config = LifecycleConfig([
            Rule(
                status="Enabled",
                rule_id=f"retention-{retention_days}-days",
                expiration=Expiration(days=retention_days),
                rule_filter=Filter(prefix=""),
            )
        ])
        minio_client.set_bucket_lifecycle(bucket_name, lifecycle_config)
        logger.info(
            f"Configured {retention_days}-day expiration lifecycle rule for bucket '{bucket_name}'"
        )
        return True
    except Exception as e:
        logger.warning(
            f"Failed to set lifecycle configuration on bucket '{bucket_name}': {e}"
        )
        return False


def cleanup_expired_frames(
    minio_client: Minio,
    bucket_name: str,
    retention_days: int = DEFAULT_FRAME_RETENTION_DAYS
) -> int:
    """
    Fallback scheduled cleaner: explicitly deletes objects older than retention_days.
    Useful in testing or when MinIO lifecycle scanner is not running.

    Args:
        minio_client: Initialized MinIO client
        bucket_name: Target bucket
        retention_days: Age threshold in days

    Returns:
        Number of objects deleted
    """
    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted_count = 0

    try:
        objects = minio_client.list_objects(bucket_name, recursive=True)
        for obj in objects:
            # Check last_modified timestamp
            if obj.last_modified and obj.last_modified < cutoff:
                minio_client.remove_object(bucket_name, obj.object_name)
                deleted_count += 1
                logger.debug(f"Removed expired frame: {obj.object_name}")

        if deleted_count > 0:
            logger.info(f"Purged {deleted_count} expired frames older than {retention_days} days from '{bucket_name}'")
    except Exception as e:
        logger.error(f"Error during expired frames cleanup in '{bucket_name}': {e}")

    return deleted_count
