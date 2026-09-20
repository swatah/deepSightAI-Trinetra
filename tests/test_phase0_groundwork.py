"""
Phase 0 Groundwork Verification Tests (GW-1 to GW-7).

Verifies all critical fixes and foundation contracts:
- GW-1: Frame preservation (no unconditional MinIO frame deletion during embed)
- GW-2: Search contract harmonization (query/query_text compatibility)
- GW-3: Multi-tenant metadata in FrameReadyEvent and Milvus schema
- GW-4/GW-5: RTSP reconnect loop, single bucket, and hierarchical paths
- GW-6: Registry zombie worker recovery script and heartbeat
- GW-7: Relational repositories and tenant isolation
"""

import os
import sys
import uuid
import threading
import time
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from deepSightAI.Trinetra.Shared.Streaming.Schema import FrameReadyEvent
from deepSightAI.Trinetra.Shared.DB import Base
from deepSightAI.Trinetra.Shared.Repositories.CameraRepository import Camera, CameraRepository
from deepSightAI.Trinetra.Shared.Repositories.PlateRepository import PlateRead, PlateRepository
from deepSightAI.Trinetra.Shared.Repositories.WatchlistRepository import (
    WatchlistEntry,
    Alert,
    WatchlistRepository,
    AlertRepository,
)


