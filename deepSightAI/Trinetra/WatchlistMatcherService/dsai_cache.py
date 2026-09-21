"""
In-memory watchlist reference cache with periodic and change-triggered refresh (WL-30).

Maintains active, unexpired watchlist entries in memory per tenant to support
real-time sub-millisecond matching against live stream object detections.
"""

import os
import json
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from deepSightAI.Trinetra.Shared.LoggingSetup import dsai_get_logger
from deepSightAI.Trinetra.Shared.Repositories.WatchlistRepository import WatchlistRepository

dsai_logger = dsai_get_logger("deepSightAI.Trinetra.WatchlistMatcherService.dsai_cache")


@dataclass
class WatchlistEntryCacheItem:
    """In-memory representation of an active watchlist entry."""
    dsai_id: int
    dsai_tenant_id: str
    dsai_entry_type: str  # 'plate' | 'person_reid' | 'vehicle_reid'
    dsai_plate_text_norm: Optional[str]
    dsai_reid_reference_pk: Optional[str]
    dsai_reid_embedding: Optional[List[float]]
    dsai_label: str
    dsai_priority: str
    dsai_expires_at: Optional[datetime]
    dsai_created_at: datetime


class WatchlistCache:
    """
    In-memory cache of active watchlist entries with tenant scoping (WL-30).
    Supports TTL expiration, periodic background refresh, and change-triggered invalidation.
    """

    def __init__(self, dsai_ttl_seconds: float = 30.0):
        self.dsai_ttl_seconds = float(os.getenv("DSAI_WATCHLIST_CACHE_TTL", str(dsai_ttl_seconds)))
        self.dsai_entries: Dict[str, List[WatchlistEntryCacheItem]] = {}
        self.dsai_last_refresh: Dict[str, float] = {}
        self.dsai_lock = threading.RLock()
        self.dsai_stop_event = threading.Event()
        self.dsai_refresh_thread: Optional[threading.Thread] = None

    def dsai_refresh_tenant(self, dsai_tenant_id: str) -> List[WatchlistEntryCacheItem]:
        """Fetch active entries from WatchlistRepository for a tenant and update in-memory cache."""
        try:
            dsai_repo = WatchlistRepository(dsai_tenant_id)
            dsai_db_entries = dsai_repo.dsai_get_active_entries()

            dsai_cached_items: List[WatchlistEntryCacheItem] = []
            for dsai_entry in dsai_db_entries:
                dsai_emb = None
                if dsai_entry.reid_embedding_json:
                    try:
                        dsai_emb = json.loads(dsai_entry.reid_embedding_json)
                    except Exception as dsai_json_err:
                        dsai_logger.warning(
                            f"Failed to parse reid_embedding_json for entry {dsai_entry.id}: {dsai_json_err}"
                        )

                dsai_cached_items.append(
                    WatchlistEntryCacheItem(
                        dsai_id=dsai_entry.id,
                        dsai_tenant_id=dsai_entry.tenant_id,
                        dsai_entry_type=dsai_entry.entry_type,
                        dsai_plate_text_norm=dsai_entry.plate_text_norm,
                        dsai_reid_reference_pk=dsai_entry.reid_reference_pk,
                        dsai_reid_embedding=dsai_emb,
                        dsai_label=dsai_entry.label,
                        dsai_priority=dsai_entry.priority,
                        dsai_expires_at=dsai_entry.expires_at,
                        dsai_created_at=dsai_entry.created_at,
                    )
                )

            with self.dsai_lock:
                self.dsai_entries[dsai_tenant_id] = dsai_cached_items
                self.dsai_last_refresh[dsai_tenant_id] = time.time()

            dsai_logger.debug(
                f"Refreshed watchlist cache for tenant '{dsai_tenant_id}': {len(dsai_cached_items)} active entries"
            )
            return dsai_cached_items

        except Exception as dsai_err:
            dsai_logger.error(f"Error refreshing watchlist cache for tenant '{dsai_tenant_id}': {dsai_err}")
            with self.dsai_lock:
                return self.dsai_entries.get(dsai_tenant_id, [])

    def dsai_get_active_entries(self, dsai_tenant_id: str) -> List[WatchlistEntryCacheItem]:
        """
        Get active, unexpired entries for tenant.
        Refreshes if cache is expired or missing.
        """
        dsai_now = time.time()
        dsai_needs_refresh = False

        with self.dsai_lock:
            dsai_last = self.dsai_last_refresh.get(dsai_tenant_id, 0.0)
            if dsai_tenant_id not in self.dsai_entries or (dsai_now - dsai_last) > self.dsai_ttl_seconds:
                dsai_needs_refresh = True

        if dsai_needs_refresh:
            self.dsai_refresh_tenant(dsai_tenant_id)

        dsai_dt_now = datetime.utcnow()
        with self.dsai_lock:
            dsai_items = self.dsai_entries.get(dsai_tenant_id, [])
            return [
                dsai_item for dsai_item in dsai_items
                if dsai_item.dsai_expires_at is None or dsai_item.dsai_expires_at > dsai_dt_now
            ]

    def dsai_invalidate(self, dsai_tenant_id: Optional[str] = None):
        """
        Change-triggered cache invalidation (WL-30).
        If tenant_id is specified, refreshes or clears that tenant's cache.
        If tenant_id is None, clears all cached tenants.
        """
        with self.dsai_lock:
            if dsai_tenant_id is not None:
                self.dsai_last_refresh.pop(dsai_tenant_id, None)
                self.dsai_entries.pop(dsai_tenant_id, None)
            else:
                self.dsai_last_refresh.clear()
                self.dsai_entries.clear()

        if dsai_tenant_id is not None:
            self.dsai_refresh_tenant(dsai_tenant_id)

    def _dsai_background_refresh_loop(self):
        """Periodic background refresh loop across cached tenants."""
        while not self.dsai_stop_event.is_set():
            try:
                self.dsai_stop_event.wait(self.dsai_ttl_seconds)
                if self.dsai_stop_event.is_set():
                    break

                with self.dsai_lock:
                    dsai_tenants = list(self.dsai_entries.keys())

                for dsai_tenant in dsai_tenants:
                    self.dsai_refresh_tenant(dsai_tenant)

            except Exception as dsai_loop_err:
                dsai_logger.error(f"Error in watchlist cache background refresh loop: {dsai_loop_err}")

    def dsai_start(self):
        """Start background periodic refresh worker thread."""
        self.dsai_stop_event.clear()
        if self.dsai_refresh_thread is None or not self.dsai_refresh_thread.is_alive():
            self.dsai_refresh_thread = threading.Thread(
                target=self._dsai_background_refresh_loop,
                daemon=True,
                name="dsai-watchlist-cache-refresher"
            )
            self.dsai_refresh_thread.start()
            dsai_logger.info("WatchlistCache periodic refresh thread started.")

    def dsai_stop(self):
        """Stop background refresh worker thread."""
        self.dsai_stop_event.set()
        if self.dsai_refresh_thread and self.dsai_refresh_thread.is_alive():
            self.dsai_refresh_thread.join(timeout=2.0)
        self.dsai_refresh_thread = None
        dsai_logger.info("WatchlistCache periodic refresh thread stopped.")


# Global cache instance
_dsai_global_cache: Optional[WatchlistCache] = None
_dsai_cache_lock = threading.Lock()


def dsai_get_watchlist_cache() -> WatchlistCache:
    """Retrieve the global WatchlistCache singleton."""
    global _dsai_global_cache
    if _dsai_global_cache is None:
        with _dsai_cache_lock:
            if _dsai_global_cache is None:
                _dsai_global_cache = WatchlistCache()
    return _dsai_global_cache
