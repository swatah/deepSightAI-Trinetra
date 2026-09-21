"""
Vision Processing Service Service Daemon (VP-12).
"""

import os
import sys
import threading
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException

from deepSightAI.Trinetra.Shared.LoggingSetup import dsai_setup_logging, dsai_get_logger
from deepSightAI.Trinetra.Shared.Middleware import RequestIDMiddleware
from deepSightAI.Trinetra.Shared.ErrorHandlers import register_error_handlers
from deepSightAI.Trinetra.Shared.Metrics import dsai_metrics_response
from deepSightAI.Trinetra.VisionProcessingService.dsai_consumer import VisionProcessingConsumer

logger = dsai_get_logger("deepSightAI.Trinetra.VisionProcessingService")

app = FastAPI(title="Vision Processing Service", version="1.0.0")
app.add_middleware(RequestIDMiddleware)
register_error_handlers(app)


class VisionProcessingService:
    """
    Main coordinator for VisionProcessingService background workers and health checks.
    """

    def __init__(self, dsai_config: Optional[Dict[str, Any]] = None):
        self.dsai_config = dsai_config or {}
        self.dsai_consumer = VisionProcessingConsumer(dsai_config=self.dsai_config)
        self.dsai_stop_event = threading.Event()
        self.dsai_worker_thread: Optional[threading.Thread] = None

    def dsai_start(self):
        """Start the consumer background worker thread."""
        self.dsai_stop_event.clear()
        self.dsai_worker_thread = threading.Thread(
            target=self.dsai_consumer.run_loop,
            kwargs={"dsai_stop_flag": self.dsai_stop_event},
            daemon=True,
            name="vps-consumer-worker"
        )
        self.dsai_worker_thread.start()
        logger.info("VisionProcessingService worker thread started.")

    def dsai_stop(self):
        """Stop the consumer background worker thread."""
        self.dsai_stop_event.set()
        if self.dsai_worker_thread and self.dsai_worker_thread.is_alive():
            self.dsai_worker_thread.join(timeout=5.0)
        logger.info("VisionProcessingService worker thread stopped.")

    start = dsai_start
    stop = dsai_stop


# Lazy global service instance
_dsai_service = None


def get_service() -> VisionProcessingService:
    global _dsai_service
    if _dsai_service is None:
        _dsai_service = VisionProcessingService()
    return _dsai_service


@app.get("/health")
def dsai_health():
    """Liveness probe (REL-63)."""
    return {"status": "healthy", "service": "VisionProcessingService"}


@app.get("/ready")
def dsai_ready():
    """Readiness probe (REL-63)."""
    svc = get_service()
    is_ready = bool(svc.dsai_worker_thread and svc.dsai_worker_thread.is_alive())
    return {
        "status": "ready" if is_ready else "starting",
        "service": "VisionProcessingService",
        "worker_alive": is_ready
    }


@app.get("/metrics")
def dsai_metrics():
    """Scrapeable Prometheus metrics endpoint (REL-64)."""
    return dsai_metrics_response()



@app.on_event("startup")
def dsai_startup():
    get_service().start()


@app.on_event("shutdown")
def dsai_shutdown():
    if _dsai_service is not None:
        _dsai_service.stop()

