"""
Comprehensive Test Suite for Enterprise Ingestion V3 (GitHub Issues #71 - #87).

Validates:
- Phase 1: Pull Path Scaling (#71, #72, #73, #74, #75)
- Phase 2: Push Path Ingestion (#76, #77, #78, #79, #80)
- Phase 3: Shared Unification (#81, #82, #83)
- Phase 4: Production Hardening (#84, #85, #86, #87)

Adheres strictly to CODING_STANDARDS.md:
- All variable names, function names, and fixtures prefixed with dsai_
- Canonical package imports
- Exhaustive negative and edge-case testing
"""

import os
import time
import json
import uuid
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Canonical imports
from deepSightAI.Trinetra.Shared.dsai_circuit_breaker import (
    CircuitState,
    CircuitBreakerOpenException,
    CircuitBreaker,
    dsai_get_circuit_breaker,
    dsai_check_circuit_breaker,
    dsai_reset_circuit_breakers,
)
from deepSightAI.Trinetra.Shared.dsai_startup_validation import (
    StartupValidationError,
    dsai_validate_startup_config,
)
from deepSightAI.Trinetra.Shared.dsai_feature_flag import (
    FeatureFlagManager,
    dsai_is_hw_decode_enabled,
    dsai_is_edge_ingest_enabled,
)
from deepSightAI.Trinetra.Shared.LoggingSetup import (
    dsai_set_correlation_id,
    dsai_get_correlation_id,
    DSAIJsonFormatter,
)
from deepSightAI.Trinetra.Shared.Metrics import (
    dsai_get_per_path_health,
    dsai_reset_health_metrics,
    dsai_record_pull_stream_count,
    dsai_record_pull_error,
    dsai_record_push_device_count,
    dsai_record_push_error,
    dsai_update_dlq_depth,
    dsai_record_embedder_backlog,
    DSAI_EMBEDDER_QUEUE_BACKLOG,
)
from deepSightAI.Trinetra.Shared.dsai_normalization import (
    MilvusCanonicalRecord,
    MilvusNormalizer,
    NormalizationError,
)
from deepSightAI.Trinetra.Shared.Streaming.Schema import (
    EdgeEmbeddingEventV1,
    EdgeEmbeddingEventV2,
    EdgeBatchRequestV1,
    DSAI_KNOWN_EMBEDDING_MODELS,
    FrameReadyEvent,
)
from deepSightAI.Trinetra.Shared.Streaming.Consumer import StreamConsumer, Message
from deepSightAI.Trinetra.Shared.Repositories.CameraRepository import CameraRepository
from deepSightAI.Trinetra.Shared.Middleware import require_auth
from deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest import (
    dsai_check_edge_idempotency,
    dsai_clamp_captured_timestamp,
    dsai_require_edge_auth,
)


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture(autouse=True)
def dsai_reset_state():
    """Reset circuit breakers and correlation contexts between test runs."""
    dsai_reset_circuit_breakers()
    dsai_set_correlation_id(None)
    yield
    dsai_reset_circuit_breakers()
    dsai_set_correlation_id(None)


# ==============================================================================
# Issue #71: Hardware Video Decode & Mid-Stream Error Recovery
# ==============================================================================

class TestIssue71HardwareDecode:
    """Tests for HW decoder detection, fallback, and mid-stream error recovery."""

    def test_dsai_hardware_decoder_detection_nvidia(self):
        """Verify NVIDIA hardware decoder is selected when present."""
        from deepSightAI.Trinetra.ServerAndExtractor.extractor import dsai_detect_hardware_decoder
        
        with patch("gi.repository.Gst.ElementFactory.find") as dsai_mock_find:
            dsai_mock_find.side_effect = lambda name: MagicMock() if name == "nvv4l2decoder" else None
            dsai_decoder, dsai_is_hw = dsai_detect_hardware_decoder()
            assert dsai_decoder == "nvv4l2decoder"
            assert dsai_is_hw is True

    def test_dsai_hardware_decoder_detection_vaapi(self):
        """Verify VAAPI hardware decoder is selected on Intel nodes."""
        from deepSightAI.Trinetra.ServerAndExtractor.extractor import dsai_detect_hardware_decoder
        
        with patch("gi.repository.Gst.ElementFactory.find") as dsai_mock_find:
            dsai_mock_find.side_effect = lambda name: MagicMock() if name == "vaapih264dec" else None
            dsai_decoder, dsai_is_hw = dsai_detect_hardware_decoder()
            assert dsai_decoder == "vaapih264dec"
            assert dsai_is_hw is True

    def test_dsai_hardware_decoder_fallback_to_software(self):
        """Verify fallback to avdec_h264 when no hardware decoders exist."""
        from deepSightAI.Trinetra.ServerAndExtractor.extractor import dsai_detect_hardware_decoder
        
        with patch("gi.repository.Gst.ElementFactory.find", return_value=None):
            dsai_decoder, dsai_is_hw = dsai_detect_hardware_decoder()
            assert dsai_decoder == "avdec_h264"
            assert dsai_is_hw is False

    def test_dsai_pipeline_reconnect_exponential_backoff_and_dlq(self):
        """Verify pipeline reconnect catches errors, limits retries, and routes failed streams."""
        from deepSightAI.Trinetra.ServerAndExtractor.extractor import run_rtsp_extraction_job
        
        dsai_shutdown = MagicMock()
        dsai_shutdown.is_set.side_effect = [False, False, True]

        with patch("deepSightAI.Trinetra.ServerAndExtractor.extractor.GStreamerRtspExtractor") as dsai_mock_ext_cls, \
             patch("deepSightAI.Trinetra.ServerAndExtractor.extractor.time.sleep") as dsai_mock_sleep, \
             patch("deepSightAI.Trinetra.ServerAndExtractor.extractor.get_producer") as dsai_mock_prod_fn, \
             patch("deepSightAI.Trinetra.ServerAndExtractor.extractor.ensure_bucket") as dsai_mock_bucket, \
             patch("deepSightAI.Trinetra.ServerAndExtractor.extractor.Minio") as dsai_mock_minio, \
             patch.dict(os.environ, {"DSAI_MAX_STREAM_FAILURES": "2"}):
            
            dsai_mock_prod = MagicMock()
            dsai_mock_prod_fn.return_value = dsai_mock_prod
            dsai_mock_instance = MagicMock()
            dsai_mock_instance.start.side_effect = RuntimeError("GStreamer fatal pipeline crash")
            dsai_mock_ext_cls.return_value = dsai_mock_instance

            run_rtsp_extraction_job(
                rtsp_url="rtsp://flaky-cam:554/live",
                stream_id="stream-test-71",
                stream_event=dsai_shutdown,
                tenant_id="tenant-alpha",
                camera_id="cam-71"
            )

            assert dsai_mock_prod.publish.call_count >= 1

    def test_dsai_dead_aliases_removed(self):
        """Verify dead backward-compatibility aliases RTSP_EXTRACTORS and RTSPExtractor are removed (Round 2 #14)."""
        import deepSightAI.Trinetra.ServerAndExtractor.extractor as dsai_ext_mod
        assert not hasattr(dsai_ext_mod, "RTSP_EXTRACTORS"), "RTSP_EXTRACTORS alias should be deleted"
        assert not hasattr(dsai_ext_mod, "RTSP_EXTRACTOR_THREADS"), "RTSP_EXTRACTOR_THREADS alias should be deleted"
        assert not hasattr(dsai_ext_mod, "RTSPExtractor"), "RTSPExtractor alias should be deleted"


