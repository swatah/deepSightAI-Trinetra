"""
Watchlist match engine: Plate matching, Re-ID cosine similarity, and flood safeguards (WL-28, WL-29, WL-34).
"""

import os
import re
import time
import math
import threading
from collections import deque
from typing import Tuple, List, Optional, Dict, Set

from deepSightAI.Trinetra.Shared.LoggingSetup import dsai_get_logger
from deepSightAI.Trinetra.Shared.Repositories.PlateRepository import dsai_trigram_similarity

dsai_logger = dsai_get_logger("deepSightAI.Trinetra.WatchlistMatcherService.dsai_matcher")


def dsai_normalize_plate(dsai_plate_text: Optional[str]) -> str:
    """Normalize license plate text by stripping non-alphanumeric chars and capitalizing (WL-28)."""
    if not dsai_plate_text:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(dsai_plate_text).strip().upper())


def dsai_match_plate(
    dsai_detected_plate: Optional[str],
    dsai_target_plate: Optional[str],
    dsai_threshold: float = 0.85
) -> Tuple[bool, float]:
    """
    Evaluate detected license plate against a watchlist plate target (WL-28).

    Performs:
    1. Exact comparison of normalized plate texts -> returns (True, 1.0)
    2. Trigram similarity comparison with OCR confusion mapping -> returns (True, score) if score >= threshold

    Returns:
        (is_match, score)
    """
    dsai_clean_det = dsai_normalize_plate(dsai_detected_plate)
    dsai_clean_target = dsai_normalize_plate(dsai_target_plate)

    if not dsai_clean_det or not dsai_clean_target:
        return False, 0.0

    # 1. Exact match check
    if dsai_clean_det == dsai_clean_target:
        return True, 1.0

    # 2. Fuzzy trigram similarity comparison
    dsai_sim = dsai_trigram_similarity(dsai_clean_det, dsai_clean_target)
    if dsai_sim >= dsai_threshold:
        return True, round(float(dsai_sim), 4)

    return False, round(float(dsai_sim), 4)


def dsai_cosine_similarity(
    dsai_vec1: Optional[List[float]],
    dsai_vec2: Optional[List[float]]
) -> float:
    """Compute cosine similarity between two float vectors (WL-29)."""
    if not dsai_vec1 or not dsai_vec2 or len(dsai_vec1) != len(dsai_vec2):
        return 0.0

    dsai_dot = 0.0
    dsai_norm1 = 0.0
    dsai_norm2 = 0.0

    for dsai_a, dsai_b in zip(dsai_vec1, dsai_vec2):
        dsai_dot += dsai_a * dsai_b
        dsai_norm1 += dsai_a * dsai_a
        dsai_norm2 += dsai_b * dsai_b

    if dsai_norm1 <= 0.0 or dsai_norm2 <= 0.0:
        return 0.0

    dsai_cos = dsai_dot / (math.sqrt(dsai_norm1) * math.sqrt(dsai_norm2))
    return max(-1.0, min(1.0, float(dsai_cos)))


def dsai_match_reid(
    dsai_det_embedding: Optional[List[float]],
    dsai_target_embedding: Optional[List[float]],
    dsai_threshold: float = 0.75
) -> Tuple[bool, float]:
    """
    Evaluate detected object Re-ID embedding against reference embedding (WL-29).

    Returns:
        (is_match, score)
    """
    if dsai_det_embedding is None or dsai_target_embedding is None:
        return False, 0.0

    dsai_sim = dsai_cosine_similarity(dsai_det_embedding, dsai_target_embedding)
    if dsai_sim >= dsai_threshold:
        return True, round(float(dsai_sim), 4)

    return False, round(float(dsai_sim), 4)