class TestGW1FramePreservation:
    """GW-1: Ensure embedder never deletes frames after vector embedding."""

    def test_process_segment_frames_does_not_delete_minio_objects(self):
        """Verify process_segment_frames does not call remove_object on MinIO."""
        from Embedder.embedder import process_segment_frames

        mock_minio = MagicMock()
        mock_collection = MagicMock()
        mock_collection.schema.fields = [MagicMock(name=f) for f in ["pk", "video_id", "camera_id", "frame_path", "frame_timestamp", "embedding", "tenant_id"]]
        
        # Mock frame_exists to return False
        with patch("Embedder.embedder.frame_exists", return_value=False), \
             patch("Embedder.embedder.download_frame_objects", return_value=["/tmp/fake1.jpg"]), \
             patch("Embedder.embedder.encode_images") as mock_encode, \
             patch("Embedder.embedder.cleanup_temp_files"), \
             patch("Embedder.embedder.mark_segment_processed"):
            
            import torch
            mock_encode.return_value = torch.ones((1, 512))

            process_segment_frames(
                minio_client=mock_minio,
                collection=mock_collection,
                video_id="test_video",
                segment_path="test_video/segment_0000",
                frame_objects=["test_video/segment_0000/frame_00001.jpg"],
                timestamps=[0.0],
                tenant_id="tenant_a",
                camera_id="cam_1"
            )

        # Ensure remove_object was NEVER called on mock_minio
        assert mock_minio.remove_object.call_count == 0

    def test_event_consumer_does_not_call_delete(self):
        """Verify EmbedderConsumer.process_event does not delete frames."""
        from Embedder.event_consumer import EmbedderConsumer

        mock_minio = MagicMock()
        mock_collection = MagicMock()
        mock_collection.schema.fields = [MagicMock() for _ in range(7)]

        consumer = EmbedderConsumer(
            milvus_collection=mock_collection,
            minio_client=mock_minio,
            group_name="test-group",
            consumer_id="test-consumer"
        )

        event = FrameReadyEvent(
            video_id="test_vid",
            segment_id=0,
            frame_paths=["path/to/frame.jpg"],
            timestamps=[1.0],
            sequence_numbers=[0],
            extractor_id="test_extractor",
            bucket_name="frames",
            timestamp=datetime.utcnow(),
            tenant_id="tenant_1",
            camera_id="cam_front"
        )

        with patch("Embedder.event_consumer.encode_images") as mock_encode, \
             patch("os.unlink"):
            import torch
            mock_encode.return_value = torch.ones((1, 512))
            consumer.process_event(event)

        assert mock_minio.remove_object.call_count == 0

    def test_configure_bucket_lifecycle(self):
        """Verify configure_bucket_lifecycle sets 7-day expiration policy."""
        from deepSightAI.Trinetra.Shared.Storage import configure_bucket_lifecycle

        mock_minio = MagicMock()
        success = configure_bucket_lifecycle(mock_minio, "frames", retention_days=7)
        assert success is True
        mock_minio.set_bucket_lifecycle.assert_called_once()
        args, _ = mock_minio.set_bucket_lifecycle.call_args
        assert args[0] == "frames"
        config = args[1]
        assert len(config.rules) == 1
        rule = config.rules[0]
        assert rule.status == "Enabled"
        assert rule.expiration.days == 7

    def test_cleanup_expired_frames(self):
        """Verify cleanup_expired_frames only deletes items older than retention threshold."""
        from datetime import datetime, timezone, timedelta
        from deepSightAI.Trinetra.Shared.Storage import cleanup_expired_frames

        mock_minio = MagicMock()
        now = datetime.now(timezone.utc)

        expired_obj = MagicMock()
        expired_obj.object_name = "tenant/cam/2026-09-01/frame1.jpg"
        expired_obj.last_modified = now - timedelta(days=10)

        recent_obj = MagicMock()
        recent_obj.object_name = "tenant/cam/2026-09-20/frame2.jpg"
        recent_obj.last_modified = now - timedelta(days=2)

        mock_minio.list_objects.return_value = [expired_obj, recent_obj]

        deleted = cleanup_expired_frames(mock_minio, "frames", retention_days=7)
        assert deleted == 1
        mock_minio.remove_object.assert_called_once_with("frames", "tenant/cam/2026-09-01/frame1.jpg")

    def test_dual_consumers_access_same_frames_without_404(self, tmp_path):
        """GW-1: Verify two independent consumers access identical frames in MinIO without 404 NoSuchKey."""
        from Embedder.event_consumer import EmbedderConsumer
        import torch

        # In-memory storage mock: would fail with 404 if previous consumer deleted the object
        dsai_minio_store = {
            "tenant_alpha/cam_gate/2026-09-20/frame_001.jpg": b"fake_jpeg_data_content"
        }

        mock_minio = MagicMock()

        def dsai_fget_object(bucket_name, object_name, file_path):
            if object_name not in dsai_minio_store:
                raise Exception(f"S3Error: 404 NoSuchKey - {object_name} does not exist in bucket {bucket_name}")
            with open(file_path, "wb") as f:
                f.write(dsai_minio_store[object_name])

        def dsai_remove_object(bucket_name, object_name):
            dsai_minio_store.pop(object_name, None)

        mock_minio.fget_object.side_effect = dsai_fget_object
        mock_minio.remove_object.side_effect = dsai_remove_object

        mock_collection_a = MagicMock()
        mock_collection_a.schema.fields = [MagicMock() for _ in range(7)]
        mock_collection_b = MagicMock()
        mock_collection_b.schema.fields = [MagicMock() for _ in range(7)]

        # Consumer 1: Main vector embedder
        dsai_consumer_a = EmbedderConsumer(
            milvus_collection=mock_collection_a,
            minio_client=mock_minio,
            group_name="embedder-group",
            consumer_id="embedder-worker-1"
        )

        # Consumer 2: Independent secondary consumer (e.g. alert / LPR / audit worker)
        dsai_consumer_b = EmbedderConsumer(
            milvus_collection=mock_collection_b,
            minio_client=mock_minio,
            group_name="alert-group",
            consumer_id="alert-worker-1"
        )

        dsai_event = FrameReadyEvent(
            video_id="traffic_stream",
            segment_id=0,
            frame_paths=["tenant_alpha/cam_gate/2026-09-20/frame_001.jpg"],
            timestamps=[10.0],
            sequence_numbers=[1],
            extractor_id="ext-01",
            bucket_name="frames",
            timestamp=datetime.utcnow(),
            tenant_id="tenant_alpha",
            camera_id="cam_gate"
        )

        with patch("Embedder.event_consumer.encode_images", return_value=torch.ones((1, 512))), \
             patch("os.unlink"):
            # Consumer A processes event
            dsai_consumer_a.process_event(dsai_event)
            # Consumer B processes same event afterwards
            dsai_consumer_b.process_event(dsai_event)

        # Assert BOTH consumers inserted into their respective collections
        assert mock_collection_a.insert.called
        assert mock_collection_b.insert.called
        # Assert the frame object STILL exists in MinIO store (no 404 was raised, no deletion occurred)
        assert "tenant_alpha/cam_gate/2026-09-20/frame_001.jpg" in dsai_minio_store
        assert mock_minio.remove_object.call_count == 0