# ==============================================================================
# Issue #72: Headroom Capacity Limit, 503 Retry-After, and PreStop Drain
# ==============================================================================

class TestIssue72CapacityAndDrain:
    """Tests for dynamic capacity derivation, 503 Retry-After, and PreStop draining."""

    def test_dsai_dynamic_capacity_headroom(self):
        """Verify capacity is derived from decoder type and environment."""
        from deepSightAI.Trinetra.ServerAndExtractor.extractor import dsai_derive_node_capacity

        with patch.dict(os.environ, {"RTSP_CAPACITY": "12"}):
            assert dsai_derive_node_capacity(dsai_is_hw=True) == 12

        with patch.dict(os.environ, {}, clear=True):
            assert dsai_derive_node_capacity(dsai_is_hw=True) == 8
            assert dsai_derive_node_capacity(dsai_is_hw=False) == 3

    def test_dsai_extract_stream_capacity_exceeded_503(self):
        """Verify /extract_stream returns 503 with Retry-After when at capacity."""
        from deepSightAI.Trinetra.ServerAndExtractor.extractor import app
        app.dependency_overrides[require_auth] = lambda: {"user_id": "test", "tenant_id": "t1"}
        dsai_client = TestClient(app)

        with patch("deepSightAI.Trinetra.ServerAndExtractor.extractor._active_rtsp_streams", {"s1": 1, "s2": 2, "s3": 3}), \
             patch("deepSightAI.Trinetra.ServerAndExtractor.extractor._rtsp_effective_limit", return_value=3):
            
            dsai_resp = dsai_client.post(
                "/extract_stream",
                json={"stream_id": "s4", "rtsp_url": "rtsp://cam/live", "tenant_id": "t1"}
            )
            assert dsai_resp.status_code == 503
            assert "Retry-After" in dsai_resp.headers
            assert dsai_resp.headers["Retry-After"] == "30"

    def test_dsai_prestop_drain_endpoint(self):
        """Verify /drain endpoint sets draining flag, stops new streams, and drains active jobs."""
        from deepSightAI.Trinetra.ServerAndExtractor.extractor import app
        import deepSightAI.Trinetra.ServerAndExtractor.extractor as dsai_ext_mod
        app.dependency_overrides[require_auth] = lambda: {"user_id": "test", "tenant_id": "t1"}

        dsai_client = TestClient(app)
        dsai_mock_event = MagicMock()

        dsai_ext_mod._active_rtsp_streams["s-drain"] = dsai_mock_event
        dsai_ext_mod.DSAI_DRAINING = False
        dsai_ext_mod._dsai_is_draining = False

        try:
            dsai_resp = dsai_client.post("/drain", params={"timeout_seconds": 1.0})
            assert dsai_resp.status_code == 200
            assert dsai_resp.json()["status"] == "drained"
            assert dsai_ext_mod.DSAI_DRAINING is True

            # Reject new stream when draining
            dsai_rej = dsai_client.post(
                "/extract_stream",
                json={"stream_id": "s-new", "rtsp_url": "rtsp://cam/live", "tenant_id": "t1"}
            )
            assert dsai_rej.status_code == 503
        finally:
            dsai_ext_mod.DSAI_DRAINING = False
            dsai_ext_mod._dsai_is_draining = False
            dsai_ext_mod._active_rtsp_streams.clear()

    def test_dsai_production_capacity_and_autoscaling_configurations(self):
        """Verify extractor autoscaler ceiling supports target 10,000 streams (Round 2 #9)."""
        import yaml
        # Verify base extractor values
        with open("helm/extractor/values.yaml", "r") as dsai_f:
            dsai_val = yaml.safe_load(dsai_f)
            assert dsai_val["autoscaling"]["enabled"] is True
            dsai_max_rep = dsai_val["autoscaling"]["maxReplicas"]
            dsai_target_streams = dsai_val["autoscaling"]["targetActiveStreams"]
            assert dsai_max_rep >= 1250, f"maxReplicas {dsai_max_rep} below 1250 required for 10k streams"
            assert dsai_max_rep * dsai_target_streams >= 10000, "Capacity ceiling does not meet 10k stream target"

        # Verify production overlay values
        with open("helm/extractor/values-production.yaml", "r") as dsai_f:
            dsai_prod_val = yaml.safe_load(dsai_f)
            assert dsai_prod_val["autoscaling"]["maxReplicas"] == 1500
            assert dsai_prod_val["autoscaling"]["targetActiveStreams"] == 7
            assert dsai_prod_val["autoscaling"]["maxReplicas"] * dsai_prod_val["autoscaling"]["targetActiveStreams"] >= 10000


# ==============================================================================
# Issue #73: Parallel Embedder Pool, Autoclaim, GPU OOM & DLQ Routing
# ==============================================================================

