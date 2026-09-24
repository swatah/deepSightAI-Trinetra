"""
Edge push-path ingestion service and router (Issues #76, #77, #78, #79, #80, #81, #85, #87).

Accepts single or batch embedding events from edge devices, enforces idempotency,
validates schema and model dimensions, flags clock skew, checks circuit breakers,
normalizes records, and writes to Milvus and Redis Streams.
"""

import os
import json
import time
import logging
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Union

from fastapi import APIRouter, HTTPException, Request, Response, Header, Depends
from pydantic import ValidationError
from sqlalchemy.orm import Session

from deepSightAI.Trinetra.AuthService.auth_service import (
    get_db,
    EdgeDevice,
    dsai_verify_edge_device,
    _dsai_edge_lockout_tracker,
    _dsai_edge_lockout_lock,
)

from deepSightAI.Trinetra.Shared.Streaming.Schema import (
    EdgeEmbeddingEventV1,
    EdgeEmbeddingEventV2,
    EdgeBatchRequestV1,
    DSAI_KNOWN_EMBEDDING_MODELS,
)
from deepSightAI.Trinetra.Shared.Streaming.RedisClient import create_redis_client
from deepSightAI.Trinetra.Shared.Streaming.Producer import StreamProducer
from deepSightAI.Trinetra.Shared.dsai_normalization import (
    MilvusNormalizer,
    NormalizationError,
    MilvusCanonicalRecord,
)
from deepSightAI.Trinetra.Shared.Milvus import ensure_tenant_collection
from deepSightAI.Trinetra.Shared.dsai_circuit_breaker import (
    dsai_get_circuit_breaker,
    CircuitBreakerOpenException,
)
from deepSightAI.Trinetra.Shared.dsai_feature_flag import dsai_is_edge_ingest_enabled
from deepSightAI.Trinetra.Shared.Metrics import (
    dsai_record_push_device_count,
    dsai_record_push_latency,
    dsai_record_push_error,
    dsai_record_push_clock_skew,
)
from deepSightAI.Trinetra.Shared.LoggingSetup import dsai_get_correlation_id, dsai_set_correlation_id

logger = logging.getLogger("deepSightAI.Trinetra.ServerAndExtractor.EdgeIngest")

DSAI_MAX_BATCH_SIZE = int(os.getenv("DSAI_EDGE_MAX_BATCH_SIZE", "100"))
DSAI_MAX_PAYLOAD_BYTES = int(os.getenv("DSAI_EDGE_MAX_PAYLOAD_BYTES", str(10 * 1024 * 1024)))  # 10MB
DSAI_DEDUP_TTL_SECONDS = int(os.getenv("DSAI_EDGE_DEDUP_TTL", "86400"))  # 24h
DSAI_MAX_CLOCK_SKEW_SECONDS = float(os.getenv("DSAI_MAX_CLOCK_SKEW_SECONDS", "300.0"))  # 5 minutes


