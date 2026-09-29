"""
Prometheus metrics collection and scrapeable endpoint for Trinetra services (REL-64).

Metrics tracked:
- processing_latency_seconds (Histogram)
- detection_counts_total (Counter)
- dlq_depth (Gauge)
- alert_matches_total (Counter)
- query_latency_seconds (Histogram)
"""

import time
import collections
import threading
from typing import Optional
from fastapi import Response
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY,
)

import uuid
import os

# --- PROMETHEUS METRIC DEFINITIONS (REL-64) ---

DSAI_PROCESSING_LATENCY = Histogram(
    "trinetra_processing_latency_seconds",
    "Processing latency in seconds across pipeline components",
    ["service", "operation"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0)
)

DSAI_DETECTION_COUNTS = Counter(
    "trinetra_detection_counts_total",
    "Total video object detections classified",
    ["tenant_id", "object_class"]
)

DSAI_DLQ_DEPTH = Gauge(
    "trinetra_dlq_depth",
    "Current dead-letter queue message backlog depth",
    ["stream"]
)

DSAI_ALERT_MATCH_RATE = Counter(
    "trinetra_alert_matches_total",
    "Total watchlist alert matches produced",
    ["tenant_id", "entry_type", "priority"]
)

DSAI_QUERY_LATENCY = Histogram(
    "trinetra_query_latency_seconds",
    "Search service query latency in seconds",
    ["endpoint", "tenant_id"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)
)


# --- PER-PATH INGESTION METRICS (Issue #83, S3) ---

DSAI_PULL_STREAM_COUNT = Gauge(
    "trinetra_ingestion_pull_stream_count",
    "Current active RTSP streams in pull path"
)

DSAI_ACTIVE_STREAMS = Gauge(
    "dsai_active_streams",
    "Current active RTSP streams in pull path for Pod HPA autoscaling (Issue #72, #74, Critical 2)"
)

DSAI_EMBEDDER_QUEUE_BACKLOG = Gauge(
    "dsai_embedder_queue_backlog",
    "Current backlog of pending frames in the embedder queue for autoscaling (Issue #73, Round 2 #8)"
)

DSAI_PULL_LATENCY = Histogram(
    "trinetra_ingestion_pull_latency_seconds",
    "Pull path frame processing and ingest latency",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

DSAI_PULL_ERROR_TOTAL = Counter(
    "trinetra_ingestion_pull_error_total",
    "Total pull path errors",
    ["reason"]
)

DSAI_PULL_DLQ_DEPTH = Gauge(
    "trinetra_ingestion_pull_dlq_depth",
    "Current DLQ depth for pull path"
)

DSAI_PUSH_DEVICE_COUNT = Gauge(
    "trinetra_ingestion_push_device_count",
    "Current active edge devices pushing embeddings"
)

DSAI_PUSH_LATENCY = Histogram(
    "trinetra_ingestion_push_latency_seconds",
    "Push path edge embedding ingest latency",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)
)

DSAI_PUSH_ERROR_TOTAL = Counter(
    "trinetra_ingestion_push_error_total",
    "Total push path errors",
    ["reason"]
)

DSAI_PUSH_DLQ_DEPTH = Gauge(
    "trinetra_ingestion_push_dlq_depth",
    "Current DLQ depth for push path"
)

DSAI_PUSH_CLOCK_SKEW_TOTAL = Counter(
    "trinetra_ingestion_push_clock_skew_total",
    "Total push events flagged for excessive clock skew",
    ["tenant_id", "camera_id"]
)

# In-memory per-path state tracking with sliding 5-minute window for decay (Issue #83, Moderate 11)
_DSAI_PATH_HEALTH_STATE = {
    "pull": {"errors_last_5m": 0, "active_streams": 0, "status": "healthy"},
    "push": {"errors_last_5m": 0, "active_devices": 0, "status": "healthy"}
}
_DSAI_PULL_ERROR_TIMESTAMPS: collections.deque = collections.deque()
_DSAI_PUSH_ERROR_TIMESTAMPS: collections.deque = collections.deque()
_DSAI_PATH_HEALTH_LOCK = threading.Lock()