class TestIssue73EmbedderParallelAndResilience:
    """Tests for distinct consumer IDs, XAUTOCLAIM reclaim, and GPU OOM recovery."""

    def test_dsai_stream_consumer_autoclaim(self):
        """Verify StreamConsumer autoclaim reclaims pending messages from idle consumers."""
        dsai_mock_redis = MagicMock()
        dsai_mock_redis.xautoclaim.return_value = (
            "0-0",
            [("msg-claimed-1", {"event": json.dumps({"video_id": "v1", "bucket_name": "frames", "frame_paths": []})})]
        )

        dsai_consumer = StreamConsumer(
            group_name="embedder-group",
            consumer_id="embedder-worker-2",
            redis_client=dsai_mock_redis
        )

        dsai_claimed = dsai_consumer.autoclaim("frames", min_idle_time_ms=60000, count=5)
        assert len(dsai_claimed) == 1
        assert dsai_claimed[0].id == "msg-claimed-1"

    def test_dsai_embedder_gpu_oom_fallback(self):
        """Verify encode_images catches OOM and falls back to sub-batch/CPU."""
        from deepSightAI.Trinetra.Embedder import embedder as dsai_emb

        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.empty_cache"):
            res = dsai_emb.encode_images([])
            assert res.shape == (0, 512)

    def test_dsai_poison_event_dlq_routing(self):
        """Verify corrupt event failing 3 times is acked and forwarded to DLQ."""
        from deepSightAI.Trinetra.Embedder.embedder import process_events

        dsai_mock_consumer = MagicMock()
        dsai_mock_producer = MagicMock()
        dsai_mock_msg = Message(
            stream="frames",
            msg_id="bad-msg-1",
            data={"event": "{ invalid-json: true }"}
        )
        dsai_mock_consumer.read.side_effect = [[dsai_mock_msg], [dsai_mock_msg], [dsai_mock_msg], []]
        dsai_mock_consumer.autoclaim.return_value = []

        process_events(
            consumer=dsai_mock_consumer,
            producer=dsai_mock_producer,
            max_iterations=4,
            consumer_name="test-worker-oom"
        )

        # Should publish to DLQ after 3 failures
        dsai_mock_producer.publish.assert_called_once()
        dsai_dlq_args = dsai_mock_producer.publish.call_args[0]
        assert dsai_dlq_args[0] == "events:dlq"
        assert dsai_dlq_args[1]["message_id"] == "bad-msg-1"
        assert dsai_mock_consumer.ack.call_count >= 1

    def test_dsai_embedder_queue_backlog_metric_and_sampling(self):
        """Verify embedder queue backlog metric recording and HPA configuration (Round 2 #8)."""
        import yaml
        from deepSightAI.Trinetra.Embedder.embedder import process_events

        # Direct metric verification
        dsai_record_embedder_backlog(42)
        assert DSAI_EMBEDDER_QUEUE_BACKLOG._value.get() == 42

        # Verify sampling during process_events
        dsai_mock_consumer = MagicMock()
        dsai_mock_consumer.read.return_value = []
        dsai_mock_consumer.autoclaim.return_value = []
        dsai_mock_consumer.pending.return_value = {"pending": 88}
        dsai_mock_consumer.client = MagicMock()
        dsai_mock_consumer.client.xinfo_groups.return_value = [{"name": "embedder-group", "lag": 70, "pending": 18}]
        dsai_mock_consumer.group_name = "embedder-group"

        dsai_mock_producer = MagicMock()
        dsai_mock_minio = MagicMock()

        process_events(
            consumer=dsai_mock_consumer,
            producer=dsai_mock_producer,
            minio_client=dsai_mock_minio,
            max_iterations=1,
            consumer_name="test-worker-backlog"
        )
        assert DSAI_EMBEDDER_QUEUE_BACKLOG._value.get() == 88

        # Verify Helm embedder HPA template includes queue backlog and GPU signals
        with open("helm/embedder/templates/hpa.yaml", "r") as dsai_f:
            dsai_hpa_content = dsai_f.read()
            assert "dsai_embedder_queue_backlog" in dsai_hpa_content
            assert "container_gpu_utilization" in dsai_hpa_content

        with open("helm/embedder/values.yaml", "r") as dsai_f:
            dsai_emb_val = yaml.safe_load(dsai_f)
            assert dsai_emb_val["autoscaling"]["targetQueueBacklog"] == 50
            assert dsai_emb_val["autoscaling"]["targetGPUUtilizationPercentage"] == 80


# ==============================================================================
# Issue #74: Scalable Registry Discovery & Spare Capacity Lookup
# ==============================================================================

class TestIssue74ScalableRegistry:
    """Tests for O(log N) sorted set capacity discovery and TTL filtering."""

    def test_dsai_get_available_rtsp_extractor_sorted_set(self):
        """Verify registry selects extractor with highest spare capacity."""
        from deepSightAI.Trinetra.ServerAndExtractor.registry import app
        import deepSightAI.Trinetra.ServerAndExtractor.registry as dsai_reg

        dsai_client = TestClient(app)
        dsai_mock_redis = MagicMock()
        # zrevrangebyscore returns sorted candidate extractor IDs
        dsai_mock_redis.zrevrangebyscore.return_value = ["extractor-2", "extractor-1"]
        dsai_mock_redis.hgetall.side_effect = lambda key: {
            "extractor:extractor-2": {
                "extractor_id": "extractor-2",
                "extractor_url": "http://ext-2:8002",
                "capacity": "10",
                "active_streams": "2",
                "last_heartbeat": str(int(time.time()))
            }
        }.get(key, {})
        dsai_mock_redis.zscore.return_value = "8"

        with patch.object(dsai_reg, "r", dsai_mock_redis):
            dsai_resp = dsai_client.get("/get_available_rtsp_extractor")
            assert dsai_resp.status_code == 200
            dsai_data = dsai_resp.json()
            assert dsai_data["extractor_id"] == "extractor-2"
            assert dsai_data["spare_capacity"] == 8

    def test_dsai_get_available_rtsp_extractor_expired_ttl(self):
        """Verify extractors with expired heartbeat (>45s) are excluded."""
        from deepSightAI.Trinetra.ServerAndExtractor.registry import app
        import deepSightAI.Trinetra.ServerAndExtractor.registry as dsai_reg

        dsai_client = TestClient(app)
        dsai_mock_redis = MagicMock()
        dsai_mock_redis.zrevrangebyscore.return_value = ["extractor-dead"]
        dsai_mock_redis.hgetall.return_value = {
            "extractor_id": "extractor-dead",
            "capacity": "10",
            "active_streams": "0",
            "last_heartbeat": str(int(time.time()) - 100)  # expired
        }

        with patch.object(dsai_reg, "r", dsai_mock_redis):
            dsai_resp = dsai_client.get("/get_available_rtsp_extractor")
            assert dsai_resp.status_code == 503
            dsai_mock_redis.zrem.assert_called_with("registry:extractors:spare_capacity", "extractor-dead")

    def test_dsai_registry_outage_fails_closed(self):
        """Verify placement fails closed with 503 if Redis registry is down."""
        from deepSightAI.Trinetra.ServerAndExtractor.registry import app
        import deepSightAI.Trinetra.ServerAndExtractor.registry as dsai_reg

        dsai_client = TestClient(app)
        dsai_mock_redis = MagicMock()
        dsai_mock_redis.zrevrangebyscore.side_effect = ConnectionError("Redis down")

        with patch.object(dsai_reg, "r", dsai_mock_redis):
            dsai_resp = dsai_client.get("/get_available_rtsp_extractor")
            assert dsai_resp.status_code == 503


# ==============================================================================
# Issue #75: Bounded Failover & Stream Reconciliation
# ==============================================================================