class EdgeIngestService:
    """Core service executing edge embedding ingestion with idempotency and normalization."""

    def __init__(self, dsai_redis_client=None, dsai_producer=None):
        self.dsai_redis_client = dsai_redis_client
        self.dsai_producer = dsai_producer

    def _dsai_get_redis(self):
        if self.dsai_redis_client is not None:
            return self.dsai_redis_client
        dsai_redis_breaker = dsai_get_circuit_breaker("redis")
        dsai_avail, dsai_retry = dsai_redis_breaker.dsai_is_available()
        if not dsai_avail:
            raise CircuitBreakerOpenException("redis", dsai_retry or 30.0)
        try:
            r = create_redis_client()
            dsai_redis_breaker.dsai_record_success()
            return r
        except Exception as dsai_err:
            dsai_redis_breaker.dsai_record_failure(dsai_err)
            raise HTTPException(
                status_code=503,
                detail=f"Redis dedup store unavailable: {dsai_err}",
                headers={"Retry-After": "5"}
            )

    def _dsai_get_producer(self):
        if self.dsai_producer is not None:
            return self.dsai_producer
        return StreamProducer()

    def dsai_claim_idempotency(self, dsai_event_id: str) -> tuple:
        """
        Atomically claim dedup key in Redis using SET NX EX to prevent check-then-act race (Issue #79, E5).
        Returns (is_new_claim, cached_result_if_duplicate).
        Raises HTTPException(503) if dedup store is down (never proceed without dedup).
        """
        dsai_r = self._dsai_get_redis()
        dsai_dedup_key = f"dedup:edge:{dsai_event_id}"
        dsai_redis_breaker = dsai_get_circuit_breaker("redis")

        try:
            dsai_in_progress = json.dumps({"status": "in_progress", "event_id": dsai_event_id})
            dsai_claimed = dsai_r.set(dsai_dedup_key, dsai_in_progress, nx=True, ex=60)
            dsai_redis_breaker.dsai_record_success()

            if dsai_claimed is True:
                return True, None

            # Key already exists: another request claimed or finished it
            dsai_existing = dsai_r.get(dsai_dedup_key)
            if dsai_existing:
                try:
                    dsai_parsed = json.loads(dsai_existing)
                    if dsai_parsed.get("status") == "in_progress":
                        dsai_start_w = time.monotonic()
                        while time.monotonic() - dsai_start_w < 2.0:
                            time.sleep(0.05)
                            dsai_poll = dsai_r.get(dsai_dedup_key)
                            if dsai_poll:
                                dsai_p = json.loads(dsai_poll)
                                if dsai_p.get("status") != "in_progress":
                                    return False, dsai_p
                        return False, {"status": "in_progress", "event_id": dsai_event_id, "cached": True}
                    return False, dsai_parsed
                except Exception:
                    return False, {"status": "success", "event_id": dsai_event_id, "cached": True}
            return True, None
        except Exception as dsai_err:
            dsai_redis_breaker.dsai_record_failure(dsai_err)
            raise HTTPException(
                status_code=503,
                detail=f"Dedup store unavailable at request time: {dsai_err}. Refusing to proceed without dedup check.",
                headers={"Retry-After": "5"}
            )

    def dsai_release_claim(self, dsai_event_id: str) -> None:
        """Release in-progress dedup key if processing fails before completion."""
        try:
            dsai_r = self._dsai_get_redis()
            dsai_dedup_key = f"dedup:edge:{dsai_event_id}"
            dsai_existing = dsai_r.get(dsai_dedup_key)
            if dsai_existing:
                dsai_parsed = json.loads(dsai_existing)
                if dsai_parsed.get("status") == "in_progress":
                    dsai_r.delete(dsai_dedup_key)
        except Exception as dsai_err:
            logger.warning(f"Failed to release in-progress claim for {dsai_event_id}: {dsai_err}")

    def dsai_check_idempotency(self, dsai_event_id: str) -> Optional[Dict[str, Any]]:
        """
        Check dedup store for previously processed event_id (Issue #79, E5).
        Returns cached result if already processed, None if new claim acquired.
        """
        dsai_is_new, dsai_cached = self.dsai_claim_idempotency(dsai_event_id)
        return dsai_cached if not dsai_is_new else None

    def dsai_mark_processed(self, dsai_event_id: str, dsai_result: Dict[str, Any]) -> None:
        """Atomically cache processed result in Redis with TTL (Issue #79)."""
        dsai_r = self._dsai_get_redis()
        dsai_dedup_key = f"dedup:edge:{dsai_event_id}"
        try:
            dsai_r.set(dsai_dedup_key, json.dumps(dsai_result), ex=DSAI_DEDUP_TTL_SECONDS)
        except Exception as dsai_err:
            logger.warning(f"Failed to record dedup entry for {dsai_event_id}: {dsai_err}")

    def dsai_handle_clock_skew(self, dsai_event: EdgeEmbeddingEventV1) -> float:
        """
        Check for clock skew between edge device timestamp and server receipt time (Issue #80, E7).
        Clamps timestamp if skew exceeds threshold and increments clock skew metric.
        """
        dsai_server_now = time.time()
        dsai_captured_at = float(dsai_event.captured_at)
        dsai_diff = abs(dsai_server_now - dsai_captured_at)

        if dsai_diff > DSAI_MAX_CLOCK_SKEW_SECONDS:
            logger.warning(
                f"Clock skew detected on camera '{dsai_event.camera_id}' "
                f"(captured_at={dsai_captured_at}, server_time={dsai_server_now}, delta={dsai_diff:.1f}s). "
                "Clamping timestamp to server receipt time to protect time-ordered indexes."
            )
            dsai_record_push_clock_skew(dsai_event.tenant_id, dsai_event.camera_id)
            return dsai_server_now

        return dsai_captured_at

    def dsai_record_liveness(self, dsai_tenant_id: str, dsai_camera_id: str) -> None:
        """Record push-path camera activity for liveness/staleness monitoring (Issue #80, E7)."""
        try:
            dsai_r = self._dsai_get_redis()
            dsai_live_key = f"push:liveness:{dsai_tenant_id}:{dsai_camera_id}"
            dsai_r.set(dsai_live_key, str(int(time.time())), ex=86400)
        except Exception as dsai_err:
            logger.warning(f"Failed to record push liveness for {dsai_camera_id}: {dsai_err}")

    def dsai_ingest_single_event(
        self,
        dsai_event: EdgeEmbeddingEventV1,
        dsai_correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Ingest a single edge embedding event with idempotency, validation, normalization, and insertion."""
        dsai_start = time.monotonic()
        dsai_cid = dsai_correlation_id or dsai_event.correlation_id or dsai_get_correlation_id()
        if dsai_cid:
            dsai_set_correlation_id(dsai_cid)

        # 1. Idempotency Check with Atomic Claim (E5, Issue #79)
        dsai_claimed, dsai_cached = self.dsai_claim_idempotency(dsai_event.event_id)
        if not dsai_claimed and dsai_cached:
            logger.info(f"Duplicate event_id '{dsai_event.event_id}' detected, returning cached result.")
            return dsai_cached

        try:
            # 2. Clock Skew Handling (E7, Issue #80)
            dsai_effective_timestamp = self.dsai_handle_clock_skew(dsai_event)
            dsai_event.captured_at = dsai_effective_timestamp

            # 3. Milvus Record Normalization (S1, Issue #81)
            dsai_canonical_record: MilvusCanonicalRecord = MilvusNormalizer.dsai_normalize_push(
                dsai_event=dsai_event,
                dsai_correlation_id=dsai_cid,
                dsai_producer=self._dsai_get_producer()
            )

            # 4. Milvus Insert (with Circuit Breaker) (Issue #85)
            dsai_milvus_breaker = dsai_get_circuit_breaker("milvus")
            dsai_avail, dsai_retry = dsai_milvus_breaker.dsai_is_available()
            if not dsai_avail:
                raise CircuitBreakerOpenException("milvus", dsai_retry or 30.0)

            try:
                dsai_collection = ensure_tenant_collection(
                    tenant_id=dsai_event.tenant_id,
                    embedding_dim=dsai_event.embedding_dim
                )
                # Insert into Milvus
                dsai_schema_fields = getattr(dsai_collection.schema, "fields", [])
                if len(dsai_schema_fields) in (3, 4):
                    dsai_collection.insert([
                        [dsai_canonical_record.video_id],
                        [dsai_canonical_record.frame_path],
                        [dsai_canonical_record.embedding],
                    ])
                else:
                    dsai_collection.insert([
                        [dsai_canonical_record.pk],
                        [dsai_canonical_record.video_id],
                        [dsai_canonical_record.camera_id],
                        [dsai_canonical_record.frame_path],
                        [dsai_canonical_record.frame_timestamp],
                        [dsai_canonical_record.embedding],
                        [dsai_canonical_record.tenant_id],
                    ])
                dsai_collection.flush()
                dsai_milvus_breaker.dsai_record_success()
            except Exception as dsai_milvus_err:
                dsai_milvus_breaker.dsai_record_failure(dsai_milvus_err)
                dsai_record_push_error("milvus_insert_failure")
                raise HTTPException(
                    status_code=503,
                    detail=f"Milvus vector database write failed: {dsai_milvus_err}",
                    headers={"Retry-After": "5"}
                )

            # 5. Record Liveness (E7, Issue #80)
            self.dsai_record_liveness(dsai_event.tenant_id, dsai_event.camera_id)

            # 6. Publish push ingest event to stream for downstream search/alerts
            try:
                self._dsai_get_producer().publish("events:edge_ingest", {
                    "event_id": dsai_event.event_id,
                    "tenant_id": dsai_event.tenant_id,
                    "camera_id": dsai_event.camera_id,
                    "pk": dsai_canonical_record.pk,
                    "captured_at": dsai_event.captured_at,
                    "correlation_id": dsai_cid
                })
            except Exception as dsai_pub_err:
                logger.warning(f"Failed to publish edge ingest event: {dsai_pub_err}")

            # 7. Record result in dedup store and record metrics (E5, S3)
            dsai_elapsed = time.monotonic() - dsai_start
            dsai_record_push_latency(dsai_elapsed)

            dsai_result = {
                "status": "success",
                "event_id": dsai_event.event_id,
                "pk": dsai_canonical_record.pk,
                "tenant_id": dsai_event.tenant_id,
                "camera_id": dsai_event.camera_id,
                "captured_at": dsai_event.captured_at,
                "correlation_id": dsai_cid,
            }
            self.dsai_mark_processed(dsai_event.event_id, dsai_result)
            return dsai_result
        except Exception:
            self.dsai_release_claim(dsai_event.event_id)
            raise

    def dsai_ingest_batch(
        self,
        dsai_events: List[Dict[str, Any]],
        dsai_correlation_id: Optional[str] = None,
        dsai_edge_device: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process batch of edge events with itemized per-item success/failure (Issue #76, E2, E6).
        Bad items are isolated and reported; valid items in the batch succeed.
        """
        dsai_results = []
        dsai_success_count = 0
        dsai_failure_count = 0

        for dsai_idx, dsai_raw_item in enumerate(dsai_events):
            try:
                # Validate item schema
                if isinstance(dsai_raw_item, dict):
                    dsai_parsed = EdgeEmbeddingEventV1(**dsai_raw_item)
                elif isinstance(dsai_raw_item, EdgeEmbeddingEventV1):
                    dsai_parsed = dsai_raw_item
                else:
                    raise ValueError(f"Expected dict or EdgeEmbeddingEventV1, got {type(dsai_raw_item).__name__}")

                if dsai_edge_device:
                    dsai_dev_tenant = getattr(dsai_edge_device, "tenant_id", None) or (dsai_edge_device.get("tenant_id") if isinstance(dsai_edge_device, dict) else None)
                    if dsai_dev_tenant is not None and str(dsai_parsed.tenant_id) != str(dsai_dev_tenant):
                        dsai_failure_count += 1
                        dsai_record_push_error("unauthorized_tenant")
                        dsai_results.append({
                            "index": dsai_idx,
                            "status": "error",
                            "reason": "unauthorized_tenant",
                            "detail": f"Device registered for '{dsai_dev_tenant}', cannot submit for '{dsai_parsed.tenant_id}'"
                        })
                        continue
                    dsai_dev_cams = getattr(dsai_edge_device, "assigned_cameras", None) or (dsai_edge_device.get("assigned_cameras") if isinstance(dsai_edge_device, dict) else [])
                    if dsai_dev_cams and dsai_parsed.camera_id not in dsai_dev_cams:
                        dsai_failure_count += 1
                        dsai_record_push_error("unauthorized_camera")
                        dsai_dev_id = getattr(dsai_edge_device, "device_id", None) or (dsai_edge_device.get("device_id") if isinstance(dsai_edge_device, dict) else "unknown")
                        dsai_results.append({
                            "index": dsai_idx,
                            "status": "error",
                            "reason": "unauthorized_camera",
                            "detail": f"Device '{dsai_dev_id}' not authorized for camera '{dsai_parsed.camera_id}'"
                        })
                        continue

                dsai_res = self.dsai_ingest_single_event(
                    dsai_event=dsai_parsed,
                    dsai_correlation_id=dsai_correlation_id
                )
                dsai_results.append({
                    "index": dsai_idx,
                    "status": "success",
                    "event_id": dsai_parsed.event_id,
                    "pk": dsai_res.get("pk")
                })
                dsai_success_count += 1
            except ValidationError as dsai_val_err:
                dsai_failure_count += 1
                dsai_record_push_error("validation_error")
                dsai_results.append({
                    "index": dsai_idx,
                    "status": "error",
                    "reason": "validation_error",
                    "detail": dsai_val_err.errors()
                })
            except ValueError as dsai_val_e:
                dsai_failure_count += 1
                dsai_record_push_error("value_error")
                dsai_results.append({
                    "index": dsai_idx,
                    "status": "error",
                    "reason": str(dsai_val_e),
                    "detail": str(dsai_val_e)
                })
            except NormalizationError as dsai_norm_err:
                dsai_failure_count += 1
                dsai_record_push_error("normalization_error")
                dsai_results.append({
                    "index": dsai_idx,
                    "status": "error",
                    "reason": "normalization_failure",
                    "detail": str(dsai_norm_err)
                })
            except Exception as dsai_gen_err:
                dsai_failure_count += 1
                dsai_record_push_error("processing_error")
                dsai_results.append({
                    "index": dsai_idx,
                    "status": "error",
                    "reason": "processing_error",
                    "detail": str(dsai_gen_err)
                })

        return {
            "total": len(dsai_events),
            "successful": dsai_success_count,
            "failed": dsai_failure_count,
            "results": dsai_results
        }


# Global singleton instance of EdgeIngestService
_DSAI_EDGE_SERVICE = EdgeIngestService()


def dsai_get_edge_service() -> EdgeIngestService:
    return _DSAI_EDGE_SERVICE


def dsai_check_edge_idempotency(dsai_event_id: str):
    """Check idempotency in dedup store; returns (is_duplicate, cached_response) (Issue #79)."""
    res = _DSAI_EDGE_SERVICE.dsai_check_idempotency(dsai_event_id)
    return (True, res) if res else (False, None)


def dsai_clamp_captured_timestamp(dsai_captured_at: float, dsai_server_now: Optional[float] = None) -> tuple:
    """Check and clamp clock skew; returns (effective_timestamp, was_flagged) (Issue #80)."""
    now = dsai_server_now if dsai_server_now is not None else time.time()
    diff = abs(now - float(dsai_captured_at))
    if diff > DSAI_MAX_CLOCK_SKEW_SECONDS:
        return now, True
    return float(dsai_captured_at), False


# --- FASTAPI ROUTER DEFINITION ---

dsai_edge_router = APIRouter(prefix="", tags=["Edge Ingestion"])


def dsai_validate_payload_size(request: Request) -> None:
    """Enforce payload and batch size limits; returns 413 on overflow (Issue #76)."""
    dsai_content_length = request.headers.get("content-length")
    if dsai_content_length:
        try:
            if int(dsai_content_length) > DSAI_MAX_PAYLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Payload size {dsai_content_length} bytes exceeds maximum limit of {DSAI_MAX_PAYLOAD_BYTES} bytes."
                )
        except ValueError:
            pass


