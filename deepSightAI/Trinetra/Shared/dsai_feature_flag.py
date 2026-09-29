"""
Feature flag and canary rollout management (Issue #87).

Controls rollout of high-traffic features (hardware decode, push-path edge endpoint)
behind configurable feature flags and canary allocations with fallback behavior.
"""

import os
import zlib
from typing import Optional, Set


class FeatureFlagManager:
    """Manages feature flags and canary rollouts for V3 ingestion capabilities."""

    @staticmethod
    def _dsai_parse_bool_env(dsai_var_name: str, dsai_default: bool = True) -> bool:
        dsai_val = os.getenv(dsai_var_name)
        if dsai_val is None:
            return dsai_default
        return dsai_val.strip().lower() in ("1", "true", "yes", "on", "enabled")

    @classmethod
    def dsai_is_hw_decode_enabled(cls, dsai_camera_id: Optional[str] = None) -> bool:
        """
        Check if hardware decode is enabled globally or for a specific camera/node.
        Rollout flag: DSAI_ENABLE_HW_DECODE (default: True).
        Canary percentage: DSAI_HW_DECODE_CANARY_PCT (0-100, default: 100).
        """
        if not cls._dsai_parse_bool_env("DSAI_ENABLE_HW_DECODE", dsai_default=True):
            return False

        dsai_canary_pct = int(os.getenv("DSAI_HW_DECODE_CANARY_PCT", "100"))
        if dsai_canary_pct >= 100:
            return True
        if dsai_canary_pct <= 0:
            return False

        if not dsai_camera_id:
            return True

        # Deterministic hashing into 0-99 bucket
        dsai_bucket = zlib.crc32(dsai_camera_id.encode("utf-8")) % 100
        return dsai_bucket < dsai_canary_pct

    @classmethod
    def dsai_is_edge_ingest_enabled(cls, dsai_tenant_id: Optional[str] = None) -> bool:
        """
        Check if edge push-path ingestion endpoint is enabled.
        Rollout flag: DSAI_ENABLE_EDGE_INGESTION (default: True).
        Canary percentage: DSAI_EDGE_CANARY_PCT (0-100, default: 100).
        Tenant allowlist: DSAI_EDGE_ALLOWED_TENANTS (comma-separated).
        """
        if not cls._dsai_parse_bool_env("DSAI_ENABLE_EDGE_INGESTION", dsai_default=True):
            return False

        # Check tenant allowlist if configured
        dsai_allowed_tenants_env = os.getenv("DSAI_EDGE_ALLOWED_TENANTS")
        if dsai_allowed_tenants_env and dsai_tenant_id:
            dsai_allowed: Set[str] = {t.strip() for t in dsai_allowed_tenants_env.split(",") if t.strip()}
            if dsai_allowed and dsai_tenant_id not in dsai_allowed:
                return False

        dsai_canary_pct = int(os.getenv("DSAI_EDGE_CANARY_PCT", "100"))
        if dsai_canary_pct >= 100:
            return True
        if dsai_canary_pct <= 0:
            return False

        if not dsai_tenant_id:
            return True

        dsai_bucket = zlib.crc32(dsai_tenant_id.encode("utf-8")) % 100
        return dsai_bucket < dsai_canary_pct


def dsai_is_hw_decode_enabled(dsai_camera_id: Optional[str] = None) -> bool:
    return FeatureFlagManager.dsai_is_hw_decode_enabled(dsai_camera_id)


def dsai_is_edge_ingest_enabled(dsai_tenant_id: Optional[str] = None) -> bool:
    return FeatureFlagManager.dsai_is_edge_ingest_enabled(dsai_tenant_id)