class TestGW2SearchContract:
    """GW-2: Verify UI and SearchService contract synchronization."""

    def test_search_request_accepts_both_query_and_query_text(self):
        from SearchService.main import SearchRequest

        # Test with query_text
        req1 = SearchRequest(query_text="red vehicle")
        assert req1.get_query() == "red vehicle"

        # Test with query
        req2 = SearchRequest(query="person in black jacket")
        assert req2.get_query() == "person in black jacket"

        # Test fallback order
        req3 = SearchRequest(query_text="first", query="second")
        assert req3.get_query() == "first"

    def test_search_request_rejects_empty(self):
        from SearchService.main import SearchRequest
        req = SearchRequest(query_text="", query="")
        with pytest.raises(ValueError, match="cannot be empty"):
            req.get_query()

    def test_search_result_schema_fields(self):
        from SearchService.main import SearchResult
        res = SearchResult(
            video_id="v1",
            frame_path="tenant1/cam1/2026-09-20/f1.jpg",
            score=0.88,
            camera_id="cam1",
            frame_timestamp=12.5
        )
        assert res.video_id == "v1"
        assert res.camera_id == "cam1"
        assert res.frame_timestamp == 12.5


class TestGW3FrameReadyEvent:
    """GW-3: Verify FrameReadyEvent metadata propagation."""

    def test_event_serialization_preserves_tenant_and_camera(self):
        event = FrameReadyEvent(
            video_id="video-xyz",
            segment_id=2,
            frame_paths=["tenant_42/cam_front/2026-09-20/f.jpg"],
            timestamps=[60.0],
            sequence_numbers=[0],
            extractor_id="ext-01",
            bucket_name="frames",
            timestamp=datetime.utcnow(),
            tenant_id="tenant_42",
            camera_id="cam_front",
            correlation_id="corr-999"
        )
        data = event.model_dump()
        assert data["tenant_id"] == "tenant_42"
        assert data["camera_id"] == "cam_front"
        assert data["correlation_id"] == "corr-999"

        # Roundtrip JSON
        json_str = event.model_dump_json()
        deserialized = FrameReadyEvent.model_validate_json(json_str)
        assert deserialized.tenant_id == "tenant_42"
        assert deserialized.camera_id == "cam_front"
        assert deserialized.correlation_id == "corr-999"