def dsai_extract_edge_key(request: Request) -> Optional[str]:
    """Extract edge API key from X-API-Key or Authorization header (Issue #77, E3)."""
    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() in ("bearer", "apikey"):
            return parts[1].strip()
        elif len(parts) == 1:
            return parts[0].strip()
    api_key_header = request.headers.get("X-API-Key")
    if api_key_header:
        return api_key_header.strip()
    return None


def dsai_require_edge_auth(
    request: Request,
    dsai_db: Session = Depends(get_db)
) -> Any:
    """
    FastAPI dependency to verify edge device credentials (Issue #77, E3, Critical 1).
    Validates API key, checks revocation, tenant/device scoping, and 5-failure lockout (429).
    """
    dsai_key = dsai_extract_edge_key(request)
    if not dsai_key:
        raise HTTPException(
            status_code=401,
            detail="Missing edge device credential. Provide via 'X-API-Key' or 'Authorization: Bearer <key>' header.",
            headers={"WWW-Authenticate": "Bearer"}
        )
    dsai_device_id = request.headers.get("X-Device-ID")
    dsai_device = dsai_verify_edge_device(
        dsai_db=dsai_db,
        dsai_api_key=dsai_key,
        dsai_device_id=dsai_device_id
    )
    request.state.edge_device = dsai_device
    return dsai_device