_dsai_health_redis_client = None
_dsai_health_redis_lock = threading.Lock()


def _dsai_get_health_redis():
    """Obtain or cache a Redis client for distributed health state tracking across pods."""
    global _dsai_health_redis_client
    if _dsai_health_redis_client is not None:
        return _dsai_health_redis_client
    with _dsai_health_redis_lock:
        if _dsai_health_redis_client is not None:
            return _dsai_health_redis_client
        try:
            from deepSightAI.Trinetra.Shared.Streaming.RedisClient import create_redis_client
            _dsai_health_redis_client = create_redis_client()
            return _dsai_health_redis_client
        except Exception:
            return None


def _dsai_prune_health_window(dsai_dq: collections.deque, dsai_window: float = 300.0) -> int:
    dsai_cutoff = time.monotonic() - dsai_window
    while dsai_dq and dsai_dq[0] < dsai_cutoff:
        dsai_dq.popleft()
    return len(dsai_dq)


# --- HELPER FUNCTIONS ---

def dsai_record_embedder_backlog(dsai_count: int) -> None:
    """Record current embedder queue backlog (pending messages) for HPA autoscaling (Issue #73, Round 2 #8)."""
    DSAI_EMBEDDER_QUEUE_BACKLOG.set(dsai_count)


def dsai_record_pull_stream_count(dsai_count: int) -> None:
    """Record current active RTSP stream count for metrics and HPA autoscaling (Critical 2)."""
    DSAI_PULL_STREAM_COUNT.set(dsai_count)
    DSAI_ACTIVE_STREAMS.set(dsai_count)
    _DSAI_PATH_HEALTH_STATE["pull"]["active_streams"] = dsai_count
    try:
        dsai_r = _dsai_get_health_redis()
        if dsai_r:
            dsai_r.set("dsai:health:pull:active_streams", str(dsai_count), ex=60)
    except Exception:
        pass


def dsai_record_pull_latency(dsai_seconds: float) -> None:
    """Record pull path latency."""
    DSAI_PULL_LATENCY.observe(dsai_seconds)


def dsai_record_pull_error(dsai_reason: str = "general") -> None:
    """Record a pull path error with sliding window decay across pods (Round 2 #11)."""
    DSAI_PULL_ERROR_TOTAL.labels(reason=dsai_reason).inc()
    with _DSAI_PATH_HEALTH_LOCK:
        _DSAI_PULL_ERROR_TIMESTAMPS.append(time.monotonic())
        _DSAI_PATH_HEALTH_STATE["pull"]["errors_last_5m"] = _dsai_prune_health_window(_DSAI_PULL_ERROR_TIMESTAMPS)

    # Distributed cluster-wide tracking via Redis Sorted Set
    try:
        dsai_r = _dsai_get_health_redis()
        if dsai_r:
            dsai_now = time.time()
            dsai_key = "dsai:health:pull:errors"
            dsai_r.zadd(dsai_key, {f"{dsai_now}:{uuid.uuid4().hex[:8]}": dsai_now})
            dsai_r.zremrangebyscore(dsai_key, 0, dsai_now - 300.0)
            dsai_r.expire(dsai_key, 360)
    except Exception:
        pass


def dsai_update_pull_dlq_depth(dsai_depth: int) -> None:
    """Update pull path DLQ gauge."""
    DSAI_PULL_DLQ_DEPTH.set(dsai_depth)


def dsai_record_push_device_count(dsai_count: int) -> None:
    """Record active edge devices."""
    DSAI_PUSH_DEVICE_COUNT.set(dsai_count)
    _DSAI_PATH_HEALTH_STATE["push"]["active_devices"] = dsai_count
    try:
        dsai_r = _dsai_get_health_redis()
        if dsai_r:
            dsai_r.set("dsai:health:push:active_devices", str(dsai_count), ex=60)
    except Exception:
        pass


def dsai_record_push_latency(dsai_seconds: float) -> None:
    """Record push path latency."""
    DSAI_PUSH_LATENCY.observe(dsai_seconds)


