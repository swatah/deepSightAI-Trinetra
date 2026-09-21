"""
Watchlist Matcher Service Daemon & HTTP Application (WL-26).
"""

import os
import sys
import threading
from typing import Optional, Dict, Any

from fastapi import FastAPI
from deepSightAI.Trinetra.Shared.LoggingSetup import dsai_setup_logging, dsai_get_logger
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_consumer import WatchlistMatcherConsumer
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_api import dsai_watchlist_router
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_cache import dsai_get_watchlist_cache

from deepSightAI.Trinetra.Shared.Middleware import RequestIDMiddleware
from deepSightAI.Trinetra.Shared.ErrorHandlers import register_error_handlers
from deepSightAI.Trinetra.Shared.Metrics import dsai_metrics_response

dsai_logger = dsai_get_logger("deepSightAI.Trinetra.WatchlistMatcherService")

app = FastAPI(
    title="deepSightAI Trinetra Watchlist Matcher Service",
    version="1.0.0",
    description="Real-time live stream watchlist matching and alerting engine (WL-26 to WL-34)."
)
app.add_middleware(RequestIDMiddleware)
register_error_handlers(app)

# Include Watchlist and Alerts API routes
app.include_router(dsai_watchlist_router)


class WatchlistMatcherService:
    """
    Coordinator for WatchlistMatcherService background consumer thread and lifecycle.
    """

    def __init__(self, dsai_config: Optional[Dict[str, Any]] = None):
        self.dsai_config = dsai_config or {}
        self.dsai_cache = dsai_get_watchlist_cache()
        self.dsai_consumer = WatchlistMatcherConsumer(
            dsai_config=self.dsai_config,
            dsai_cache=self.dsai_cache
        )
        self.dsai_stop_event = threading.Event()
        self.dsai_worker_thread: Optional[threading.Thread] = None

    def dsai_start(self):
        """Start the consumer background worker thread."""
        self.dsai_stop_event.clear()
        self.dsai_cache.dsai_start()
        self.dsai_worker_thread = threading.Thread(
            target=self.dsai_consumer.run_loop,
            kwargs={"dsai_stop_flag": self.dsai_stop_event},
            daemon=True,
            name="dsai-watchlist-matcher-worker"
        )
        self.dsai_worker_thread.start()
        dsai_logger.info("WatchlistMatcherService worker thread started.")

    def dsai_stop(self):
        """Stop the consumer background worker thread."""
        self.dsai_stop_event.set()
        if self.dsai_worker_thread and self.dsai_worker_thread.is_alive():
            self.dsai_worker_thread.join(timeout=5.0)
        self.dsai_cache.dsai_stop()
        dsai_logger.info("WatchlistMatcherService worker thread stopped.")

    start = dsai_start
    stop = dsai_stop


# Lazy global instance
_dsai_matcher_service: Optional[WatchlistMatcherService] = None


def dsai_get_service() -> WatchlistMatcherService:
    global _dsai_matcher_service
    if _dsai_matcher_service is None:
        _dsai_matcher_service = WatchlistMatcherService()
    return _dsai_matcher_service


@app.get("/health")
def dsai_health():
    """Service health check endpoint (REL-63)."""
    return {"status": "healthy", "service": "WatchlistMatcherService"}


@app.get("/ready")
def dsai_ready():
    """Service readiness check endpoint (REL-63)."""
    svc = dsai_get_service()
    is_ready = bool(svc.dsai_worker_thread and svc.dsai_worker_thread.is_alive())
    return {
        "status": "ready" if is_ready else "starting",
        "service": "WatchlistMatcherService",
        "worker_alive": is_ready
    }


@app.get("/metrics")
def dsai_metrics():
    """Service scrapeable metrics endpoint (REL-64)."""
    return dsai_metrics_response()



@app.on_event("startup")
def dsai_startup():
    dsai_get_service().start()


@app.on_event("shutdown")
def dsai_shutdown():
    if _dsai_matcher_service is not None:
        _dsai_matcher_service.stop()