@dsai_edge_router.post("/v1/edge/embeddings", status_code=200)
async def dsai_post_edge_embeddings_v1(
    request: Request,
    response: Response,
    edge_device: Any = Depends(dsai_require_edge_auth),
    x_correlation_id: Optional[str] = Header(None)
):
    """
    Ingest single event or batch of events for push path (Issues #76, #78, #79, #81, E1, E2).
    Supports canary rollout, circuit breakers, idempotency, and partial-batch error isolation.
    """
    dsai_validate_payload_size(request)

    # Content-type validation
    dsai_content_type = request.headers.get("content-type", "")
    if "application/json" not in dsai_content_type:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Content-Type '{dsai_content_type}'. Must be 'application/json'."
        )

    # Parse JSON body
    try:
        dsai_body = await request.json()
    except Exception as dsai_json_err:
        raise HTTPException(status_code=400, detail=f"Malformed JSON: {dsai_json_err}")

    # Check canary rollout flag (Issue #87)
    dsai_tenant_candidate = None
    if isinstance(dsai_body, dict):
        dsai_tenant_candidate = dsai_body.get("tenant_id")
    elif isinstance(dsai_body, list) and dsai_body:
        dsai_tenant_candidate = dsai_body[0].get("tenant_id") if isinstance(dsai_body[0], dict) else None

    if not dsai_is_edge_ingest_enabled(dsai_tenant_candidate):
        raise HTTPException(
            status_code=503,
            detail="Edge ingestion endpoint is not enabled or excluded by canary rollout policy."
        )

    dsai_service = dsai_get_edge_service()
    dsai_cid = x_correlation_id or dsai_get_correlation_id()

    # Case A: Batch Submission
    if isinstance(dsai_body, list):
        if len(dsai_body) > DSAI_MAX_BATCH_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Batch size {len(dsai_body)} exceeds maximum allowed batch limit of {DSAI_MAX_BATCH_SIZE} events."
            )
        return dsai_service.dsai_ingest_batch(dsai_body, dsai_correlation_id=dsai_cid, dsai_edge_device=edge_device)

    if isinstance(dsai_body, dict) and "events" in dsai_body:
        dsai_events_list = dsai_body.get("events")
        if not isinstance(dsai_events_list, list):
            raise HTTPException(status_code=400, detail="'events' field must be an array.")
        if len(dsai_events_list) > DSAI_MAX_BATCH_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Batch size {len(dsai_events_list)} exceeds maximum allowed batch limit of {DSAI_MAX_BATCH_SIZE} events."
            )
        return dsai_service.dsai_ingest_batch(dsai_events_list, dsai_correlation_id=dsai_cid, dsai_edge_device=edge_device)

    # Case B: Single Event Submission
    if isinstance(dsai_body, dict):
        # Validate required fields naming exact field (Issue #78)
        dsai_required_fields = [
            "camera_id", "tenant_id", "captured_at",
            "embedding_vector", "embedding_dim", "model_id", "model_version", "event_id"
        ]
        for dsai_f in dsai_required_fields:
            if dsai_f not in dsai_body:
                raise HTTPException(status_code=400, detail=f"Missing required field: '{dsai_f}'")

        try:
            dsai_event = EdgeEmbeddingEventV1(**dsai_body)
        except ValidationError as dsai_ve:
            dsai_first_err = dsai_ve.errors()[0]
            dsai_field = ".".join(str(loc) for loc in dsai_first_err.get("loc", []))
            dsai_msg = dsai_first_err.get("msg", "Validation error")
            raise HTTPException(status_code=400, detail=f"Invalid field '{dsai_field}': {dsai_msg}")
        except ValueError as dsai_val_e:
            raise HTTPException(status_code=400, detail=str(dsai_val_e))

        # Enforce edge device tenant and camera scoping (E3, E4, Issue #77)
        dsai_dev_tenant = getattr(edge_device, "tenant_id", None) or (edge_device.get("tenant_id") if isinstance(edge_device, dict) else None)
        if dsai_dev_tenant is not None and str(dsai_dev_tenant) != str(dsai_event.tenant_id):
            raise HTTPException(
                status_code=403,
                detail=f"Edge device tenant mismatch: registered for '{dsai_dev_tenant}', called for '{dsai_event.tenant_id}'"
            )

        dsai_dev_cams = getattr(edge_device, "assigned_cameras", None) or (edge_device.get("assigned_cameras") if isinstance(edge_device, dict) else [])
        if dsai_dev_cams and dsai_event.camera_id not in dsai_dev_cams:
            dsai_dev_id = getattr(edge_device, "device_id", None) or (edge_device.get("device_id") if isinstance(edge_device, dict) else "unknown")
            raise HTTPException(
                status_code=403,
                detail=f"Device '{dsai_dev_id}' is not authorized to submit embeddings for camera '{dsai_event.camera_id}'"
            )

        return dsai_service.dsai_ingest_single_event(dsai_event, dsai_correlation_id=dsai_cid)

    raise HTTPException(status_code=400, detail="Invalid payload structure: expected object or array.")


