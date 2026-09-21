"""
Phase 1 Verification Tests (DM-1 to DM-11, REL-51 to REL-57, VP-12 to VP-25, SR-35 to SR-44, UI-82 to UI-93).

Comprehensive test suite verifying Phase 1 Object Search on Stored Video (FP32):
- DM-1 to DM-4: Tenant-isolated Milvus collections, HNSW/COSINE and scalar indexes
- DM-5: Required camera_id at ingestion
- DM-8 & DM-9: Crop persistence gating and fail-closed legal-hold overrides
- DM-10 & DM-11: Schema versioning tag and deterministic video_object_pk
- REL-51 & REL-53: Standardized exceptions and structured JSON logging
- REL-55 to REL-57: Extractor upload retry + DLQ, orphan recording, embedder bounded retry + DLQ
- VP-12 to VP-25: Vision Processing Service, plugins, FP32 Re-ID, durable Milvus write, ObjectDetectedEvent
- SR-35 to SR-44: Unified Search API, RBAC enforcement, vehicle/person search, ceiling limits
- UI-82 to UI-93: Modernized Streamlit UI utilities and contracts
"""

import os
import sys
import json
import time
import uuid
import logging
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, ANY
import pytest
from pydantic import ValidationError as PydanticValidationError

# --- IMPORT MODULES UNDER TEST ---
from deepSightAI.Trinetra.Shared.Errors import (
    TrinetraError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    ValidationError,
    StorageError,
    MinIOError,
    MilvusError,
    StreamingError,
    DeadLetterQueueError,
    RecoverableOrphanError,
    ModelInferenceError,
    ConfigurationError,
    LegalHoldError,
)
from deepSightAI.Trinetra.Shared.LoggingSetup import DSAIJsonFormatter, dsai_setup_logging
from deepSightAI.Trinetra.Shared.Milvus import (
    ensure_tenant_collection,
    ensure_person_collection,
    ensure_vehicle_collection,
    get_person_collection_name,
    get_vehicle_collection_name,
    dsai_generate_video_object_pk,
    dsai_get_milvus_collection_version,
    DSAI_MILVUS_SCHEMA_VERSION,
)
from deepSightAI.Trinetra.Shared.Retention import (
    CropRetentionPolicy,
    DataRetentionManager,
    dsai_crop_policy,
    dsai_retention_manager,
)
from deepSightAI.Trinetra.Shared.Streaming.Schema import FrameReadyEvent, ObjectDetectedEvent
from deepSightAI.Trinetra.ServerAndExtractor.main_api import VideoSourceRequest, RtspSourceRequest
from deepSightAI.Trinetra.ServerAndExtractor.extractor import (
    dsai_upload_frame_with_retry,
    dsai_record_recoverable_orphan,
    DSAI_RECOVERABLE_ORPHANS,
)
from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_plugin_loader import PluginLoader
from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_pp_human import PPHumanPlugin
from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_pp_vehicle import PPVehiclePlugin
from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_vehicle_attributes import PPVehicleAttributePlugin
from deepSightAI.Trinetra.VisionProcessingService.dsai_consumer import VisionProcessingConsumer


# =====================================================================
# 1. DATA MODEL (DM-1, DM-2, DM-3, DM-4, DM-10, DM-11)
# =====================================================================

class TestDM1toDM4MilvusCollections:
    """DM-1 to DM-4: Milvus collections, HNSW vector indexes, and scalar indexes."""

    def test_ensure_person_collection_schema_and_indices(self):
        """Verify video_objects_person collection fields, HNSW index, and scalar indexes."""
        mock_collection_cls = MagicMock()
        mock_instance = MagicMock()
        mock_collection_cls.return_value = mock_instance

        with patch("deepSightAI.Trinetra.Shared.Milvus.connections.has_connection", return_value=True), \
             patch("deepSightAI.Trinetra.Shared.Milvus.utility.has_collection", return_value=False), \
             patch("deepSightAI.Trinetra.Shared.Milvus.Collection", mock_collection_cls):

            coll = ensure_person_collection(tenant_id="tenant_alpha", embedding_dim=256)

            # Collection name format check (DM-1)
            coll_name = get_person_collection_name("tenant_alpha")
            assert coll_name == "video_objects_person_tenant_alpha"
            mock_collection_cls.assert_called_once()
            call_kwargs = mock_collection_cls.call_args[1]
            assert call_kwargs["name"] == "video_objects_person_tenant_alpha"

            # Verify schema fields (DM-1, DM-4)
            schema = call_kwargs["schema"]
            field_names = [f.name for f in schema.fields]
            assert "video_object_pk" in field_names
            assert "tenant_id" in field_names
            assert "camera_id" in field_names
            assert "frame_timestamp" in field_names
            assert "crop_path" in field_names
            assert "has_plate_read" in field_names
            assert "embedding" in field_names

            # Verify primary key
            pk_field = next(f for f in schema.fields if f.name == "video_object_pk")
            assert pk_field.is_primary is True

            # Verify HNSW index created on embedding (DM-2, DM-3)
            create_index_calls = mock_instance.create_index.call_args_list
            embedding_index_call = [c for c in create_index_calls if c[1].get("field_name") == "embedding"]
            assert len(embedding_index_call) >= 1
            index_params = embedding_index_call[0][1]["index_params"]
            assert index_params["metric_type"] == "COSINE"
            assert index_params["index_type"] == "HNSW"
            assert index_params["params"] == {"M": 16, "efConstruction": 200}

            # Verify scalar indexes created (DM-4, DM-2)
            scalar_fields_indexed = [c[1].get("field_name") for c in create_index_calls if c[1].get("field_name") != "embedding"]
            for expected_scalar in ["camera_id", "frame_timestamp", "object_class", "tenant_id", "has_plate_read"]:
                assert expected_scalar in scalar_fields_indexed

    def test_ensure_vehicle_collection_schema_and_indices(self):
        """Verify video_objects_vehicle collection fields, attributes, HNSW, and scalar indexes."""
        mock_collection_cls = MagicMock()
        mock_instance = MagicMock()
        mock_collection_cls.return_value = mock_instance

        with patch("deepSightAI.Trinetra.Shared.Milvus.connections.has_connection", return_value=True), \
             patch("deepSightAI.Trinetra.Shared.Milvus.utility.has_collection", return_value=False), \
             patch("deepSightAI.Trinetra.Shared.Milvus.Collection", mock_collection_cls):

            coll = ensure_vehicle_collection(tenant_id="tenant_beta", embedding_dim=256)

            coll_name = get_vehicle_collection_name("tenant_beta")
            assert coll_name == "video_objects_vehicle_tenant_beta"

            call_kwargs = mock_collection_cls.call_args[1]
            schema = call_kwargs["schema"]
            field_names = [f.name for f in schema.fields]

            # Vehicle specific attribute fields (DM-1)
            assert "color" in field_names
            assert "vehicle_type" in field_names
            assert "has_plate_read" in field_names
            assert "plate_number" in field_names

            # Verify indexes
            create_index_calls = mock_instance.create_index.call_args_list
            embedding_index_call = [c for c in create_index_calls if c[1].get("field_name") == "embedding"]
            assert len(embedding_index_call) >= 1
            assert embedding_index_call[0][1]["index_params"]["metric_type"] == "COSINE"

            scalar_fields_indexed = [c[1].get("field_name") for c in create_index_calls if c[1].get("field_name") != "embedding"]
            for expected_scalar in ["camera_id", "frame_timestamp", "color", "vehicle_type", "has_plate_read"]:
                assert expected_scalar in scalar_fields_indexed

    def test_ensure_tenant_collection_scalar_indexes(self):
        """Verify video_frames collection creates scalar indexes on camera_id, timestamp, tenant_id."""
        mock_collection_cls = MagicMock()
        mock_instance = MagicMock()
        mock_collection_cls.return_value = mock_instance

        with patch("deepSightAI.Trinetra.Shared.Milvus.connections.has_connection", return_value=True), \
             patch("deepSightAI.Trinetra.Shared.Milvus.utility.has_collection", return_value=False), \
             patch("deepSightAI.Trinetra.Shared.Milvus.Collection", mock_collection_cls):

            coll = ensure_tenant_collection(tenant_id="tenant_gamma")
            create_index_calls = mock_instance.create_index.call_args_list
            scalar_fields_indexed = [c[1].get("field_name") for c in create_index_calls if c[1].get("field_name") != "embedding"]
            assert "camera_id" in scalar_fields_indexed
            assert "frame_timestamp" in scalar_fields_indexed
            assert "tenant_id" in scalar_fields_indexed