def dsai_record_push_error(dsai_reason: str = "general") -> None:
    """Record a push path error with sliding window decay across pods (Round 2 #11)."""
    DSAI_PUSH_ERROR_TOTAL.labels(reason=dsai_reason).inc()
    with _DSAI_PATH_HEALTH_LOCK:
        _DSAI_PUSH_ERROR_TIMESTAMPS.append(time.monotonic())
        _DSAI_PATH_HEALTH_STATE["push"]["errors_last_5m"] = _dsai_prune_health_window(_DSAI_PUSH_ERROR_TIMESTAMPS)

    # Distributed cluster-wide tracking via Redis Sorted Set
    try:
        dsai_r = _dsai_get_health_redis()
        if dsai_r:
            dsai_now = time.time()
            dsai_key = "dsai:health:push:errors"
            dsai_r.zadd(dsai_key, {f"{dsai_now}:{uuid.uuid4().hex[:8]}": dsai_now})
            dsai_r.zremrangebyscore(dsai_key, 0, dsai_now - 300.0)
            dsai_r.expire(dsai_key, 360)
    except Exception:
        pass


def dsai_update_push_dlq_depth(dsai_depth: int) -> None:
    """Update push path DLQ gauge."""
    DSAI_PUSH_DLQ_DEPTH.set(dsai_depth)


def dsai_record_push_clock_skew(dsai_tenant_id: str, dsai_camera_id: str) -> None:
    """Record clock skew incident."""
    DSAI_PUSH_CLOCK_SKEW_TOTAL.labels(tenant_id=dsai_tenant_id, camera_id=dsai_camera_id).inc()


def dsai_get_per_path_health(dsai_redis_client: Optional[object] = None) -> dict:
    """
    Return independent health indicators for pull and push paths.
    CRITICAL: Never aggregate into a single average score (Issue #83).
    Automatically decays error counts outside the rolling 5-minute window.
    Reads cluster-wide error counts from Redis across multi-pod deployments (Round 2 #11).
    """
    with _DSAI_PATH_HEALTH_LOCK:
        dsai_local_pull_errors = _dsai_prune_health_window(_DSAI_PULL_ERROR_TIMESTAMPS, 300.0)
        dsai_local_push_errors = _dsai_prune_health_window(_DSAI_PUSH_ERROR_TIMESTAMPS, 300.0)
        _DSAI_PATH_HEALTH_STATE["pull"]["errors_last_5m"] = dsai_local_pull_errors
        _DSAI_PATH_HEALTH_STATE["push"]["errors_last_5m"] = dsai_local_push_errors

    dsai_pull_errors = dsai_local_pull_errors
    dsai_push_errors = dsai_local_push_errors
    dsai_active_streams = _DSAI_PATH_HEALTH_STATE["pull"]["active_streams"]
    dsai_active_devices = _DSAI_PATH_HEALTH_STATE["push"]["active_devices"]

    # Query shared cluster-wide Redis state across extractor, embedder, and main_api pods
    try:
        dsai_r = dsai_redis_client or _dsai_get_health_redis()
        if dsai_r:
            dsai_now = time.time()
            # Prune and count pull errors across cluster
            dsai_pull_key = "dsai:health:pull:errors"
            dsai_r.zremrangebyscore(dsai_pull_key, 0, dsai_now - 300.0)
            dsai_redis_pull_errors = dsai_r.zcount(dsai_pull_key, dsai_now - 300.0, dsai_now)
            if dsai_redis_pull_errors is not None:
                dsai_pull_errors = max(dsai_local_pull_errors, int(dsai_redis_pull_errors))

            # Prune and count push errors across cluster
            dsai_push_key = "dsai:health:push:errors"
            dsai_r.zremrangebyscore(dsai_push_key, 0, dsai_now - 300.0)
            dsai_redis_push_errors = dsai_r.zcount(dsai_push_key, dsai_now - 300.0, dsai_now)
            if dsai_redis_push_errors is not None:
                dsai_push_errors = max(dsai_local_push_errors, int(dsai_redis_push_errors))

            # Read distributed active counts if present
            dsai_cached_streams = dsai_r.get("dsai:health:pull:active_streams")
            if dsai_cached_streams is not None:
                try:
                    dsai_active_streams = int(dsai_cached_streams)
                except (ValueError, TypeError):
                    pass

            dsai_cached_devices = dsai_r.get("dsai:health:push:active_devices")
            if dsai_cached_devices is not None:
                try:
                    dsai_active_devices = int(dsai_cached_devices)
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass

    dsai_pull_status = "healthy" if dsai_pull_errors < 10 else ("degraded" if dsai_pull_errors < 50 else "outage")
    dsai_push_status = "healthy" if dsai_push_errors < 10 else ("degraded" if dsai_push_errors < 50 else "outage")

    return {
        "pull_path": {
            "status": dsai_pull_status,
            "active_streams": dsai_active_streams,
            "recent_errors": dsai_pull_errors,
        },
        "push_path": {
            "status": dsai_push_status,
            "active_devices": dsai_active_devices,
            "recent_errors": dsai_push_errors,
        }
    }


