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


# --- HELPER FUNCTIONS ---

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