class TestDM5IngestCameraIdRequired:
    """DM-5: Ingestion endpoints strictly require camera_id."""

    def test_video_source_request_requires_camera_id(self):
        """VideoSourceRequest must reject missing or empty camera_id."""
        with pytest.raises(PydanticValidationError):
            VideoSourceRequest(video_uri="videos/clip1.mp4", tenant_id="t1")

        with pytest.raises(PydanticValidationError):
            VideoSourceRequest(video_uri="videos/clip1.mp4", camera_id="", tenant_id="t1")

        with pytest.raises(PydanticValidationError):
            VideoSourceRequest(video_uri="videos/clip1.mp4", camera_id="   ", tenant_id="t1")

        valid = VideoSourceRequest(video_uri="videos/clip1.mp4", camera_id="cam_entry", tenant_id="t1")
        assert valid.camera_id == "cam_entry"

    def test_rtsp_source_request_requires_camera_id(self):
        """RtspSourceRequest must reject missing or empty camera_id."""
        with pytest.raises(PydanticValidationError):
            RtspSourceRequest(rtsp_url="rtsp://10.0.0.1/live", tenant_id="t1")

        with pytest.raises(PydanticValidationError):
            RtspSourceRequest(rtsp_url="rtsp://10.0.0.1/live", camera_id="", tenant_id="t1")

        valid = RtspSourceRequest(rtsp_url="rtsp://10.0.0.1/live", camera_id="cam_exit", tenant_id="t1")
        assert valid.camera_id == "cam_exit"

    def test_ingest_service_forwards_camera_id(self):
        """Ingest service endpoint forwards camera_id and tenant_id to event stream."""
        from fastapi.testclient import TestClient
        from deepSightAI.Trinetra.ServerAndExtractor.ingest_service import app, get_producer, get_extractor

        mock_producer = MagicMock()
        mock_extractor = {"extractor_url": "http://mock-extractor:8000"}

        app.dependency_overrides[get_producer] = lambda: mock_producer
        app.dependency_overrides[get_extractor] = lambda: mock_extractor

        client = TestClient(app)
        try:
            with patch("deepSightAI.Trinetra.ServerAndExtractor.ingest_service.publish_event") as mock_publish, \
                 patch("deepSightAI.Trinetra.ServerAndExtractor.ingest_service.dispatch_to_extractor") as mock_dispatch:
                payload = {
                    "source_type": "rtsp",
                    "rtsp_url": "rtsp://10.0.0.1/stream",
                    "camera_id": "cam_gate_42",
                    "tenant_id": "tenant_test"
                }
                response = client.post("/ingest", json=payload, headers={"X-Tenant-ID": "tenant_test"})
                assert response.status_code == 200
                data = response.json()
                assert data["camera_id"] == "cam_gate_42"
                assert data["tenant_id"] == "tenant_test"

                # Check published IngestJobStarted event
                mock_publish.assert_called()
                event = mock_publish.call_args[0][1]
                assert event.tenant_id == "tenant_test"
        finally:
            app.dependency_overrides.clear()