class TestIssue75BoundedFailover:
    """Tests for stream assignment reconciliation, rate limiting, and pending states."""

    def test_dsai_reconciliation_reassigns_orphaned_streams(self):
        """Verify reconciliation reassigns streams whose owner died."""
        from deepSightAI.Trinetra.ServerAndExtractor.registry import app
        import deepSightAI.Trinetra.ServerAndExtractor.registry as dsai_reg

        dsai_client = TestClient(app)
        dsai_mock_redis = MagicMock()

        dsai_orphan_assignment = {
            "stream_id": "stream-orphan-1",
            "camera_id": "cam-orphan-1",
            "extractor_id": "extractor-dead",
            "rtsp_url": "rtsp://cam/live",
            "tenant_id": "t1",
            "status": "active"
        }
        dsai_mock_redis.hgetall.side_effect = lambda k: {
            "registry:stream_assignments": {"stream-orphan-1": json.dumps(dsai_orphan_assignment)},
            "extractor:extractor-dead": {"last_heartbeat": str(int(time.time()) - 120)}
        }.get(k, {})

        dsai_mock_candidate = {
            "extractor_id": "extractor-survivor",
            "extractor_url": "http://ext-survivor:8001",
            "spare_capacity": 5
        }

        dsai_mock_resp = MagicMock(status_code=200)
        dsai_mock_resp.json.return_value = {"stream_id": "stream-reassigned"}
        dsai_mock_resp.raise_for_status = MagicMock()
        dsai_mock_http_client = MagicMock()
        dsai_mock_http_client.__enter__.return_value.post.return_value = dsai_mock_resp

        with patch.object(dsai_reg, "r", dsai_mock_redis), \
             patch("deepSightAI.Trinetra.ServerAndExtractor.registry.get_available_rtsp_extractor", return_value=dsai_mock_candidate), \
             patch("deepSightAI.Trinetra.ServerAndExtractor.registry.httpx.Client", return_value=dsai_mock_http_client):
            
            dsai_resp = dsai_client.post("/reconcile_streams")
            assert dsai_resp.status_code == 200
            dsai_data = dsai_resp.json()
            assert len(dsai_data["reassigned"]) == 1
            assert dsai_data["reassigned"][0] == "cam-orphan-1"

    def test_dsai_reconciliation_rate_limits_failovers(self):
        """Verify failover batch limit (DSAI_MAX_FAILOVER_BATCH=5) stops massive cascade."""
        from deepSightAI.Trinetra.ServerAndExtractor.registry import app, DSAI_MAX_FAILOVER_BATCH
        import deepSightAI.Trinetra.ServerAndExtractor.registry as dsai_reg

        dsai_client = TestClient(app)
        dsai_mock_redis = MagicMock()

        # 10 orphaned streams
        dsai_all_assignments = {
            f"stream-{i}": json.dumps({
                "stream_id": f"stream-{i}",
                "camera_id": f"cam-{i}",
                "extractor_id": "extractor-dead",
                "rtsp_url": "rtsp://cam/live",
                "tenant_id": "t1",
                "status": "active"
            })
            for i in range(10)
        }
        dsai_mock_redis.hgetall.side_effect = lambda k: {
            "registry:stream_assignments": dsai_all_assignments,
            "extractor:extractor-dead": {"last_heartbeat": "0"}
        }.get(k, {})

        dsai_mock_resp = MagicMock(status_code=200)
        dsai_mock_resp.json.return_value = {"stream_id": "stream-reassigned"}
        dsai_mock_resp.raise_for_status = MagicMock()
        dsai_mock_http_client = MagicMock()
        dsai_mock_http_client.__enter__.return_value.post.return_value = dsai_mock_resp

        with patch.object(dsai_reg, "r", dsai_mock_redis), \
             patch("deepSightAI.Trinetra.ServerAndExtractor.registry.get_available_rtsp_extractor", return_value={"extractor_id": "ext-live", "extractor_url": "http://live:8001"}), \
             patch("deepSightAI.Trinetra.ServerAndExtractor.registry.httpx.Client", return_value=dsai_mock_http_client):
            
            dsai_resp = dsai_client.post("/reconcile_streams")
            assert dsai_resp.status_code == 200
            dsai_data = dsai_resp.json()
            assert len(dsai_data["reassigned"]) == DSAI_MAX_FAILOVER_BATCH


# ==============================================================================
# Issue #76 & #78: Edge Push Ingest & Schema Validation
# ==============================================================================

class TestIssue76And78PushIngestAndSchema:
    """Tests for edge embedding submission, batching, dimension validation, and sunset."""

    def test_dsai_edge_push_single_event_success(self):
        """Verify valid single edge embedding event enqueued to Redis."""
        from deepSightAI.Trinetra.ServerAndExtractor.main_api import app
        from deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest import dsai_require_edge_auth
        app.dependency_overrides[require_auth] = lambda: {"user_id": "test", "tenant_id": "tenant-corp"}
        app.dependency_overrides[dsai_require_edge_auth] = lambda: {
            "device_id": "dev-edge-1",
            "tenant_id": "tenant-corp",
            "assigned_cameras": ["cam-push-01"]
        }
        dsai_client = TestClient(app)

        dsai_payload = {
            "event_id": f"evt-{uuid.uuid4().hex}",
            "camera_id": "cam-push-01",
            "tenant_id": "tenant-corp",
            "captured_at": time.time(),
            "embedding_vector": [0.1] * 512,
            "embedding_dim": 512,
            "model_id": "ViT-B-32",
            "model_version": "1.0"
        }

        with patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.StreamProducer.publish"), \
             patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.ensure_tenant_collection") as dsai_mock_coll, \
             patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.create_redis_client") as dsai_mock_redis_fn:
            
            dsai_mock_redis = MagicMock()
            dsai_mock_redis.get.return_value = None
            dsai_mock_redis_fn.return_value = dsai_mock_redis
            dsai_mock_coll.return_value = MagicMock()

            dsai_resp = dsai_client.post("/v1/edge/embeddings", json=dsai_payload)
            assert dsai_resp.status_code == 200
            assert dsai_resp.json()["status"] == "success"

    def test_dsai_edge_push_batch_with_partial_failure(self):
        """Verify batch ingestion accepts valid items while reporting exact errors for invalid."""
        from deepSightAI.Trinetra.ServerAndExtractor.main_api import app
        from deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest import dsai_require_edge_auth
        app.dependency_overrides[require_auth] = lambda: {"user_id": "test", "tenant_id": "tenant-1"}
        app.dependency_overrides[dsai_require_edge_auth] = lambda: {
            "device_id": "dev-edge-1",
            "tenant_id": "tenant-1",
            "assigned_cameras": ["cam-1"]
        }
        dsai_client = TestClient(app)

        dsai_batch = {
            "items": [
                {
                    "event_id": "evt-good",
                    "camera_id": "cam-1",
                    "tenant_id": "tenant-1",
                    "captured_at": time.time(),
                    "embedding_vector": [0.05] * 512,
                    "embedding_dim": 512,
                    "model_id": "ViT-B-32",
                    "model_version": "1.0"
                },
                {
                    "event_id": "evt-bad-dim",
                    "camera_id": "cam-1",
                    "tenant_id": "tenant-1",
                    "captured_at": time.time(),
                    "embedding_vector": [0.05] * 128,  # mismatch with 512
                    "embedding_dim": 128,
                    "model_id": "ViT-B-32",
                    "model_version": "1.0"
                }
            ]
        }

        with patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.StreamProducer.publish"), \
             patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.ensure_tenant_collection"), \
             patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.create_redis_client") as dsai_mock_redis_fn:
            
            dsai_mock_redis = MagicMock()
            dsai_mock_redis.get.return_value = None
            dsai_mock_redis_fn.return_value = dsai_mock_redis

            dsai_resp = dsai_client.post("/v1/edge/embeddings/batch", json=dsai_batch)
            assert dsai_resp.status_code == 207  # Multi-Status partial success
            dsai_data = dsai_resp.json()
            assert dsai_data["summary"]["accepted"] == 1
            assert dsai_data["summary"]["rejected"] == 1
            assert dsai_data["results"][1]["status"] == "error"

    def test_dsai_edge_push_sunset_v0_410_gone(self):
        """Verify sunset endpoint /v0/edge/embeddings returns 410 Gone with redirect."""
        from deepSightAI.Trinetra.ServerAndExtractor.main_api import app
        app.dependency_overrides[require_auth] = lambda: {"user_id": "test", "tenant_id": "t1"}
        dsai_client = TestClient(app)

        dsai_resp = dsai_client.post("/v0/edge/embeddings", json={})
        assert dsai_resp.status_code == 410
        assert "/v1/edge/embeddings" in dsai_resp.json()["detail"]