@dsai_edge_router.post("/v1/edge/embeddings/batch", status_code=200)
async def dsai_post_edge_embeddings_batch(
    request: Request,
    response: Response,
    edge_device: Any = Depends(dsai_require_edge_auth),
    x_correlation_id: Optional[str] = Header(None)
):
    """
    Dedicated batch ingestion endpoint for edge embeddings (Issues #76, #78).
    Accepts list or { items: [...] } with partial-batch itemized status.
    """
    dsai_validate_payload_size(request)
    try:
        dsai_body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Malformed JSON: {e}")

    items = dsai_body.get("items", dsai_body) if isinstance(dsai_body, dict) else dsai_body
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="Invalid payload: expected items array.")

    if len(items) > DSAI_MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Batch size {len(items)} exceeds maximum allowed batch limit of {DSAI_MAX_BATCH_SIZE} events."
        )

    service = dsai_get_edge_service()
    res = service.dsai_ingest_batch(
        items,
        dsai_correlation_id=x_correlation_id or dsai_get_correlation_id(),
        dsai_edge_device=edge_device
    )

    if res["failed"] > 0 and res["successful"] > 0:
        response.status_code = 207  # Partial success Multi-Status
    elif res["failed"] > 0 and res["successful"] == 0:
        response.status_code = 400

    return {
        "status": "partial" if res["failed"] > 0 else "success",
        "summary": {
            "total": res["total"],
            "accepted": res["successful"],
            "rejected": res["failed"]
        },
        "results": res["results"]
    }


