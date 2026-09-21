"""
deepSightAI Trinetra WatchlistMatcherService.

Live camera stream monitoring and watchlist alerting service (WL-26 to WL-34).
"""

from .dsai_service import WatchlistMatcherService, app
from .dsai_cache import WatchlistCache
from .dsai_matcher import AlertFloodSafeguard, dsai_match_plate, dsai_match_reid
from .dsai_consumer import WatchlistMatcherConsumer

__all__ = [
    "WatchlistMatcherService",
    "WatchlistCache",
    "AlertFloodSafeguard",
    "WatchlistMatcherConsumer",
    "app",
    "dsai_match_plate",
    "dsai_match_reid",
]