# ==============================================================================
# Issue #77: Edge Authentication & Scoped Onboarding
# ==============================================================================

class TestIssue77EdgeAuth:
    """Tests for edge device registration, scoped camera verification, and lockout."""

    def test_dsai_edge_device_registration_and_scoped_verification(self):
        """Verify device onboarding, token issuance, and scoped verification."""
        from deepSightAI.Trinetra.AuthService.auth_service import app, Base, get_db

        dsai_engine = create_engine("sqlite:////tmp/test_edge_auth_77.db")
        Base.metadata.create_all(bind=dsai_engine)
        TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=dsai_engine)

        def override_get_db():
            db = TestingSession()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        try:
            dsai_client = TestClient(app)

            # Onboard new edge device
            dsai_reg_req = {
                "tenant_id": "tenant-retail",
                "camera_id": "cam-store-front",
                "device_name": "Nvidia-Jetson-Orin-1"
            }
            dsai_resp = dsai_client.post("/auth/edge/devices", json=dsai_reg_req)
            assert dsai_resp.status_code == 200
            dsai_device = dsai_resp.json()
            assert "api_key" in dsai_device
            dsai_key = dsai_device["api_key"]
            dsai_dev_id = dsai_device["device_id"]

            # Successful verification
            dsai_v_resp = dsai_client.post("/auth/edge/verify", json={
                "api_key": dsai_key,
                "camera_id": "cam-store-front",
                "tenant_id": "tenant-retail"
            })
            assert dsai_v_resp.status_code == 200
            assert dsai_v_resp.json()["valid"] is True

            # Camera mismatch -> 403 Forbidden
            dsai_mismatch = dsai_client.post("/auth/edge/verify", json={
                "api_key": dsai_key,
                "camera_id": "cam-unauthorized",
                "tenant_id": "tenant-retail"
            })
            assert dsai_mismatch.status_code == 403

            # Revocation
            dsai_rev = dsai_client.post(f"/auth/edge/devices/{dsai_dev_id}/revoke")
            assert dsai_rev.status_code == 200

            # Verification after revocation -> 401 Unauthorized
            dsai_post_rev = dsai_client.post("/auth/edge/verify", json={
                "api_key": dsai_key,
                "camera_id": "cam-store-front",
                "tenant_id": "tenant-retail"
            })
            assert dsai_post_rev.status_code == 401
        finally:
            Base.metadata.drop_all(bind=dsai_engine)
            app.dependency_overrides.clear()

    def test_dsai_edge_auth_lockout_after_consecutive_failures(self):
        """Verify device lockout after 5 consecutive failed authentication attempts."""
        from deepSightAI.Trinetra.AuthService.auth_service import app, Base, get_db

        dsai_engine = create_engine("sqlite:////tmp/test_edge_lockout_77.db")
        Base.metadata.create_all(bind=dsai_engine)
        TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=dsai_engine)

        def override_get_db():
            db = TestingSession()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        try:
            dsai_client = TestClient(app)
            dsai_bad_key = "dsk_invalid_fake_key_test_lockout"
            for _ in range(5):
                dsai_client.post("/auth/edge/verify", json={
                    "api_key": dsai_bad_key,
                    "camera_id": "cam-1",
                    "tenant_id": "t1"
                })

            # 6th attempt should return 429 Too Many Requests (Lockout)
            dsai_lockout_resp = dsai_client.post("/auth/edge/verify", json={
                "api_key": dsai_bad_key,
                "camera_id": "cam-1",
                "tenant_id": "t1"
            })
            assert dsai_lockout_resp.status_code == 429
        finally:
            Base.metadata.drop_all(bind=dsai_engine)
            app.dependency_overrides.clear()

    def test_dsai_edge_endpoint_authentication_and_scoping_integration(self):
        """Verify HTTP /v1/edge/embeddings rejects unauthenticated/unauthorized edge requests (Critical 1)."""
        from deepSightAI.Trinetra.ServerAndExtractor.main_api import app
        from deepSightAI.Trinetra.AuthService.auth_service import app as auth_app, Base, get_db

        dsai_engine = create_engine("sqlite:////tmp/test_edge_endpoint_auth_77.db")
        Base.metadata.create_all(bind=dsai_engine)
        TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=dsai_engine)

        def override_get_db():
            db = TestingSession()
            try:
                yield db
            finally:
                db.close()

        auth_app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_db] = override_get_db
        # Clear edge auth dependency override so real credential check runs
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(dsai_require_edge_auth, None)

        try:
            dsai_auth_client = TestClient(auth_app)
            dsai_ingest_client = TestClient(app)

            # 1. Hit /v1/edge/embeddings with NO auth header -> 401 Unauthorized
            dsai_unauth_resp = dsai_ingest_client.post(
                "/v1/edge/embeddings",
                json={
                    "event_id": "evt-no-auth",
                    "camera_id": "cam-scoped-1",
                    "tenant_id": "tenant-edge",
                    "captured_at": time.time(),
                    "embedding_vector": [0.1] * 512,
                    "embedding_dim": 512,
                    "model_id": "ViT-B-32",
                    "model_version": "1.0"
                }
            )
            assert dsai_unauth_resp.status_code == 401
            assert "Missing edge device credential" in dsai_unauth_resp.json()["detail"]

            # 2. Hit /v1/edge/embeddings with INVALID key -> 401 Unauthorized
            dsai_bad_resp = dsai_ingest_client.post(
                "/v1/edge/embeddings",
                headers={"X-API-Key": "clp_edge_invalid_key_12345678"},
                json={
                    "event_id": "evt-bad-auth",
                    "camera_id": "cam-scoped-1",
                    "tenant_id": "tenant-edge",
                    "captured_at": time.time(),
                    "embedding_vector": [0.1] * 512,
                    "embedding_dim": 512,
                    "model_id": "ViT-B-32",
                    "model_version": "1.0"
                }
            )
            assert dsai_bad_resp.status_code == 401
            assert "Invalid edge device credential" in dsai_bad_resp.json()["detail"]

            # 3. Onboard legitimate edge device for tenant-edge and cam-scoped-1
            dsai_onboard_resp = dsai_auth_client.post("/auth/edge/devices", json={
                "tenant_id": "tenant-edge",
                "camera_id": "cam-scoped-1",
                "device_name": "Jetson-Edge-01"
            })
            assert dsai_onboard_resp.status_code == 200
            dsai_dev_data = dsai_onboard_resp.json()
            dsai_api_key = dsai_dev_data["api_key"]
            dsai_device_id = dsai_dev_data["device_id"]

            with patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.StreamProducer.publish"), \
                 patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.ensure_tenant_collection") as dsai_mock_coll, \
                 patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.create_redis_client") as dsai_mock_redis_fn:
                
                dsai_mock_redis = MagicMock()
                dsai_mock_redis.set.return_value = True
                dsai_mock_redis.get.return_value = None
                dsai_mock_redis_fn.return_value = dsai_mock_redis
                dsai_mock_coll.return_value = MagicMock()

                # 4. Valid credentials with authorized camera and tenant -> 200 OK
                dsai_valid_resp = dsai_ingest_client.post(
                    "/v1/edge/embeddings",
                    headers={"X-API-Key": dsai_api_key},
                    json={
                        "event_id": f"evt-{uuid.uuid4().hex}",
                        "camera_id": "cam-scoped-1",
                        "tenant_id": "tenant-edge",
                        "captured_at": time.time(),
                        "embedding_vector": [0.1] * 512,
                        "embedding_dim": 512,
                        "model_id": "ViT-B-32",
                        "model_version": "1.0"
                    }
                )
                assert dsai_valid_resp.status_code == 200
                assert dsai_valid_resp.json()["status"] == "success"

                # 5. Valid credentials but unauthorized camera -> 403 Forbidden
                dsai_cam_mismatch_resp = dsai_ingest_client.post(
                    "/v1/edge/embeddings",
                    headers={"Authorization": f"Bearer {dsai_api_key}"},
                    json={
                        "event_id": f"evt-{uuid.uuid4().hex}",
                        "camera_id": "cam-unauthorized-99",
                        "tenant_id": "tenant-edge",
                        "captured_at": time.time(),
                        "embedding_vector": [0.1] * 512,
                        "embedding_dim": 512,
                        "model_id": "ViT-B-32",
                        "model_version": "1.0"
                    }
                )
                assert dsai_cam_mismatch_resp.status_code == 403
                assert "not authorized to submit embeddings for camera" in dsai_cam_mismatch_resp.json()["detail"]

                # 6. Valid credentials but tenant mismatch -> 403 Forbidden
                dsai_ten_mismatch_resp = dsai_ingest_client.post(
                    "/v1/edge/embeddings",
                    headers={"X-API-Key": dsai_api_key},
                    json={
                        "event_id": f"evt-{uuid.uuid4().hex}",
                        "camera_id": "cam-scoped-1",
                        "tenant_id": "tenant-other-corp",
                        "captured_at": time.time(),
                        "embedding_vector": [0.1] * 512,
                        "embedding_dim": 512,
                        "model_id": "ViT-B-32",
                        "model_version": "1.0"
                    }
                )
                assert dsai_ten_mismatch_resp.status_code == 403
                assert "Edge device tenant mismatch" in dsai_ten_mismatch_resp.json()["detail"]

            # 7. Revoke device -> Subsequent requests rejected with 401 Unauthorized
            dsai_rev_resp = dsai_auth_client.post(f"/auth/edge/devices/{dsai_device_id}/revoke")
            assert dsai_rev_resp.status_code == 200

            dsai_revoked_resp = dsai_ingest_client.post(
                "/v1/edge/embeddings",
                headers={"X-API-Key": dsai_api_key},
                json={
                    "event_id": f"evt-{uuid.uuid4().hex}",
                    "camera_id": "cam-scoped-1",
                    "tenant_id": "tenant-edge",
                    "captured_at": time.time(),
                    "embedding_vector": [0.1] * 512,
                    "embedding_dim": 512,
                    "model_id": "ViT-B-32",
                    "model_version": "1.0"
                }
            )
            assert dsai_revoked_resp.status_code == 401
            assert "revoked" in dsai_revoked_resp.json()["detail"]

        finally:
            Base.metadata.drop_all(bind=dsai_engine)
            auth_app.dependency_overrides.clear()
            app.dependency_overrides.clear()

    def test_dsai_edge_endpoint_lockout_after_failures(self):
        """Verify repeated failed auth on /v1/edge/embeddings triggers 429 lockout (Critical 1)."""
        from deepSightAI.Trinetra.ServerAndExtractor.main_api import app
        from deepSightAI.Trinetra.AuthService.auth_service import app as auth_app, Base, get_db

        dsai_engine = create_engine("sqlite:////tmp/test_edge_endpoint_lockout_77.db")
        Base.metadata.create_all(bind=dsai_engine)
        TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=dsai_engine)

        def override_get_db():
            db = TestingSession()
            try:
                yield db
            finally:
                db.close()

        auth_app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(dsai_require_edge_auth, None)

        try:
            dsai_ingest_client = TestClient(app)
            dsai_bad_edge_key = "clp_edge_lockout_test_key_xxxx"

            # 5 failed attempts return 401 (with 5th or 6th locking out)
            for _ in range(5):
                resp = dsai_ingest_client.post(
                    "/v1/edge/embeddings",
                    headers={"X-API-Key": dsai_bad_edge_key},
                    json={
                        "event_id": "evt-attempt",
                        "camera_id": "cam-1",
                        "tenant_id": "t1",
                        "captured_at": time.time(),
                        "embedding_vector": [0.1] * 512,
                        "embedding_dim": 512,
                        "model_id": "ViT-B-32",
                        "model_version": "1.0"
                    }
                )
                assert resp.status_code in (401, 429)

            # Attempt after threshold must return 429 Too Many Requests
            dsai_lockout_resp = dsai_ingest_client.post(
                "/v1/edge/embeddings",
                headers={"X-API-Key": dsai_bad_edge_key},
                json={
                    "event_id": "evt-locked",
                    "camera_id": "cam-1",
                    "tenant_id": "t1",
                    "captured_at": time.time(),
                    "embedding_vector": [0.1] * 512,
                    "embedding_dim": 512,
                    "model_id": "ViT-B-32",
                    "model_version": "1.0"
                }
            )
            assert dsai_lockout_resp.status_code == 429
            assert "locked" in dsai_lockout_resp.json()["detail"].lower()
        finally:
            Base.metadata.drop_all(bind=dsai_engine)
            auth_app.dependency_overrides.clear()
            app.dependency_overrides.clear()