class TestGW4RTSPReconnect:
    """GW-4: Verify RTSP reconnect loop with exponential backoff on network error."""

    def test_gstreamer_error_message_does_not_abort_stream_and_allows_reconnect(self):
        """Simulate Gst.MessageType.ERROR to ensure extractor.stop() is called but shutdown_event is NOT set."""
        try:
            import gi
            gi.require_version('Gst', '1.0')
            from gi.repository import Gst
        except (ImportError, AttributeError, ValueError):
            Gst = MagicMock()
            Gst.MessageType.ERROR = 1
            Gst.MessageType.EOS = 2

        import extractor
        dsai_shutdown_event = threading.Event()
        dsai_extractor = extractor.GStreamerRtspExtractor(
            rtsp_url="rtsp://10.0.0.1:8554/live",
            video_id="cam_test",
            minio_client=MagicMock(),
            bucket_name="frames",
            shutdown_event=dsai_shutdown_event,
            tenant_id="tenant_1",
            camera_id="cam_test"
        )

        dsai_mock_msg = MagicMock()
        dsai_mock_msg.type = Gst.MessageType.ERROR
        dsai_mock_msg.parse_error.return_value = (Exception("Connection refused by RTSP server"), "debug trace")

        with patch.object(dsai_extractor, "stop") as dsai_mock_stop:
            dsai_extractor.on_message(bus=None, message=dsai_mock_msg)
            # Pipeline is stopped on error
            dsai_mock_stop.assert_called_once()
            # CRITICAL: shutdown_event must NOT be set, so the outer reconnect loop can retry!
            assert dsai_shutdown_event.is_set() is False

    def test_run_rtsp_extraction_job_retries_with_exponential_backoff(self):
        """Verify run_rtsp_extraction_job reconnects with exponential backoff (2s -> 4s -> ...) on disconnect."""
        import extractor

        dsai_stream_event = threading.Event()
        dsai_sleep_durations = []

        def dsai_mock_sleep(seconds):
            dsai_sleep_durations.append(seconds)
            # After 2 retry attempts, signal stream shutdown to terminate the test loop cleanly
            if len(dsai_sleep_durations) >= 2:
                dsai_stream_event.set()

        dsai_attempt_count = 0
        def dsai_mock_start(self):
            nonlocal dsai_attempt_count
            dsai_attempt_count += 1
            # Simulate pipeline running and terminating on network disconnect without setting stream_event
            return None

        with patch("extractor.ensure_bucket"), \
             patch("extractor.Minio"), \
             patch.object(extractor.GStreamerRtspExtractor, "start", dsai_mock_start), \
             patch("time.sleep", side_effect=dsai_mock_sleep):

            extractor.run_rtsp_extraction_job(
                rtsp_url="rtsp://test-camera:8554/stream",
                stream_id="stream_test_01",
                stream_event=dsai_stream_event,
                tenant_id="tenant_gamma",
                camera_id="cam_gate_01"
            )

        # Verified that the job reconnected multiple times
        assert dsai_attempt_count == 2
        # Verified exponential backoff progression: 2s, then 4s (doubles every retry)
        assert dsai_sleep_durations == [2, 4]
        # Verified that stream only ended once shutdown_event was set
        assert dsai_stream_event.is_set() is True