@dsai_edge_router.post("/v2/edge/embeddings", status_code=200)
async def dsai_post_edge_embeddings_v2(
    request: Request,
    response: Response,
    edge_device: Any = Depends(dsai_require_edge_auth),
    x_correlation_id: Optional[str] = Header(None)
):
    """V2 edge embedding endpoint with forward compatibility (Issue #78)."""
    return await dsai_post_edge_embeddings_v1(request, response, edge_device, x_correlation_id)


@dsai_edge_router.post("/v0/edge/embeddings", status_code=410)
def dsai_sunset_edge_v0():
    """Sunset API version returning HTTP 410 Gone (Issue #78, E8)."""
    raise HTTPException(
        status_code=410,
        detail="API version /v0/ has reached sunset and is permanently decommissioned. Please migrate to /v1/edge/embeddings.",
        headers={"Link": '</v1/edge/embeddings>; rel="successor-version"'}
    )


@dsai_edge_router.post("/v1/edge/heartbeat")
def dsai_edge_heartbeat(
    request: Request,
    camera_id: str,
    tenant_id: str = "default",
    edge_device: Any = Depends(dsai_require_edge_auth)
):
    """Periodic edge device/camera heartbeat for liveness detection (Issue #80, E7)."""
    dsai_dev_tenant = getattr(edge_device, "tenant_id", None) or (edge_device.get("tenant_id") if isinstance(edge_device, dict) else None)
    if dsai_dev_tenant is not None and str(dsai_dev_tenant) != str(tenant_id):
        raise HTTPException(status_code=403, detail="Edge device tenant mismatch")
    dsai_dev_cams = getattr(edge_device, "assigned_cameras", None) or (edge_device.get("assigned_cameras") if isinstance(edge_device, dict) else [])
    if dsai_dev_cams and camera_id not in dsai_dev_cams:
        raise HTTPException(status_code=403, detail=f"Device not authorized for camera '{camera_id}'")

    dsai_service = dsai_get_edge_service()
    dsai_service.dsai_record_liveness(tenant_id, camera_id)
    return {"status": "ok", "camera_id": camera_id, "timestamp": time.time()}