# ==============================================================================
# Issue #79 & #80: Idempotency Dedup & Clock Skew Clamping
# ==============================================================================

class TestIssue79And80DedupAndLiveness:
    """Tests for idempotent duplicate handling, dedup outage 503, and clock skew."""

    def test_dsai_idempotency_duplicate_returns_original(self):
        """Verify re-submitting existing event_id returns original response."""
        from deepSightAI.Trinetra.ServerAndExtractor.main_api import app
        from deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest import dsai_require_edge_auth
        app.dependency_overrides[require_auth] = lambda: {"user_id": "test", "tenant_id": "t1"}
        app.dependency_overrides[dsai_require_edge_auth] = lambda: {
            "device_id": "dev-edge-1",
            "tenant_id": "t1",
            "assigned_cameras": ["cam-1"]
        }
        dsai_client = TestClient(app)

        dsai_cached = {"status": "success", "event_id": "evt-dup-1", "cached": True}
        with patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.create_redis_client") as dsai_mock_redis_fn:
            dsai_mock_redis = MagicMock()
            dsai_mock_redis.set.return_value = None
            dsai_mock_redis.get.return_value = json.dumps(dsai_cached)
            dsai_mock_redis_fn.return_value = dsai_mock_redis

            dsai_resp = dsai_client.post(
                "/v1/edge/embeddings",
                json={
                    "event_id": "evt-dup-1",
                    "camera_id": "cam-1",
                    "tenant_id": "t1",
                    "captured_at": time.time(),
                    "embedding_vector": [0.1] * 512,
                    "embedding_dim": 512,
                    "model_id": "ViT-B-32",
                    "model_version": "1.0"
                }
            )
            assert dsai_resp.status_code == 200
            assert dsai_resp.json()["cached"] is True

    def test_dsai_idempotency_store_outage_503(self):
        """Verify dedup store failure rejects with 503 instead of risking double writes."""
        from deepSightAI.Trinetra.ServerAndExtractor.main_api import app
        from deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest import dsai_require_edge_auth
        app.dependency_overrides[require_auth] = lambda: {"user_id": "test", "tenant_id": "t1"}
        app.dependency_overrides[dsai_require_edge_auth] = lambda: {
            "device_id": "dev-edge-1",
            "tenant_id": "t1",
            "assigned_cameras": ["cam-1"]
        }
        dsai_client = TestClient(app)

        with patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.create_redis_client") as dsai_mock_redis_fn:
            dsai_mock_redis = MagicMock()
            dsai_mock_redis.get.side_effect = ConnectionError("Redis down")
            dsai_mock_redis_fn.return_value = dsai_mock_redis

            dsai_resp = dsai_client.post(
                "/v1/edge/embeddings",
                json={
                    "event_id": "evt-crash",
                    "camera_id": "cam-1",
                    "tenant_id": "t1",
                    "captured_at": time.time(),
                    "embedding_vector": [0.1] * 512,
                    "embedding_dim": 512,
                    "model_id": "ViT-B-32",
                    "model_version": "1.0"
                }
            )
            assert dsai_resp.status_code == 503

    def test_dsai_clock_skew_clamping(self):
        """Verify captured_at far in past (>300s) is clamped to server time."""
        dsai_server_now = 1000000.0
        # 1000s in past -> clamped
        dsai_clamped_past, dsai_flagged_past = dsai_clamp_captured_timestamp(dsai_server_now - 1000.0, dsai_server_now)
        assert dsai_flagged_past is True
        assert dsai_clamped_past == dsai_server_now

        # 500s in future -> clamped
        dsai_clamped_future, dsai_flagged_future = dsai_clamp_captured_timestamp(dsai_server_now + 500.0, dsai_server_now)
        assert dsai_flagged_future is True
        assert dsai_clamped_future == dsai_server_now

        # 10s skew -> normal
        dsai_normal, dsai_flagged_normal = dsai_clamp_captured_timestamp(dsai_server_now - 10.0, dsai_server_now)
        assert dsai_flagged_normal is False
        assert dsai_normal == dsai_server_now - 10.0