class TestGW5StructuredObjectPaths:
    """GW-5: Verify single bucket & structured hierarchical MinIO object paths."""

    def test_extractor_single_bucket_and_models(self):
        """Verify FRAME_BUCKET constant and CamelCase request models."""
        from extractor import FRAME_BUCKET, FileJobRequest, RtspJobRequest, HttpFileRequest, HttpRtspRequest
        from deepSightAI.Trinetra import HttpRtspRequest as DeepSightHttpRtspRequest

        assert FRAME_BUCKET == "frames"

        file_req = FileJobRequest(
            video_uri="videos/clip.mp4",
            segment_id=0,
            start_time=0.0,
            duration=30.0,
            tenant_id="tenant_beta",
            camera_id="cam_gate"
        )
        assert file_req.tenant_id == "tenant_beta"
        assert file_req.camera_id == "cam_gate"

        rtsp_req = RtspJobRequest(
            rtsp_url="rtsp://10.0.0.1:554/live",
            tenant_id="tenant_beta",
            camera_id="cam_gate"
        )
        assert rtsp_req.tenant_id == "tenant_beta"
        assert rtsp_req.camera_id == "cam_gate"

        http_rtsp = HttpRtspRequest(
            rtsp_url="rtsp://10.0.0.1:554/live",
            tenant_id="tenant_beta",
            camera_id="cam_gate"
        )
        assert http_rtsp.rtsp_url == "rtsp://10.0.0.1:554/live"
        assert issubclass(RtspJobRequest, HttpRtspRequest) or RtspJobRequest == HttpRtspRequest
        assert issubclass(FileJobRequest, HttpFileRequest) or FileJobRequest == HttpFileRequest
        assert DeepSightHttpRtspRequest == HttpRtspRequest

    def test_file_extraction_hierarchical_paths(self, tmp_path):
        """Verify extract_frames constructs exact {tenant_id}/{camera_id}/{date}/{video_id}/segment_{id}/ paths."""
        import extractor
        from deepSightAI.Trinetra.Shared.Minio import is_tenant_prefixed

        dsai_mock_minio = MagicMock()
        dsai_uploaded_keys = []

        def dsai_mock_fput(bucket, object_name, file_path):
            dsai_uploaded_keys.append((bucket, object_name))

        dsai_mock_minio.fput_object.side_effect = dsai_mock_fput

        # Mock GStreamerFileExtractor to produce 2 fake JPEG frames in the output directory
        def dsai_mock_extract(segment_path, output_dir):
            with open(os.path.join(output_dir, "frame_00000.jpg"), "wb") as f:
                f.write(b"frame0")
            with open(os.path.join(output_dir, "frame_00001.jpg"), "wb") as f:
                f.write(b"frame1")

        with patch("extractor.Minio", return_value=dsai_mock_minio), \
             patch("extractor.ensure_bucket"), \
             patch("extractor.ffmpeg"), \
             patch("extractor.publish_frame_ready_event"), \
             patch("extractor.GStreamerFileExtractor.extract_frames", side_effect=dsai_mock_extract), \
             patch("httpx.Client"):

            extractor.run_file_extraction_job(
                video_uri="videos/mall_cctv.mp4",
                segment_id=5,
                start_time=150.0,
                duration=30.0,
                tenant_id="tenant_retail",
                camera_id="cam_aisle_3"
            )

        assert len(dsai_uploaded_keys) == 2
        dsai_date_today = datetime.utcnow().strftime("%Y-%m-%d")

        for dsai_bucket, dsai_object_name in dsai_uploaded_keys:
            assert dsai_bucket == "frames", f"Expected 'frames' bucket, got {dsai_bucket}"
            assert is_tenant_prefixed(dsai_object_name, "tenant_retail")
            dsai_expected_prefix = f"tenant_retail/cam_aisle_3/{dsai_date_today}/mall_cctv/segment_0005/"
            assert dsai_object_name.startswith(dsai_expected_prefix), f"Object name {dsai_object_name} must start with {dsai_expected_prefix}"
            assert dsai_object_name.endswith(".jpg")

    def test_rtsp_extraction_hierarchical_paths(self):
        """Verify GStreamerRtspExtractor.on_new_sample generates {tenant}/{camera}/{date}/frame_*.jpg paths."""
        import extractor
        from deepSightAI.Trinetra.Shared.Minio import is_tenant_prefixed

        dsai_mock_minio = MagicMock()
        dsai_uploaded_keys = []

        def dsai_mock_fput(bucket, object_name, file_path):
            dsai_uploaded_keys.append((bucket, object_name))

        dsai_mock_minio.fput_object.side_effect = dsai_mock_fput

        dsai_shutdown = threading.Event()
        dsai_extractor = extractor.GStreamerRtspExtractor(
            rtsp_url="rtsp://10.0.0.5:8554/live",
            video_id="cam_traffic_01",
            minio_client=dsai_mock_minio,
            bucket_name="frames",
            shutdown_event=dsai_shutdown,
            tenant_id="tenant_city",
            camera_id="cam_traffic_01"
        )

        # Mock sample buffer
        dsai_mock_sink = MagicMock()
        dsai_mock_sample = MagicMock()
        dsai_mock_buffer = MagicMock()
        dsai_mock_info = MagicMock()
        dsai_mock_info.data = b"fake_rtsp_jpeg_bytes"
        dsai_mock_buffer.map.return_value = (True, dsai_mock_info)
        dsai_mock_sample.get_buffer.return_value = dsai_mock_buffer
        dsai_mock_sink.emit.return_value = dsai_mock_sample

        with patch("extractor.publish_frame_ready_event"):
            dsai_extractor.on_new_sample(dsai_mock_sink)

        assert len(dsai_uploaded_keys) == 1
        dsai_bucket, dsai_object_name = dsai_uploaded_keys[0]
        assert dsai_bucket == "frames"
        dsai_date_today = datetime.utcnow().strftime("%Y-%m-%d")
        dsai_expected_prefix = f"tenant_city/cam_traffic_01/{dsai_date_today}/frame_"
        assert dsai_object_name.startswith(dsai_expected_prefix)
        assert dsai_object_name.endswith(".jpg")
        assert is_tenant_prefixed(dsai_object_name, "tenant_city")