@dsai_edge_router.get("/v1/edge/liveness/{tenant_id}/{camera_id}")
def dsai_check_camera_liveness(
    tenant_id: str,
    camera_id: str,
    max_idle_seconds: int = 120,
    edge_device: Any = Depends(dsai_require_edge_auth)
):
    """Check if push-path camera feed is active or stale (Issue #80, E7)."""
    dsai_dev_tenant = getattr(edge_device, "tenant_id", None) or (edge_device.get("tenant_id") if isinstance(edge_device, dict) else None)
    if dsai_dev_tenant is not None and str(dsai_dev_tenant) != str(tenant_id):
        raise HTTPException(status_code=403, detail="Edge device tenant mismatch")

    dsai_r = dsai_get_edge_service()._dsai_get_redis()
    dsai_live_key = f"push:liveness:{tenant_id}:{camera_id}"
    dsai_val = dsai_r.get(dsai_live_key)

    if not dsai_val:
        return {"camera_id": camera_id, "tenant_id": tenant_id, "status": "stale", "last_seen_seconds_ago": None}

    dsai_elapsed = time.time() - float(dsai_val)
    dsai_is_stale = dsai_elapsed > max_idle_seconds
    return {
        "camera_id": camera_id,
        "tenant_id": tenant_id,
        "status": "stale" if dsai_is_stale else "active",
        "last_seen_seconds_ago": round(dsai_elapsed, 1),
        "stale_threshold_seconds": max_idle_seconds
    }