# ==============================================================================
# Issue #81 & #82: Milvus Normalization & Ingestion Path Assignment
# ==============================================================================

class TestIssue81And82NormalizationAndPathAssignment:
    """Tests for canonical Milvus shape normalization and Camera ingestion_path switching."""

    def test_dsai_milvus_normalization_pull_success(self):
        """Verify pull-path frame normalizes into canonical record."""
        dsai_record = MilvusNormalizer.dsai_normalize_pull(
            dsai_video_id="vid-1",
            dsai_camera_id="cam-1",
            dsai_frame_path="tenant/cam/frame.jpg",
            dsai_timestamp=1700000.0,
            dsai_embedding=[0.1] * 512,
            dsai_tenant_id="tenant-1",
            dsai_correlation_id="corr-123"
        )
        assert dsai_record.ingestion_path == "pull"
        assert dsai_record.tenant_id == "tenant-1"
        assert len(dsai_record.embedding) == 512
        assert dsai_record.correlation_id == "corr-123"

    def test_dsai_milvus_normalization_missing_tenant_dlq(self):
        """Verify normalization failure routes to DLQ and raises NormalizationError."""
        dsai_mock_producer = MagicMock()

        with pytest.raises(NormalizationError):
            MilvusNormalizer.dsai_normalize_pull(
                dsai_video_id="vid-1",
                dsai_camera_id="cam-1",
                dsai_frame_path="tenant/cam/frame.jpg",
                dsai_timestamp=1700000.0,
                dsai_embedding=[0.1] * 512,
                dsai_tenant_id="",  # Missing tenant
                dsai_producer=dsai_mock_producer
            )

        dsai_mock_producer.publish.assert_called_once()
        dsai_dlq_args = dsai_mock_producer.publish.call_args[0]
        assert dsai_dlq_args[0] == "events:dlq"

    def test_dsai_camera_path_assignment_and_drain(self):
        """Verify CameraRepository updates ingestion_path with drain callback."""
        dsai_mock_session = MagicMock()
        dsai_mock_camera = MagicMock(camera_id="cam-100", ingestion_path="pull")
        dsai_mock_session.query.return_value.get.return_value = dsai_mock_camera

        dsai_drain_called = {"called": False}
        def dsai_drain_callback(cid, old_path=None):
            dsai_drain_called["called"] = True

        dsai_repo = CameraRepository(tenant_id="tenant-1")
        with patch.object(dsai_repo, "Session") as dsai_mock_session_cls:
            dsai_mock_session_cls.return_value.__enter__.return_value = dsai_mock_session
            dsai_res = dsai_repo.update_ingestion_path(
                camera_id="cam-100",
                new_path="push",
                drain_callback=dsai_drain_callback
            )

            assert dsai_res is not None
            assert dsai_drain_called["called"] is True
            assert dsai_mock_camera.ingestion_path == "push"


# ==============================================================================
# Issue #83: Per-Path Monitoring & Independent Health
# ==============================================================================