class AlertFloodSafeguard:
    """
    Alert flood safeguard and rate-limiting engine (WL-34).

    Prevents alert flooding (e.g. from static cars or camera spam):
    - Rate limits duplicate alerts per (tenant_id, watchlist_entry_id, camera_id) within cooldown window.
    - Auto-disables or suppresses watchlist entries that exceed flood thresholds within sliding window.
    """

    def __init__(
        self,
        dsai_cooldown_seconds: Optional[float] = None,
        dsai_flood_threshold: Optional[int] = None,
        dsai_window_seconds: Optional[float] = None,
        dsai_auto_disable: Optional[bool] = None
    ):
        self.dsai_cooldown_seconds = float(
            dsai_cooldown_seconds or os.getenv("DSAI_ALERT_COOLDOWN_SECONDS", "30.0")
        )
        self.dsai_flood_threshold = int(
            dsai_flood_threshold or os.getenv("DSAI_ALERT_FLOOD_THRESHOLD", "10")
        )
        self.dsai_window_seconds = float(
            dsai_window_seconds or os.getenv("DSAI_ALERT_FLOOD_WINDOW", "60.0")
        )
        self.dsai_auto_disable = (
            dsai_auto_disable if dsai_auto_disable is not None
            else (os.getenv("DSAI_ALERT_AUTO_DISABLE", "true").lower() in ("1", "true", "yes"))
        )

        # Map (tenant_id, entry_id, camera_id) -> last alert timestamp
        self.dsai_cooldown_map: Dict[Tuple[str, int, str], float] = {}
        # Map (tenant_id, entry_id) -> deque of alert timestamps in window
        self.dsai_flood_map: Dict[Tuple[str, int], deque] = {}
        # Set of auto-disabled (tenant_id, entry_id)
        self.dsai_disabled_entries: Set[Tuple[str, int]] = set()
        self.dsai_lock = threading.Lock()

    def dsai_should_suppress(
        self,
        dsai_tenant_id: str,
        dsai_entry_id: int,
        dsai_camera_id: str,
        dsai_now: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Check if an alert match should be suppressed due to cooldown or flood prevention (WL-34).

        Returns:
            (suppress: bool, reason: str)
        """
        dsai_current_time = dsai_now if dsai_now is not None else time.time()
        dsai_entry_key = (dsai_tenant_id, dsai_entry_id)
        dsai_cam_key = (dsai_tenant_id, dsai_entry_id, dsai_camera_id)

        with self.dsai_lock:
            # 1. Check if entry is already auto-disabled
            if dsai_entry_key in self.dsai_disabled_entries:
                return True, "auto_disabled_flood"

            # 2. Check camera-specific cooldown
            dsai_last_time = self.dsai_cooldown_map.get(dsai_cam_key, 0.0)
            if (dsai_current_time - dsai_last_time) < self.dsai_cooldown_seconds:
                return True, "cooldown_rate_limit"

            # 3. Check flood window count
            if dsai_entry_key in self.dsai_flood_map:
                dsai_history = self.dsai_flood_map[dsai_entry_key]
                # Prune timestamps outside sliding window
                while dsai_history and (dsai_current_time - dsai_history[0]) > self.dsai_window_seconds:
                    dsai_history.popleft()

                if len(dsai_history) >= self.dsai_flood_threshold:
                    if self.dsai_auto_disable:
                        self.dsai_disabled_entries.add(dsai_entry_key)
                        dsai_logger.warning(
                            f"Alert flood safeguard triggered: Auto-disabled watchlist entry {dsai_entry_id} "
                            f"(tenant '{dsai_tenant_id}') after {len(dsai_history)} alerts in {self.dsai_window_seconds}s"
                        )
                        return True, "auto_disabled_flood"
                    return True, "flood_threshold_exceeded"

            return False, ""

    def dsai_record_alert(
        self,
        dsai_tenant_id: str,
        dsai_entry_id: int,
        dsai_camera_id: str,
        dsai_now: Optional[float] = None
    ):
        """Record an issued alert timestamp for cooldown and flood tracking."""
        dsai_current_time = dsai_now if dsai_now is not None else time.time()
        dsai_entry_key = (dsai_tenant_id, dsai_entry_id)
        dsai_cam_key = (dsai_tenant_id, dsai_entry_id, dsai_camera_id)

        with self.dsai_lock:
            self.dsai_cooldown_map[dsai_cam_key] = dsai_current_time
            if dsai_entry_key not in self.dsai_flood_map:
                self.dsai_flood_map[dsai_entry_key] = deque()
            self.dsai_flood_map[dsai_entry_key].append(dsai_current_time)

    def dsai_enable_entry(self, dsai_tenant_id: str, dsai_entry_id: int):
        """Re-enable a watchlist entry that was auto-disabled by flood safeguard."""
        with self.dsai_lock:
            self.dsai_disabled_entries.discard((dsai_tenant_id, dsai_entry_id))
            self.dsai_flood_map.pop((dsai_tenant_id, dsai_entry_id), None)

    def dsai_reset(self):
        """Clear all tracking state (used in testing)."""
        with self.dsai_lock:
            self.dsai_cooldown_map.clear()
            self.dsai_flood_map.clear()
            self.dsai_disabled_entries.clear()


# Global safeguard instance
_dsai_global_safeguard: Optional[AlertFloodSafeguard] = None
_dsai_safeguard_lock = threading.Lock()


def dsai_get_alert_safeguard() -> AlertFloodSafeguard:
    """Retrieve the global AlertFloodSafeguard singleton."""
    global _dsai_global_safeguard
    if _dsai_global_safeguard is None:
        with _dsai_safeguard_lock:
            if _dsai_global_safeguard is None:
                _dsai_global_safeguard = AlertFloodSafeguard()
    return _dsai_global_safeguard