class TestDM8andDM9RetentionAndLegalHold:
    """DM-8 & DM-9: Crop persistence gating and legal-hold overrides."""

    def test_crop_retention_policy_confidence_gating(self):
        """Crops below confidence threshold are embedding-only (DM-8)."""
        policy = CropRetentionPolicy(dsai_min_confidence=0.6, dsai_store_crops=True)

        # Confidence >= 0.6: persist crop
        assert policy.should_persist_crop(dsai_object_class="person", dsai_confidence=0.75) is True

        # Confidence < 0.6: embedding only
        assert policy.should_persist_crop(dsai_object_class="person", dsai_confidence=0.45) is False

    def test_crop_retention_policy_class_gating(self):
        """Crops for unconfigured classes are embedding-only (DM-8)."""
        policy = CropRetentionPolicy(dsai_min_confidence=0.5, dsai_persist_classes={"person", "vehicle"})

        assert policy.should_persist_crop(dsai_object_class="vehicle", dsai_confidence=0.8) is True
        assert policy.should_persist_crop(dsai_object_class="backpack", dsai_confidence=0.9) is False

    def test_crop_retention_tenant_override(self):
        """Tenant-specific overrides take precedence (DM-8)."""
        policy = CropRetentionPolicy(dsai_min_confidence=0.5, dsai_store_crops=True)

        tenant_disable = {"store_crops": False}
        assert policy.should_persist_crop("person", 0.9, dsai_tenant_config=tenant_disable) is False

        tenant_strict = {"min_confidence": 0.85}
        assert policy.should_persist_crop("person", 0.70, dsai_tenant_config=tenant_strict) is False
        assert policy.should_persist_crop("person", 0.90, dsai_tenant_config=tenant_strict) is True

    def test_data_retention_expiration_without_legal_hold(self):
        """Standard expiration deletes data past retention period (DM-9)."""
        now = datetime.now(timezone.utc)
        old_record = now - timedelta(days=35)
        new_record = now - timedelta(days=5)

        # 30 day retention policy
        assert DataRetentionManager.evaluate_expiration(old_record, dsai_retention_days=30, dsai_tenant_id="tenant_x", dsai_now=now) is True
        assert DataRetentionManager.evaluate_expiration(new_record, dsai_retention_days=30, dsai_tenant_id="tenant_x", dsai_now=now) is False

    def test_data_retention_fail_closed_with_legal_hold(self):
        """Legal hold PREVENTS deletion even if age far exceeds retention window (DM-9, GOV-1)."""
        tenant = f"tenant_hold_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        very_old = now - timedelta(days=3650)  # 10 years old

        # Without hold -> eligible for deletion
        assert DataRetentionManager.evaluate_expiration(very_old, 30, tenant, dsai_now=now) is True

        # Apply tenant-wide legal hold
        DataRetentionManager.set_legal_hold(tenant, dsai_enabled=True)
        assert DataRetentionManager.is_legal_hold_active(tenant) is True
        # Must FAIL-CLOSED: cannot expire
        assert DataRetentionManager.evaluate_expiration(very_old, 30, tenant, dsai_now=now) is False

        # Release hold -> can expire again
        DataRetentionManager.set_legal_hold(tenant, dsai_enabled=False)
        assert DataRetentionManager.is_legal_hold_active(tenant) is False
        assert DataRetentionManager.evaluate_expiration(very_old, 30, tenant, dsai_now=now) is True

    def test_camera_specific_legal_hold(self):
        """Legal hold applied to a specific camera preserves only that camera (DM-9)."""
        tenant = f"tenant_cam_hold_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        old_record = now - timedelta(days=60)

        # Set hold on cam_vault only
        DataRetentionManager.set_legal_hold(tenant, dsai_camera_id="cam_vault", dsai_enabled=True)

        # cam_vault is protected
        assert DataRetentionManager.evaluate_expiration(old_record, 30, tenant, dsai_camera_id="cam_vault", dsai_now=now) is False
        # cam_lobby is NOT protected
        assert DataRetentionManager.evaluate_expiration(old_record, 30, tenant, dsai_camera_id="cam_lobby", dsai_now=now) is True

        # Clean up
        DataRetentionManager.set_legal_hold(tenant, dsai_camera_id="cam_vault", dsai_enabled=False)

    def test_legal_hold_redis_sync_and_storage_cleanup_gating(self):
        """Legal hold syncs to Redis and prevents Storage.cleanup_expired_frames from deleting objects (DM-9, GOV-1)."""
        from deepSightAI.Trinetra.Shared.Storage import cleanup_expired_frames

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        stored_holds = set()
        mock_redis.sadd.side_effect = lambda k, v: stored_holds.add((k, v))
        mock_redis.srem.side_effect = lambda k, v: stored_holds.discard((k, v))
        mock_redis.sismember.side_effect = lambda k, v: (k, v) in stored_holds

        with patch("deepSightAI.Trinetra.Shared.dsai_retention._dsai_get_redis_client", return_value=mock_redis):
            # 1. Verify Redis sync on set_legal_hold
            DataRetentionManager.set_legal_hold("tenant_gov", "cam_evidence_1", dsai_enabled=True)
            mock_redis.sadd.assert_called_with("dsai:legal_hold:tenant_gov", "cam_evidence_1")

            # 2. Verify Storage.cleanup_expired_frames respects legal hold
            mock_minio = MagicMock()
            now = datetime.now(timezone.utc)
            expired_time = now - timedelta(days=20)

            obj_held = MagicMock()
            obj_held.object_name = "tenant_gov/cam_evidence_1/2026-09-01/frame_001.jpg"
            obj_held.last_modified = expired_time

            obj_unheld = MagicMock()
            obj_unheld.object_name = "tenant_gov/cam_hallway/2026-09-01/frame_002.jpg"
            obj_unheld.last_modified = expired_time

            mock_minio.list_objects.return_value = [obj_held, obj_unheld]

            deleted_count = cleanup_expired_frames(mock_minio, "frames", retention_days=7)

            # Only unheld object should be deleted!
            assert deleted_count == 1
            assert mock_minio.remove_object.call_count == 1
            assert mock_minio.remove_object.call_args[0][1] == "tenant_gov/cam_hallway/2026-09-01/frame_002.jpg"

            # Clean up hold
            DataRetentionManager.set_legal_hold("tenant_gov", "cam_evidence_1", dsai_enabled=False)
            mock_redis.srem.assert_called_with("dsai:legal_hold:tenant_gov", "cam_evidence_1")