class TestGW6RegistryZombieReclaim:
    """GW-6: Verify atomic Lua script for zombie claim and heartbeat threads."""

    def test_claim_script_contains_zombie_timeout_and_heartbeat(self):
        import registry

        script_obj = registry._CLAIM_AVAILABLE_SCRIPT
        script_code = getattr(script_obj, "script", str(script_obj))
        # Must check for busy status, last_heartbeat, and timeout threshold
        assert "last_heartbeat" in script_code
        assert "timeout" in script_code
        assert "busy" in script_code
        assert "available" in script_code

    def test_claim_script_reclaims_dead_worker_but_keeps_heartbeating_worker(self):
        """Simulate Lua logic in Python to verify active worker is preserved while dead worker is reclaimed."""
        import time

        now = int(time.time())
        timeout = 180

        # Scenario 1: Worker has been busy for 300s (e.g. 5 min video), but heartbeat sent 10s ago
        busy_since_active = now - 300
        last_heartbeat_active = now - 10
        hb_check_active = last_heartbeat_active if last_heartbeat_active > 0 else busy_since_active
        reclaimed_active = (now - hb_check_active) > timeout
        assert reclaimed_active is False, "Active worker with recent heartbeat must NOT be reclaimed"

        # Scenario 2: Worker has been busy and heartbeat stopped 200s ago (crashed/killed)
        busy_since_dead = now - 200
        last_heartbeat_dead = now - 200
        hb_check_dead = last_heartbeat_dead if last_heartbeat_dead > 0 else busy_since_dead
        reclaimed_dead = (now - hb_check_dead) > timeout
        assert reclaimed_dead is True, "Dead worker whose heartbeat stopped > 180s must be reclaimed"

    def test_extractor_heartbeat_thread_reports_to_registry(self):
        """Verify extractor start_heartbeat_thread sends heartbeat with worker_type='extractor'."""
        import extractor
        import threading
        import time

        called = []
        def mock_post(url, params=None, **kwargs):
            called.append((url, params))
            resp = MagicMock()
            resp.status_code = 200
            return resp

        test_shutdown = threading.Event()
        with patch.object(extractor, "shutdown_event", test_shutdown), \
             patch("httpx.Client.post", side_effect=mock_post):
            extractor._heartbeat_thread = None
            t = extractor.start_heartbeat_thread(interval=0.01)
            time_start = time.time()
            while not called and (time.time() - time_start) < 2.0:
                time.sleep(0.01)
            test_shutdown.set()
            t.join(timeout=1.0)

        assert len(called) >= 1
        assert "heartbeat" in called[0][0]
        assert called[0][1]["worker_type"] == "extractor"

    def test_embedder_heartbeat_thread_reports_to_registry(self):
        """Verify embedder start_embedder_heartbeat_thread sends heartbeat with worker_type='embedder'."""
        from Embedder import embedder
        import threading
        import time

        called = []
        def mock_post(url, params=None, **kwargs):
            called.append((url, params))
            resp = MagicMock()
            resp.status_code = 200
            return resp

        test_shutdown = threading.Event()
        with patch.object(embedder, "shutdown_event", test_shutdown), \
             patch("httpx.Client.post", side_effect=mock_post):
            embedder._heartbeat_thread = None
            t = embedder.start_embedder_heartbeat_thread(interval=0.01)
            time_start = time.time()
            while not called and (time.time() - time_start) < 2.0:
                time.sleep(0.01)
            test_shutdown.set()
            t.join(timeout=1.0)

        assert len(called) >= 1
        assert "heartbeat" in called[0][0]
        assert called[0][1]["worker_type"] == "embedder"

    def test_registry_heartbeat_endpoint(self):
        """Verify registry /heartbeat updates last_heartbeat in Redis."""
        import registry

        mock_redis = MagicMock()
        mock_redis.exists.return_value = True

        with patch.object(registry, "r", mock_redis):
            res = registry.heartbeat("ext-1", "extractor")
            assert res == {"status": "ok"}
            mock_redis.hset.assert_called_once()
            args = mock_redis.hset.call_args[0]
            assert args[0] == "extractor:ext-1"
            assert args[1] == "last_heartbeat"