def dsai_reset_health_metrics() -> None:
    """Reset per-path error tracking and health states (for testing and lifecycle reset)."""
    with _DSAI_PATH_HEALTH_LOCK:
        _DSAI_PULL_ERROR_TIMESTAMPS.clear()
        _DSAI_PUSH_ERROR_TIMESTAMPS.clear()
        _DSAI_PATH_HEALTH_STATE["pull"] = {"errors_last_5m": 0, "active_streams": 0, "status": "healthy"}
        _DSAI_PATH_HEALTH_STATE["push"] = {"errors_last_5m": 0, "active_devices": 0, "status": "healthy"}



def dsai_record_processing_latency(dsai_service: str, dsai_operation: str, dsai_seconds: float) -> None:
    """Record processing latency for a service operation."""
    DSAI_PROCESSING_LATENCY.labels(service=dsai_service, operation=dsai_operation).observe(dsai_seconds)


def dsai_record_detection(dsai_tenant_id: str, dsai_object_class: str, dsai_count: int = 1) -> None:
    """Increment detection count for a given tenant and object class."""
    DSAI_DETECTION_COUNTS.labels(tenant_id=dsai_tenant_id, object_class=dsai_object_class).inc(dsai_count)


def dsai_update_dlq_depth(dsai_stream: str, dsai_depth: int) -> None:
    """Set the DLQ depth gauge for a given stream."""
    DSAI_DLQ_DEPTH.labels(stream=dsai_stream).set(dsai_depth)


def dsai_record_alert_match(dsai_tenant_id: str, dsai_entry_type: str, dsai_priority: str = "medium") -> None:
    """Record an alert match event."""
    DSAI_ALERT_MATCH_RATE.labels(tenant_id=dsai_tenant_id, entry_type=dsai_entry_type, priority=dsai_priority).inc()


def dsai_record_query_latency(dsai_endpoint: str, dsai_tenant_id: str, dsai_seconds: float) -> None:
    """Record search query execution latency."""
    DSAI_QUERY_LATENCY.labels(endpoint=dsai_endpoint, tenant_id=dsai_tenant_id).observe(dsai_seconds)


def dsai_metrics_response() -> Response:
    """Generate scrapeable HTTP response in Prometheus exposition format."""
    dsai_data = generate_latest(REGISTRY)
    return Response(content=dsai_data, media_type=CONTENT_TYPE_LATEST)


# Backwards compatibility aliases
dsai_set_dlq_depth = dsai_update_dlq_depth
dsai_generate_metrics_response = dsai_metrics_response
record_processing_latency = dsai_record_processing_latency
record_detection = dsai_record_detection
update_dlq_depth = dsai_update_dlq_depth
set_dlq_depth = dsai_update_dlq_depth
record_alert_match = dsai_record_alert_match
record_query_latency = dsai_record_query_latency
metrics_response = dsai_metrics_response
generate_metrics_response = dsai_metrics_response