class TestDM10andDM11VersioningAndIdempotency:
    """DM-10 & DM-11: Schema versioning tag and deterministic video_object_pk."""

    def test_milvus_schema_version_tag(self):
        """Verify schema version is tagged as 1.0.0 and readable (DM-10)."""
        assert DSAI_MILVUS_SCHEMA_VERSION == "1.0.0"

        mock_collection = MagicMock()
        mock_collection.schema.description = "Video frames [schema_version=1.0.0]"
        assert dsai_get_milvus_collection_version(mock_collection) == "1.0.0"

    def test_deterministic_pk_generation(self):
        """Verify dsai_generate_video_object_pk is deterministic and idempotent (DM-11)."""
        tenant_id = "tenant_hq"
        camera_id = "cam_01"
        frame_timestamp = 142.50012
        object_class = "person"
        bbox = [10.5, 20.0, 50.2, 80.8]

        pk1 = dsai_generate_video_object_pk(tenant_id, camera_id, frame_timestamp, object_class, bbox)
        pk2 = dsai_generate_video_object_pk(tenant_id, camera_id, frame_timestamp, object_class, bbox)

        assert isinstance(pk1, str)
        assert len(pk1) == 64  # SHA-256 hex string
        assert pk1 == pk2

    def test_deterministic_pk_uniqueness(self):
        """Different parameters must generate distinct PKs (DM-11)."""
        pk_base = dsai_generate_video_object_pk("t1", "c1", 10.0, "vehicle", [0, 0, 10, 10])
        pk_diff_camera = dsai_generate_video_object_pk("t1", "c2", 10.0, "vehicle", [0, 0, 10, 10])
        pk_diff_time = dsai_generate_video_object_pk("t1", "c1", 11.0, "vehicle", [0, 0, 10, 10])
        pk_diff_class = dsai_generate_video_object_pk("t1", "c1", 10.0, "person", [0, 0, 10, 10])
        pk_diff_bbox = dsai_generate_video_object_pk("t1", "c1", 10.0, "vehicle", [5, 5, 15, 15])

        pks = {pk_base, pk_diff_camera, pk_diff_time, pk_diff_class, pk_diff_bbox}
        assert len(pks) == 5

    def test_deterministic_pk_ordinal_keying(self):
        """Verify ordinal det_idx produces consistent PK regardless of slight bbox float variations (DM-11)."""
        pk1 = dsai_generate_video_object_pk("t1", "c1", 10.0, "vehicle", [10.001, 20.002, 30.003, 40.004], det_idx=0)
        pk2 = dsai_generate_video_object_pk("t1", "c1", 10.0, "vehicle", [10.004, 20.001, 30.001, 40.009], det_idx=0)
        assert pk1 == pk2, "Ordinal keying should produce identical PK even if model bbox floats vary slightly"

        pk_det1 = dsai_generate_video_object_pk("t1", "c1", 10.0, "vehicle", [10.0, 20.0, 30.0, 40.0], det_idx=1)
        assert pk1 != pk_det1, "Different ordinal det_idx must produce distinct PKs"


class TestDM10AlembicMultiTenant:
    """DM-10: Multi-tenant schema discovery for Alembic migrations."""

    def test_get_tenant_schemas_discovers_all_tenants(self):
        """Migrations target all tenant_% schemas plus public and tenant_default (DM-10)."""
        from deepSightAI.Trinetra.Shared.DB import dsai_get_tenant_schemas as get_tenant_schemas

        mock_conn = MagicMock()
        mock_conn.execute.return_value = [("tenant_alpha",), ("tenant_beta",)]

        schemas = get_tenant_schemas(mock_conn)
        assert "public" in schemas
        assert "tenant_default" in schemas
        assert "tenant_alpha" in schemas
        assert "tenant_beta" in schemas


# =====================================================================
# 2. HARDENING (REL-51, REL-53, REL-55, REL-56, REL-57)
# =====================================================================

class TestREL51andREL53Hardening:
    """REL-51 & REL-53: Exception hierarchy and structured JSON logging."""

    def test_trinetra_error_hierarchy(self):
        """All domain exceptions inherit from TrinetraError and serialize to dict (REL-51)."""
        errors = [
            AuthenticationError("Unauthorized", dsai_code="AUTH_401"),
            PermissionDeniedError("Forbidden", dsai_code="AUTH_403"),
            NotFoundError("Resource missing", dsai_code="NOT_FOUND_404"),
            ValidationError("Bad input", dsai_code="VALIDATION_422"),
            StorageError("Storage failed"),
            MinIOError("MinIO fput failed"),
            MilvusError("Milvus query timeout"),
            StreamingError("Stream closed"),
            DeadLetterQueueError("DLQ full"),
            RecoverableOrphanError("Frame orphaned"),
            ModelInferenceError("Inference failed"),
            ConfigurationError("Config missing"),
            LegalHoldError("Cannot delete: legal hold active"),
        ]

        for err in errors:
            assert isinstance(err, TrinetraError)
            d = err.to_dict()
            assert "error" in d
            assert "message" in d
            assert "details" in d

    def test_json_structured_logging(self):
        """DSAIJsonFormatter outputs valid JSON with required observability fields (REL-53)."""
        formatter = DSAIJsonFormatter(dsai_service_name="vision-processing-service")
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="Detection completed for frame",
            args=(),
            exc_info=None
        )
        record.tenant_id = "tenant_alpha"
        record.camera_id = "cam_01"

        log_line = formatter.format(record)
        parsed = json.loads(log_line)

        assert parsed["service"] == "vision-processing-service"
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Detection completed for frame"
        assert parsed["tenant_id"] == "tenant_alpha"
        assert parsed["camera_id"] == "cam_01"
        assert "timestamp" in parsed