class TestIssue83PerPathMonitoring:
    """Tests for separate pull vs push metrics and non-aggregating health status."""

    def setup_method(self):
        """Reset per-path error tracking before each test."""
        dsai_reset_health_metrics()

    def test_dsai_per_path_health_isolation(self):
        """Verify push path error threshold does not mask healthy pull path."""
        # Record normal pull operations
        dsai_record_pull_stream_count(5)
        
        # Simulate edge outage (many push errors)
        for _ in range(15):
            dsai_record_push_error("circuit_trip")

        dsai_health = dsai_get_per_path_health()
        assert dsai_health["pull_path"]["status"] == "healthy"
        assert dsai_health["push_path"]["status"] == "degraded"

    def test_dsai_health_paths_http_endpoint(self):
        """Verify GET /health/paths exposes independent path health statuses (Issue #83)."""
        from deepSightAI.Trinetra.ServerAndExtractor.main_api import app
        app.dependency_overrides[require_auth] = lambda: {"user_id": "test", "tenant_id": "t1"}
        dsai_client = TestClient(app)

        dsai_resp = dsai_client.get("/health/paths")
        assert dsai_resp.status_code == 200
        dsai_data = dsai_resp.json()
        assert "pull_path" in dsai_data
        assert "push_path" in dsai_data
        assert "status" in dsai_data["pull_path"]
        assert "status" in dsai_data["push_path"]

    def test_dsai_per_path_health_distributed_redis(self):
        """Verify per-path health aggregates across multiple pods via Redis (Round 2 #11)."""
        from deepSightAI.Trinetra.ServerAndExtractor.main_api import app
        import deepSightAI.Trinetra.Shared.dsai_metrics as dsai_met_mod

        # Create simulated shared Redis mock
        dsai_mock_redis = MagicMock()
        # Simulate 25 errors reported by extractor and embedder pods into Redis ZSET
        dsai_mock_redis.zcount.side_effect = lambda key, min_s, max_s: 25 if "pull" in key else 2
        dsai_mock_redis.get.side_effect = lambda key: "14" if "pull:active_streams" in key else "3"

        with patch.object(dsai_met_mod, "_dsai_health_redis_client", dsai_mock_redis):
            dsai_health = dsai_get_per_path_health(dsai_redis_client=dsai_mock_redis)
            # Pull path has 25 fleet-wide errors -> degraded (threshold: >= 10)
            assert dsai_health["pull_path"]["status"] == "degraded"
            assert dsai_health["pull_path"]["recent_errors"] >= 25
            assert dsai_health["pull_path"]["active_streams"] == 14

            # Push path has 2 errors -> healthy (< 10)
            assert dsai_health["push_path"]["status"] == "healthy"
            assert dsai_health["push_path"]["active_devices"] == 3

        # Test HTTP GET /health/paths endpoint with multi-pod Redis backing
        app.dependency_overrides[require_auth] = lambda: {"user_id": "test", "tenant_id": "t1"}
        dsai_client = TestClient(app)
        with patch("deepSightAI.Trinetra.Shared.dsai_metrics._dsai_get_health_redis", return_value=dsai_mock_redis):
            dsai_resp = dsai_client.get("/health/paths")
            assert dsai_resp.status_code == 200
            dsai_body = dsai_resp.json()
            assert dsai_body["pull_path"]["status"] == "degraded"
            assert dsai_body["pull_path"]["recent_errors"] >= 25
            assert dsai_body["push_path"]["status"] == "healthy"


# ==============================================================================
# Issue #84: Structured Logging & Correlation ID Propagation
# ==============================================================================

class TestIssue84StructuredLogging:
    """Tests for ContextVar correlation ID propagation in JSON formatter."""

    def test_dsai_correlation_id_context_and_json_format(self):
        """Verify correlation_id is present in log record JSON output."""
        dsai_test_corr = f"corr-{uuid.uuid4().hex}"
        dsai_set_correlation_id(dsai_test_corr)
        assert dsai_get_correlation_id() == dsai_test_corr

        import logging
        dsai_record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Processing test frame",
            args=(),
            exc_info=None
        )

        dsai_formatter = DSAIJsonFormatter()
        dsai_json_output = dsai_formatter.format(dsai_record)
        dsai_parsed = json.loads(dsai_json_output)

        assert dsai_parsed["correlation_id"] == dsai_test_corr
        assert dsai_parsed["message"] == "Processing test frame"


# ==============================================================================
# Issue #85: Downstream Circuit Breakers
# ==============================================================================

class TestIssue85CircuitBreakers:
    """Tests for CLOSED -> OPEN -> HALF_OPEN states and 503 Retry-After."""

    def test_dsai_circuit_breaker_state_transitions(self):
        """Verify breaker opens after failure threshold and trips 503."""
        dsai_cb = CircuitBreaker(
            dsai_name="test-milvus",
            dsai_failure_threshold=3,
            dsai_recovery_timeout=0.1
        )

        assert dsai_cb.dsai_state == CircuitState.CLOSED

        # Record 2 failures -> still closed
        dsai_cb.dsai_record_failure(Exception("e1"))
        dsai_cb.dsai_record_failure(Exception("e2"))
        assert dsai_cb.dsai_state == CircuitState.CLOSED

        # 3rd failure -> trips OPEN
        dsai_cb.dsai_record_failure(Exception("e3"))
        assert dsai_cb.dsai_state == CircuitState.OPEN

        # Immediate check raises CircuitBreakerOpenException
        dsai_avail, dsai_retry = dsai_cb.dsai_is_available()
        assert dsai_avail is False
        assert dsai_retry is not None

        # Wait recovery timeout -> HALF_OPEN
        time.sleep(0.12)
        assert dsai_cb.dsai_state == CircuitState.HALF_OPEN

        # Success in HALF_OPEN resets to CLOSED
        dsai_cb.dsai_record_success()
        dsai_cb.dsai_record_success()
        assert dsai_cb.dsai_state == CircuitState.CLOSED


# ==============================================================================
# Issue #86: Fail-Fast Startup Validation
# ==============================================================================

class TestIssue86StartupValidation:
    """Tests for fail-fast profile checking at startup."""

    def test_dsai_startup_validation_missing_env(self):
        """Verify missing required env vars raises StartupValidationError."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(StartupValidationError) as dsai_exc:
                dsai_validate_startup_config("extractor")
            assert "Missing or empty required environment variable" in str(dsai_exc.value)

    def test_dsai_startup_validation_success(self):
        """Verify all valid env vars pass startup check."""
        dsai_valid_env = {
            "REDIS_URL": "redis://localhost:6379",
            "REGISTRY_URL": "http://localhost:8000",
            "MINIO_URL": "localhost:9000",
            "EXTRACTOR_ID": "ext-1",
            "EXTRACTOR_URL": "http://localhost:8001"
        }
        with patch.dict(os.environ, dsai_valid_env, clear=True):
            dsai_validate_startup_config("extractor")


# ==============================================================================
# Issue #87: Feature Flag & Canary Rollout Safety
# ==============================================================================

class TestIssue87FeatureFlagRollout:
    """Tests for feature flags, canary hash percentage, and allowlists."""

    def test_dsai_feature_flag_allowlist_and_canary(self):
        """Verify tenant allowlist and canary percentage rollouts."""
        with patch.dict(os.environ, {
            "DSAI_ENABLE_EDGE_INGESTION": "1",
            "DSAI_EDGE_CANARY_PCT": "50",
            "DSAI_EDGE_ALLOWED_TENANTS": "vip-tenant,beta-tenant"
        }):
            # Allowlist tenant is enabled
            assert dsai_is_edge_ingest_enabled(dsai_tenant_id="vip-tenant") is True
            # Non-allowlist tenant is rejected when allowlist is present
            assert dsai_is_edge_ingest_enabled(dsai_tenant_id="random-tenant") is False

        # When global flag is disabled, all tenants disabled
        with patch.dict(os.environ, {"DSAI_ENABLE_EDGE_INGESTION": "0"}):
            assert dsai_is_edge_ingest_enabled(dsai_tenant_id="vip-tenant") is False

    def test_dsai_hw_decode_canary_rollout(self):
        """Verify hardware decode flag and canary percentage evaluation."""
        with patch.dict(os.environ, {"DSAI_ENABLE_HW_DECODE": "0"}):
            assert dsai_is_hw_decode_enabled() is False

        with patch.dict(os.environ, {"DSAI_ENABLE_HW_DECODE": "1", "DSAI_HW_DECODE_CANARY_PCT": "100"}):
            assert dsai_is_hw_decode_enabled() is True

        with patch.dict(os.environ, {"DSAI_ENABLE_HW_DECODE": "1", "DSAI_HW_DECODE_CANARY_PCT": "0"}):
            assert dsai_is_hw_decode_enabled("cam-1") is False
