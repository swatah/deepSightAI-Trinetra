"""
Canonical PascalCase re-export for Metrics (REL-64).
"""

from deepSightAI.Trinetra.Shared.dsai_metrics import (
    DSAI_PROCESSING_LATENCY,
    DSAI_DETECTION_COUNTS,
    DSAI_DLQ_DEPTH,
    DSAI_ALERT_MATCH_RATE,
    DSAI_QUERY_LATENCY,
    dsai_record_processing_latency,
    dsai_record_detection,
    dsai_update_dlq_depth,
    dsai_record_alert_match,
    dsai_record_query_latency,
    dsai_metrics_response,
    dsai_set_dlq_depth,
    dsai_generate_metrics_response,
    record_processing_latency,
    record_detection,
    update_dlq_depth,
    record_alert_match,
    record_query_latency,
    metrics_response,
)

__all__ = [
    "DSAI_PROCESSING_LATENCY",
    "DSAI_DETECTION_COUNTS",
    "DSAI_DLQ_DEPTH",
    "DSAI_ALERT_MATCH_RATE",
    "DSAI_QUERY_LATENCY",
    "dsai_record_processing_latency",
    "dsai_record_detection",
    "dsai_update_dlq_depth",
    "dsai_record_alert_match",
    "dsai_record_query_latency",
    "dsai_metrics_response",
    "record_processing_latency",
    "record_detection",
    "update_dlq_depth",
    "record_alert_match",
    "record_query_latency",
    "metrics_response",
]