class TestREL55toREL57RetryAndDLQ:
    """REL-55 to REL-57: Extractor upload retry + DLQ, orphan recording, embedder bounded retry."""

    def test_extractor_minio_upload_retry_and_dlq(self):
        """Extractor retries MinIO upload with backoff; on exhaustion publishes to events:dlq (REL-55)."""
        mock_minio = MagicMock()
        mock_minio.fput_object.side_effect = Exception("Simulated MinIO upload network failure")

        with patch("deepSightAI.Trinetra.ServerAndExtractor.extractor.get_producer") as mock_get_producer, \
             patch("time.sleep") as mock_sleep:

            mock_producer = MagicMock()
            mock_get_producer.return_value = mock_producer

            success = dsai_upload_frame_with_retry(
                minio_client=mock_minio,
                bucket_name="frames",
                object_name="tenant_1/cam1/2026-09-20/f.jpg",
                file_path="/tmp/f.jpg",
                max_retries=3,
                initial_delay=0.01,
                backoff=2.0
            )

            assert success is False
            # Retried 3 times
            assert mock_minio.fput_object.call_count == 3
            # Routed to events:dlq on exhaustion
            mock_producer.publish.assert_called_once()
            dlq_args = mock_producer.publish.call_args
            assert dlq_args[0][0] == "events:dlq"
            assert dlq_args[0][1]["event_type"] == "minio.upload.failed"

    def test_extractor_redis_publish_orphan_recording(self):
        """Redis publish exhaustion records recoverable orphan entry (REL-56)."""
        event = FrameReadyEvent(
            video_id="vid_orphan",
            segment_id=0,
            frame_paths=["path/to/frame.jpg"],
            timestamps=[1.0],
            sequence_numbers=[0],
            extractor_id="ext-01",
            bucket_name="frames",
            timestamp=datetime.now(timezone.utc),
            tenant_id="tenant_orph",
            camera_id="cam_orph"
        )

        initial_count = len(DSAI_RECOVERABLE_ORPHANS)
        dsai_record_recoverable_orphan(event, "Redis connection refused")

        assert len(DSAI_RECOVERABLE_ORPHANS) == initial_count + 1
        last_orphan = DSAI_RECOVERABLE_ORPHANS[-1]
        assert last_orphan["status"] == "RECOVERABLE_ORPHAN"
        assert last_orphan["error"] == "Redis connection refused"
        assert last_orphan["event"]["video_id"] == "vid_orphan"


    def test_embedder_active_entrypoint_process_events_retry_and_dlq(self):
        """Active entrypoint embedder.py:process_events implements bounded retry and DLQ routing (REL-57)."""
        from deepSightAI.Trinetra.Embedder.embedder import process_events

        mock_minio = MagicMock()
        mock_consumer = MagicMock()
        mock_producer = MagicMock()

        mock_msg = MagicMock()
        mock_msg.id = "1690000000001-0"
        mock_msg.data = {
            "event": json.dumps({
                "video_id": "vid_bad_2",
                "segment_id": 0,
                "frame_paths": ["corrupt2.jpg"],
                "timestamps": [0.0],
                "sequence_numbers": [0],
                "extractor_id": "ext-1",
                "bucket_name": "frames",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tenant_id": "t1",
                "camera_id": "c1"
            })
        }
        mock_consumer.read.return_value = [mock_msg]

        with patch("deepSightAI.Trinetra.Embedder.embedder.process_segment_frames", side_effect=Exception("Failed to decode")), \
             patch("deepSightAI.Trinetra.Embedder.embedder.get_milvus_collection", return_value=MagicMock()), \
             patch.dict(os.environ, {"MAX_MESSAGE_RETRIES": "2", "DLQ_STREAM": "events:dlq"}):

            stop_flag = MagicMock()
            stop_flag.is_set.side_effect = [False, False, True]

            process_events(
                consumer=mock_consumer,
                producer=mock_producer,
                minio_client=mock_minio,
                stop_flag=stop_flag,
                max_iterations=2
            )

            # Verified DLQ published and message ACKed after 2 retries
            assert mock_producer.publish.called
            mock_producer.publish.assert_called_with("events:dlq", ANY)
            mock_consumer.ack.assert_called_with("frames", mock_msg.id)


# =====================================================================
# 3. VISION PROCESSING SERVICE (VP-12 to VP-25)
# =====================================================================