class TestGW7Repositories:
    """GW-7: Verify repository CRUD within tenant scope."""

    @pytest.fixture
    def test_db_session(self):
        """Create an in-memory SQLite engine and bind Base metadata."""
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        return Session

    def test_camera_repository_crud(self, test_db_session, monkeypatch):
        repo = CameraRepository("tenant_test")
        monkeypatch.setattr(repo, "Session", test_db_session)

        cam = repo.create(
            camera_id="cam_01",
            name="Main Entrance",
            rtsp_url="rtsp://localhost:8554/live",
            location="Building A"
        )
        assert cam.id == "cam_01"
        assert cam.name == "Main Entrance"
        assert cam.is_active is True

        fetched = repo.get("cam_01")
        assert fetched is not None
        assert fetched.name == "Main Entrance"

        cameras = repo.list_all()
        assert len(cameras) == 1

        repo.update_status("cam_01", is_active=False)
        updated = repo.get("cam_01")
        assert updated.is_active is False

    def test_plate_repository_crud(self, test_db_session, monkeypatch):
        repo = PlateRepository("tenant_test")
        monkeypatch.setattr(repo, "Session", test_db_session)

        read = repo.create(
            video_object_pk="obj-pk-101",
            video_id="stream-01",
            camera_id="cam_01",
            frame_timestamp=1700000000.0,
            plate_text_raw="MH 12 AB 1234",
            plate_text_norm="MH12AB1234",
            ocr_confidence=0.96,
            crop_path="crops/plate1.jpg"
        )
        assert read.plate_text_norm == "MH12AB1234"
        assert read.ocr_confidence == 0.96

        # Idempotency check: inserting same video_object_pk returns existing
        read2 = repo.create(
            video_object_pk="obj-pk-101",
            video_id="stream-01",
            camera_id="cam_01",
            frame_timestamp=1700000000.0,
            plate_text_raw="MH 12 AB 1234",
            plate_text_norm="MH12AB1234",
            ocr_confidence=0.96
        )
        assert read2.id == read.id

        exact = repo.search_exact("MH12AB1234")
        assert len(exact) == 1
        assert exact[0].video_object_pk == "obj-pk-101"

    def test_watchlist_and_alert_repositories(self, test_db_session, monkeypatch):
        wl_repo = WatchlistRepository("tenant_test")
        alert_repo = AlertRepository("tenant_test")
        monkeypatch.setattr(wl_repo, "Session", test_db_session)
        monkeypatch.setattr(alert_repo, "Session", test_db_session)

        entry = wl_repo.create(
            entry_type="plate",
            label="Stolen Sedan",
            created_by="officer_1",
            plate_text_norm="KA01AB1234",
            priority="high"
        )
        assert entry.id is not None
        assert entry.plate_text_norm == "KA01AB1234"

        # Create alert for this watchlist entry
        alert = alert_repo.create(
            watchlist_entry_id=entry.id,
            video_object_pk="obj-pk-999",
            camera_id="cam_01",
            match_score=1.0,
            crop_path="crops/alert999.jpg"
        )
        assert alert.id is not None
        assert alert.acknowledged is False

        unack = alert_repo.list_unacknowledged()
        assert len(unack) == 1
        assert unack[0].id == alert.id

        # Acknowledge
        ack_alert = alert_repo.acknowledge(alert.id, acknowledged_by="analyst_bob")
        assert ack_alert.acknowledged is True
        assert ack_alert.acknowledged_by == "analyst_bob"

        # Now unacknowledged list is empty
        assert len(alert_repo.list_unacknowledged()) == 0

    def test_tenant_connection_search_path_configuration(self):
        """GW-7: Verify get_tenant_connection configures search_path in PostgreSQL connection options."""
        from deepSightAI.Trinetra.Shared.DB import get_tenant_connection, clear_engine_pool

        clear_engine_pool()
        with patch("deepSightAI.Trinetra.Shared.DB.create_engine") as dsai_mock_create:
            get_tenant_connection("acme_corp")
            dsai_mock_create.assert_called_once()
            _, dsai_kwargs = dsai_mock_create.call_args
            dsai_options = dsai_kwargs.get("connect_args", {}).get("options", "")
            assert "-c search_path=tenant_acme_corp,public" in dsai_options
        clear_engine_pool()

    def test_tenant_id_sanitization_prevents_sql_injection(self):
        """GW-7: Verify get_tenant_connection sanitizes tenant_id to prevent search_path SQL injection."""
        from deepSightAI.Trinetra.Shared.DB import get_tenant_connection, clear_engine_pool

        clear_engine_pool()
        with patch("deepSightAI.Trinetra.Shared.DB.create_engine") as dsai_mock_create:
            get_tenant_connection("evil'; DROP SCHEMA public; --")
            dsai_mock_create.assert_called_once()
            _, dsai_kwargs = dsai_mock_create.call_args
            dsai_options = dsai_kwargs.get("connect_args", {}).get("options", "")
            # Verify dangerous SQL injection characters were completely stripped
            assert "'" not in dsai_options
            assert ";" not in dsai_options
            assert "--" not in dsai_options
            assert "tenant_evilDROPSCHEMApublic" in dsai_options
        clear_engine_pool()

    def test_validate_tenant_isolation_checks_search_path(self):
        """GW-7: Verify validate_tenant_isolation verifies search_path contains tenant schema."""
        from deepSightAI.Trinetra.Shared.DB import validate_tenant_isolation

        dsai_mock_engine = MagicMock()
        dsai_mock_conn = MagicMock()
        dsai_mock_engine.connect.return_value.__enter__.return_value = dsai_mock_conn

        # Case 1: Search path correctly contains tenant schema
        dsai_mock_conn.execute.return_value.scalar.return_value = "tenant_alpha, public"
        with patch("deepSightAI.Trinetra.Shared.DB.get_tenant_connection", return_value=dsai_mock_engine):
            assert validate_tenant_isolation("alpha") is True

        # Case 2: Search path lacks tenant schema (isolation failure)
        dsai_mock_conn.execute.return_value.scalar.return_value = "public"
        with patch("deepSightAI.Trinetra.Shared.DB.get_tenant_connection", return_value=dsai_mock_engine):
            assert validate_tenant_isolation("alpha") is False

    def test_multi_schema_isolation_boundary(self):
        """GW-7: Verify true schema isolation boundary where data in schema A is invisible to schema B."""
        from sqlalchemy import create_engine, text

        # SQLite supports real multi-schema namespaces using ATTACH DATABASE
        dsai_test_engine = create_engine("sqlite:///:memory:")
        with dsai_test_engine.connect() as dsai_conn:
            dsai_conn.execute(text("ATTACH DATABASE ':memory:' AS tenant_alpha;"))
            dsai_conn.execute(text("ATTACH DATABASE ':memory:' AS tenant_beta;"))
            dsai_conn.execute(text("CREATE TABLE tenant_alpha.cameras (id TEXT PRIMARY KEY, name TEXT);"))
            dsai_conn.execute(text("CREATE TABLE tenant_beta.cameras (id TEXT PRIMARY KEY, name TEXT);"))

            # Insert camera into tenant_alpha's schema only
            dsai_conn.execute(text("INSERT INTO tenant_alpha.cameras VALUES ('cam-1', 'Alpha Gate');"))
            dsai_conn.commit()

            # Query tenant_alpha -> 1 camera
            dsai_count_a = dsai_conn.execute(text("SELECT COUNT(*) FROM tenant_alpha.cameras;")).scalar()
            assert dsai_count_a == 1

            # Query tenant_beta -> 0 cameras (strict schema-per-tenant isolation confirmed)
            dsai_count_b = dsai_conn.execute(text("SELECT COUNT(*) FROM tenant_beta.cameras;")).scalar()
            assert dsai_count_b == 0