class TestVP12toVP25VisionProcessing:
    """VP-12 to VP-25: Vision Processing Service, plugins, FP32 Re-ID, durable Milvus write."""

    def test_plugin_loader_sector_and_tenant_camera_filtering(self):
        """PluginLoader enables plugins based on sector compatibility and tenant/camera overrides (VP-24, VP-25)."""
        config = {
            "plugins": {
                "pp_human": {"enabled": True, "sectors": ["law_enforcement", "commercial"]},
                "pp_vehicle": {"enabled": True, "sectors": ["law_enforcement", "logistics"]},
            },
            "tenants": {
                "tenant_alpha": {
                    "sector": "commercial",
                    "disabled_plugins": ["pp_human"],  # explicitly disabled for this tenant
                },
                "tenant_beta": {
                    "sector": "law_enforcement",
                    "camera_overrides": {
                        "cam_no_cars": {"disabled_plugins": ["pp_vehicle"]}
                    }
                }
            }
        }

        loader = PluginLoader(config)

        # tenant_alpha has commercial sector (supports human, not vehicle), but disabled pp_human
        assert loader.is_plugin_enabled("pp_human", tenant_sector="commercial", tenant_id="tenant_alpha") is False
        assert loader.is_plugin_enabled("pp_vehicle", tenant_sector="commercial", tenant_id="tenant_alpha") is False

        # tenant_beta has law_enforcement sector (supports both)
        assert loader.is_plugin_enabled("pp_human", tenant_sector="law_enforcement", tenant_id="tenant_beta") is True
        assert loader.is_plugin_enabled("pp_vehicle", tenant_sector="law_enforcement", tenant_id="tenant_beta") is True

        # camera override disables pp_vehicle on cam_no_cars
        assert loader.is_plugin_enabled("pp_vehicle", tenant_sector="law_enforcement", tenant_id="tenant_beta", camera_id="cam_no_cars") is False
        assert loader.is_plugin_enabled("pp_vehicle", tenant_sector="law_enforcement", tenant_id="tenant_beta", camera_id="cam_entry") is True

    def test_pp_human_and_vehicle_plugins(self):
        """PP-Human and PP-Vehicle plugins return detections with FP32 256-dim embeddings and attributes."""
        human_plugin = PPHumanPlugin({"min_confidence": 0.5})
        vehicle_plugin = PPVehiclePlugin({"min_confidence": 0.5})
        attribute_plugin = PPVehicleAttributePlugin({})

        # Test frame input
        frame_input = "mock_frame.jpg"

        human_dets = human_plugin.detect(frame_input)
        assert len(human_dets) >= 1
        det_h = human_dets[0]
        assert det_h["object_class"] == "person"
        assert det_h["confidence"] >= 0.5
        assert len(det_h["embedding"]) == 256  # 256-dim FP32 Re-ID embedding

        vehicle_dets = vehicle_plugin.detect(frame_input)
        assert len(vehicle_dets) >= 1
        det_v = vehicle_dets[0]
        assert det_v["object_class"] == "vehicle"
        assert det_v["confidence"] >= 0.5
        assert len(det_v["embedding"]) == 256

        # Test attribute extraction (color, vehicle_type)
        attrs = attribute_plugin.extract_attributes(det_v)
        assert "color" in attrs
        assert "vehicle_type" in attrs

        # Test real Re-ID feature extraction distinguishes distinct visual appearances (VP-15, VP-16)
        img_red = np.zeros((120, 80, 3), dtype=np.uint8)
        img_red[:, :, 2] = 255  # Red crop
        img_blue = np.zeros((120, 80, 3), dtype=np.uint8)
        img_blue[:, :, 0] = 255  # Blue crop

        emb_red = human_plugin._dsai_extract_reid(img_red)
        emb_blue = human_plugin._dsai_extract_reid(img_blue)
        assert len(emb_red) == 256
        assert len(emb_blue) == 256
        # Cosine similarity must NOT be 1.0 (real feature extraction, not fixed dummy vector)
        cos_sim = float(np.dot(emb_red, emb_blue))
        assert cos_sim < 0.95, f"Expected distinct embeddings for red vs blue crops, got similarity {cos_sim}"

        # Identical crops produce identical embeddings
        emb_red_dup = human_plugin._dsai_extract_reid(img_red)
        assert np.isclose(float(np.dot(emb_red, emb_red_dup)), 1.0)

    def test_vps_consumer_processes_frame_ready_event(self):
        """VisionProcessingConsumer runs plugins, writes Milvus, and emits ObjectDetectedEvent (VP-20, VP-22)."""
        mock_minio = MagicMock()
        mock_producer = MagicMock()

        consumer = VisionProcessingConsumer(
            dsai_minio_client=mock_minio,
            dsai_producer=mock_producer,
            dsai_config={"tenants": {"t_test": {"sector": "law_enforcement"}}}
        )

        event = FrameReadyEvent(
            video_id="vid_test_1",
            segment_id=0,
            frame_paths=["t_test/cam_front/2026-09-20/vid_test_1/segment_0/frame_00000.jpg"],
            timestamps=[10.5],
            sequence_numbers=[0],
            extractor_id="ext-01",
            bucket_name="frames",
            timestamp=datetime.now(timezone.utc),
            tenant_id="t_test",
            camera_id="cam_front"
        )

        # Mock person and vehicle Milvus collections
        mock_person_coll = MagicMock()
        mock_vehicle_coll = MagicMock()

        with patch("deepSightAI.Trinetra.VisionProcessingService.dsai_consumer.ensure_person_collection", return_value=mock_person_coll), \
             patch("deepSightAI.Trinetra.VisionProcessingService.dsai_consumer.ensure_vehicle_collection", return_value=mock_vehicle_coll):

            emitted_events = consumer.dsai_process_event(event)

            # Both human and vehicle plugins produced detections
            assert len(emitted_events) >= 2
            classes = [e.object_class for e in emitted_events]
            assert "person" in classes
            assert "vehicle" in classes

            # Verify deterministic PKs on emitted events
            for e in emitted_events:
                assert isinstance(e.video_object_pk, str)
                assert len(e.video_object_pk) == 64
                assert e.tenant_id == "t_test"
                assert e.camera_id == "cam_front"
                assert e.frame_timestamp == 10.5

            # Verify Milvus durable writes occurred before publishing
            assert mock_person_coll.insert.called
            assert mock_person_coll.flush.called
            assert mock_vehicle_coll.insert.called
            assert mock_vehicle_coll.flush.called

            # Verify ObjectDetectedEvents published to Redis stream
            assert mock_producer.publish.called
            publish_calls = [c[0] for c in mock_producer.publish.call_args_list]
            for stream_name, _ in publish_calls:
                assert stream_name == "events:object_detected"

    def test_vps_consumer_milvus_failure_prevents_ack(self):
        """Source FrameReadyEvent is NOT acked if Milvus durable write fails (VP-23)."""
        mock_minio = MagicMock()
        mock_producer = MagicMock()
        mock_consumer = MagicMock()

        consumer = VisionProcessingConsumer(
            dsai_minio_client=mock_minio,
            dsai_producer=mock_producer,
            dsai_config={"tenants": {"t_test": {"sector": "law_enforcement"}}}
        )
        consumer.consumer = mock_consumer

        mock_msg = MagicMock()
        mock_msg.id = "msg-123"
        mock_msg.data = {
            "event": json.dumps({
                "video_id": "vid_test_1",
                "segment_id": 0,
                "frame_paths": ["fake_frame.jpg"],
                "timestamps": [1.0],
                "sequence_numbers": [0],
                "extractor_id": "ext-1",
                "bucket_name": "frames",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tenant_id": "t_test",
                "camera_id": "c1",
            })
        }
        mock_consumer.read.return_value = [mock_msg]

        # Milvus collection insert raises exception
        mock_person_coll = MagicMock()
        mock_person_coll.insert.side_effect = Exception("Milvus connection lost")

        with patch("deepSightAI.Trinetra.VisionProcessingService.dsai_consumer.ensure_person_collection", return_value=mock_person_coll):
            stop_flag = MagicMock()
            stop_flag.is_set.side_effect = [False, True]
            consumer.dsai_run_loop(dsai_stop_flag=stop_flag, dsai_max_iterations=1)

            # Milvus write failed, so message must NOT be acked!
            mock_consumer.ack.assert_not_called()


# =====================================================================
# 4. SEARCH API (SR-35 to SR-44)
# =====================================================================

class TestSR35toSR44SearchAPI:
    """SR-35 to SR-44: Unified Search API, RBAC enforcement, vehicle/person search, ceiling limits."""

    @pytest.fixture
    def test_client(self):
        """Create FastAPI test client for SearchService."""
        from fastapi.testclient import TestClient
        from deepSightAI.Trinetra.SearchService.main import app
        return TestClient(app)

    def test_search_unauthenticated_returns_401(self, test_client):
        """Search requests without Authorization header must return 401 Unauthorized (SR-43)."""
        response = test_client.post("/search/text", json={"query_text": "red car"})
        assert response.status_code == 401

        response_veh = test_client.post("/search/vehicle", json={"color": "red"})
        assert response_veh.status_code == 401

        response_per = test_client.post("/search/person", json={"camera_ids": ["c1"]})
        assert response_per.status_code == 401

    def test_search_without_permission_returns_403(self, test_client):
        """Authenticated user without 'search:read' permission receives 403 Forbidden (SR-43)."""
        from deepSightAI.Trinetra.SearchService.main import require_auth, app

        # Provide user without search:read permission
        user_no_perms = {
            "sub": "user_viewer",
            "tenant_id": "tenant_1",
            "roles": ["viewer"],
            "permissions": ["audit:read"]  # Missing search:read
        }

        app.dependency_overrides[require_auth] = lambda: user_no_perms
        try:
            response = test_client.post("/search/text", json={"query_text": "person running"})
            assert response.status_code == 403
            assert "search:read" in response.json().get("detail", "")
        finally:
            app.dependency_overrides.pop(require_auth, None)

    def test_search_text_with_camera_and_time_filters(self, test_client):
        """Semantic text search filters by camera_ids and time window, returning presigned thumbnails (SR-35)."""
        from deepSightAI.Trinetra.SearchService.main import require_auth, app

        auth_user = {
            "sub": "user_sec",
            "tenant_id": "tenant_search",
            "roles": ["operator"],
            "permissions": ["search:read"]
        }
        app.dependency_overrides[require_auth] = lambda: auth_user

        mock_hit = MagicMock()
        mock_hit.score = 0.92
        mock_hit.entity.get.side_effect = lambda field: {
            "video_id": "vid_101",
            "frame_path": "tenant_search/cam_1/2026-09-20/f.jpg",
            "camera_id": "cam_1",
            "frame_timestamp": 125.0
        }.get(field)

        mock_coll = MagicMock()
        mock_coll.search.return_value = [[mock_hit]]

        with patch("deepSightAI.Trinetra.SearchService.main.get_milvus_collection", return_value=mock_coll), \
             patch("deepSightAI.Trinetra.SearchService.main.dsai_generate_presigned_url", return_value="http://minio/presigned.jpg"):

            payload = {
                "query_text": "delivery van",
                "camera_ids": ["cam_1", "cam_2"],
                "time_start": 100.0,
                "time_end": 200.0,
                "top_k": 5
            }
            response = test_client.post("/search/text", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            item = data[0]
            assert item["video_id"] == "vid_101"
            assert item["camera_id"] == "cam_1"
            assert item["frame_timestamp"] == 125.0
            assert item["thumbnail_url"] == "http://minio/presigned.jpg"

            # Check that scalar expr included camera_ids and timestamp filters
            search_call = mock_coll.search.call_args[1]
            expr = search_call.get("expr", "")
            assert 'camera_id in ["cam_1", "cam_2"]' in expr
            assert "frame_timestamp >= 100.0" in expr
            assert "frame_timestamp <= 200.0" in expr

        app.dependency_overrides.pop(require_auth, None)

    def test_search_vehicle_attributes(self, test_client):
        """Vehicle search correctly filters on color, type, and plate indicators (SR-36)."""
        from deepSightAI.Trinetra.SearchService.main import require_auth, app

        auth_user = {"sub": "u1", "tenant_id": "t1", "permissions": ["search:read"]}
        app.dependency_overrides[require_auth] = lambda: auth_user

        mock_hit = MagicMock()
        mock_hit.score = 0.95
        mock_hit.entity.get.side_effect = lambda field: {
            "video_id": "vid_202",
            "frame_path": "t1/c1/2026-09-20/f.jpg",
            "crop_path": "t1/c1/2026-09-20/crops/pk1.jpg",
            "camera_id": "cam_gate",
            "frame_timestamp": 670.0,
            "object_class": "vehicle",
            "confidence": 0.98,
            "color": "red",
            "vehicle_type": "sedan",
            "has_plate_read": True,
            "plate_number": "KA01AB1234"
        }.get(field)

        mock_coll = MagicMock()
        mock_coll.query.return_value = [{
            "video_id": "vid_202",
            "frame_path": "t1/c1/2026-09-20/f.jpg",
            "crop_path": "t1/c1/2026-09-20/crops/pk1.jpg",
            "camera_id": "cam_gate",
            "frame_timestamp": 670.0,
            "object_class": "vehicle",
            "confidence": 0.98,
            "color": "red",
            "vehicle_type": "sedan",
            "has_plate_read": True,
            "plate_number": "KA01AB1234"
        }]

        with patch("deepSightAI.Trinetra.SearchService.main.ensure_vehicle_collection", return_value=mock_coll), \
             patch("deepSightAI.Trinetra.SearchService.main.dsai_generate_presigned_url", return_value="http://minio/crop.jpg"):

            payload = {
                "color": "red",
                "vehicle_type": "sedan",
                "has_plate_read": True,
                "camera_ids": ["cam_gate"],
                "time_start": 600.0,
                "time_end": 700.0,
                "top_k": 10
            }
            response = test_client.post("/search/vehicle", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            res = data[0]
            assert res["color"] == "red"
            assert res["vehicle_type"] == "sedan"
            assert res["has_plate_read"] is True
            assert res["plate_number"] == "KA01AB1234"

            # Check constructed expr passed to collection.query
            query_call = mock_coll.query.call_args[1]
            expr = query_call.get("expr", "")
            assert 'color == "red"' in expr
            assert 'vehicle_type == "sedan"' in expr
            assert "has_plate_read == true" in expr

        app.dependency_overrides.pop(require_auth, None)

    def test_search_person(self, test_client):
        """Person search returns detections matching filters (SR-37)."""
        from deepSightAI.Trinetra.SearchService.main import require_auth, app

        auth_user = {"sub": "u1", "tenant_id": "t1", "permissions": ["search:read"]}
        app.dependency_overrides[require_auth] = lambda: auth_user

        mock_coll = MagicMock()
        mock_coll.query.return_value = [{
            "video_id": "vid_303",
            "frame_path": "t1/c1/f.jpg",
            "crop_path": "t1/c1/crops/pk_person.jpg",
            "camera_id": "cam_lobby",
            "frame_timestamp": 312.0,
            "object_class": "person",
            "confidence": 0.91,
        }]

        with patch("deepSightAI.Trinetra.SearchService.main.ensure_person_collection", return_value=mock_coll), \
             patch("deepSightAI.Trinetra.SearchService.main.dsai_generate_presigned_url", return_value="http://minio/person.jpg"):

            payload = {
                "camera_ids": ["cam_lobby"],
                "time_start": 300.0,
                "time_end": 400.0,
                "top_k": 10
            }
            response = test_client.post("/search/person", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["object_class"] == "person"
            assert data[0]["camera_id"] == "cam_lobby"

        app.dependency_overrides.pop(require_auth, None)

    def test_search_empty_returns_200_with_empty_list(self, test_client):
        """Empty search results must return HTTP 200 with [] (SR-41)."""
        from deepSightAI.Trinetra.SearchService.main import require_auth, app

        auth_user = {"sub": "u1", "tenant_id": "t1", "permissions": ["search:read"]}
        app.dependency_overrides[require_auth] = lambda: auth_user

        mock_coll = MagicMock()
        mock_coll.search.return_value = []

        with patch("deepSightAI.Trinetra.SearchService.main.get_milvus_collection", return_value=mock_coll):
            response = test_client.post("/search/text", json={"query_text": "nonexistent term"})
            assert response.status_code == 200
            assert response.json() == []

        app.dependency_overrides.pop(require_auth, None)

    def test_search_top_k_ceiling_422(self, test_client):
        """Requests with top_k > 100 must be rejected with 422 Unprocessable Entity (SR-44)."""
        from deepSightAI.Trinetra.SearchService.main import require_auth, app

        auth_user = {"sub": "u1", "tenant_id": "t1", "permissions": ["search:read"]}
        app.dependency_overrides[require_auth] = lambda: auth_user

        response = test_client.post("/search/text", json={"query_text": "cars", "top_k": 150})
        assert response.status_code == 422
        err = response.json()
        assert "detail" in err

        response_veh = test_client.post("/search/vehicle", json={"top_k": 101})
        assert response_veh.status_code == 422

        response_per = test_client.post("/search/person", json={"top_k": 200})
        assert response_per.status_code == 422

        app.dependency_overrides.pop(require_auth, None)

    def test_cameras_endpoint(self, test_client):
        """GET /cameras returns tenant-isolated camera registry list (SR-38)."""
        from deepSightAI.Trinetra.SearchService.main import require_auth, app

        auth_user = {"sub": "u1", "tenant_id": "tenant_cam_test", "permissions": ["search:read"]}
        app.dependency_overrides[require_auth] = lambda: auth_user

        mock_cam = MagicMock()
        mock_cam.camera_id = "cam_entry_1"
        mock_cam.name = "Front Entrance Gate"
        mock_cam.stream_url = "rtsp://10.0.0.1/live"
        mock_cam.is_active = True

        with patch("deepSightAI.Trinetra.SearchService.main.CameraRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.list_all.return_value = [mock_cam]
            mock_repo_cls.return_value = mock_repo

            response = test_client.get("/cameras")
            assert response.status_code == 200
            cams = response.json()
            assert len(cams) == 1
            assert cams[0]["camera_id"] == "cam_entry_1"
            assert cams[0]["name"] == "Front Entrance Gate"

        app.dependency_overrides.pop(require_auth, None)

    def test_presigned_url_short_ttl_fail_closed_and_expiry(self):
        """Presigned URL generator fails closed to None on exception, and SearchResult exposes expires_at (SR-40)."""
        from deepSightAI.Trinetra.SearchService.main import dsai_generate_presigned_url, SearchResult

        # 1. On exception, generator must return None (fail closed), NEVER fallback to raw http link
        with patch("deepSightAI.Trinetra.SearchService.main.get_minio_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.presigned_get_object.side_effect = Exception("MinIO connection reset")
            mock_get_client.return_value = mock_client

            url = dsai_generate_presigned_url("sensitive_tenant/secret_cam/frame.jpg")
            assert url is None

        # 2. SearchResult model drops raw frame_path in favor of thumbnail_url (SR-40) with expires_in_seconds and expires_at
        res = SearchResult(
            video_id="v1",
            score=0.95,
            thumbnail_url="http://minio/presigned.jpg",
            expires_in_seconds=900
        )
        assert "frame_path" not in SearchResult.model_fields
        assert not hasattr(res, "frame_path")
        assert res.thumbnail_url == "http://minio/presigned.jpg"
        assert res.expires_at is not None
        assert res.expires_in_seconds == 900
        assert res.expires_at > datetime.now(timezone.utc)


# =====================================================================
# 5. MODERNIZED UI (UI-82 to UI-93)
# =====================================================================

class TestUI82toUI93ModernizedUI:
    """UI-82 to UI-93: Verification of UI formatting, headers, and contracts."""

    def test_ui_format_timestamp(self):
        """format_timestamp converts seconds to HH:MM:SS or MM:SS format (UI-93)."""
        from deepSightAI.Trinetra.UI.ui import format_timestamp

        assert format_timestamp(None) == "N/A"
        assert format_timestamp(45.0) == "00:45"
        assert format_timestamp(125.0) == "02:05"
        assert format_timestamp(3665.0) == "01:01:05"
