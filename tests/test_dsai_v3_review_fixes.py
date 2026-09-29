"""
Regression tests for the V3 review fixes:
- extractor returns to its reconnect loop after a pipeline error (no hang)
- codec is taken from the request only; H.265 decoder falls back when unusable
- camera URL is set as a property, never pasted into the pipeline text
- base_timestamp is honoured only when the test-only switch is on
- embedder does not ACK events whose frames failed to index; DLQ uses Redis delivery count
- search reports backend failures as 503 and rejects unsafe filter values
- JWT keys fail closed when key files are missing
"""

import os
import json
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, ANY

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import deepSightAI.Trinetra.ServerAndExtractor.extractor as dsai_ext


# ==============================================================================
# Extractor
# ==============================================================================

@pytest.mark.skipif(dsai_ext.Gst is None, reason="GStreamer not installed")
def test_dsai_extractor_start_returns_after_pipeline_error():
    """An unreachable camera must end start() so the reconnect loop can retry, not hang forever."""
    dsai_stop = threading.Event()
    with patch.object(dsai_ext, "ensure_bucket"):
        dsai_x = dsai_ext.GStreamerRtspExtractor(
            "rtsp://127.0.0.1:1/unreachable", "cam_probe", MagicMock(), "frames", dsai_stop, "t1", "cam_probe"
        )
        dsai_done = threading.Event()

        def dsai_run():
            dsai_x.start()
            dsai_done.set()

        threading.Thread(target=dsai_run, daemon=True).start()
        dsai_returned = dsai_done.wait(20)
    dsai_stop.set()
    assert dsai_returned, "start() did not return after the RTSP connection failed"


@pytest.mark.skipif(dsai_ext.Gst is None, reason="GStreamer not installed")
def test_dsai_extractor_url_is_not_parsed_as_pipeline_text():
    """A URL containing pipeline syntax must stay a plain property value on rtspsrc."""
    dsai_stop = threading.Event()
    dsai_stop.set()  # return right after the pipeline is built
    dsai_evil = "rtsp://127.0.0.1:1/x ! filesink location=/tmp/dsai_should_not_exist"
    with patch.object(dsai_ext, "ensure_bucket"):
        dsai_x = dsai_ext.GStreamerRtspExtractor(dsai_evil, "cam", MagicMock(), "frames", dsai_stop, "t1", "cam")
        dsai_x.start()
    assert dsai_x.pipeline.get_by_name("src").get_property("location") == dsai_evil
    dsai_element_types = [dsai_e.get_factory().get_name() for dsai_e in dsai_x.pipeline.iterate_elements()]
    assert "filesink" not in dsai_element_types


@pytest.mark.skipif(dsai_ext.Gst is None, reason="GStreamer not installed")
def test_dsai_extractor_codec_comes_from_request_not_url():
    """A '265' in the URL must not switch the stream to H.265."""
    dsai_x = dsai_ext.GStreamerRtspExtractor(
        "rtsp://10.0.0.5:2650/cam1265", "cam", MagicMock(), "frames", threading.Event(), "t1", "cam"
    )
    assert dsai_x.codec == "h264"
    dsai_y = dsai_ext.GStreamerRtspExtractor(
        "rtsp://10.0.0.5/cam", "cam", MagicMock(), "frames", threading.Event(), "t1", "cam", codec="HEVC"
    )
    assert dsai_y.codec == "h265"


@pytest.mark.skipif(dsai_ext.Gst is None, reason="GStreamer not installed")
def test_dsai_h265_decoder_skips_unusable_hardware():
    """A hardware decoder that is installed but cannot open its device must not be selected."""
    with patch.object(dsai_ext, "dsai_is_hw_decode_enabled", return_value=True), \
         patch.object(dsai_ext.Gst.ElementFactory, "find", return_value=True), \
         patch.object(dsai_ext, "dsai_decoder_is_usable", return_value=False):
        assert dsai_ext.dsai_detect_hardware_decoder_h265() == ("avdec_h265", False)


@pytest.fixture
def dsai_extractor_client():
    from deepSightAI.Trinetra.Shared.Middleware import require_auth
    dsai_ext.app.dependency_overrides[require_auth] = lambda: {"sub": "u", "roles": ["admin"]}
    with patch.object(dsai_ext, "run_rtsp_extraction_job") as dsai_job:
        yield TestClient(dsai_ext.app), dsai_job
    dsai_ext.app.dependency_overrides.pop(require_auth, None)
    with dsai_ext._rtsp_lock:
        dsai_ext._active_rtsp_streams.clear()
        dsai_ext._active_camera_streams.clear()


def test_dsai_extract_stream_ignores_base_timestamp_by_default(dsai_extractor_client, monkeypatch):
    dsai_client, dsai_job = dsai_extractor_client
    monkeypatch.delenv("DSAI_ALLOW_CLIENT_FRAME_TIMESTAMPS", raising=False)
    dsai_resp = dsai_client.post("/extract_stream", json={
        "rtsp_url": "rtsp://cam/live", "camera_id": "c1", "base_timestamp": 1000.0
    })
    assert dsai_resp.status_code == 200
    assert dsai_job.call_args.args[-1] is None  # base_timestamp not passed to the job


def test_dsai_extract_stream_honours_base_timestamp_in_test_mode(dsai_extractor_client, monkeypatch):
    dsai_client, dsai_job = dsai_extractor_client
    monkeypatch.setenv("DSAI_ALLOW_CLIENT_FRAME_TIMESTAMPS", "true")
    dsai_resp = dsai_client.post("/extract_stream", json={
        "rtsp_url": "rtsp://cam/live", "camera_id": "c2", "base_timestamp": 1000.0
    })
    assert dsai_resp.status_code == 200
    assert dsai_job.call_args.args[-1] == 1000.0


def test_dsai_extract_stream_rejects_bad_codec_and_scheme(dsai_extractor_client):
    dsai_client, _ = dsai_extractor_client
    assert dsai_client.post("/extract_stream", json={"rtsp_url": "rtsp://cam/live", "codec": "vp9"}).status_code == 422
    assert dsai_client.post("/extract_stream", json={"rtsp_url": "file:///etc/passwd"}).status_code == 422


def test_dsai_reconnect_keeps_sequence_across_restarts():
    """Test-mode timestamps must keep moving forward after a reconnect, not restart at base."""
    dsai_shutdown = MagicMock()
    dsai_shutdown.is_set.side_effect = [False, False, False, False] + [True] * 10
    dsai_seen_starts = []

    def dsai_make(**dsai_kwargs):
        dsai_inst = MagicMock()
        dsai_inst.sequence_counter = 0

        def dsai_start():
            dsai_seen_starts.append(dsai_inst.sequence_counter)
            dsai_inst.sequence_counter += 25  # 25 frames produced before the camera dropped

        dsai_inst.start.side_effect = dsai_start
        return dsai_inst

    with patch.object(dsai_ext, "GStreamerRtspExtractor", side_effect=dsai_make), \
         patch.object(dsai_ext.time, "sleep"), \
         patch.object(dsai_ext, "get_producer"), \
         patch.object(dsai_ext, "ensure_bucket"), \
         patch.object(dsai_ext, "Minio"), \
         patch.dict(os.environ, {"DSAI_MAX_STREAM_FAILURES": "5"}):
        dsai_ext.run_rtsp_extraction_job("rtsp://cam/live", "s1", dsai_shutdown, "t1", "c1", None, 1000.0)
    assert dsai_seen_starts == [0, 25]


# ==============================================================================
# Embedder
# ==============================================================================

def _dsai_frame_msg(dsai_bucket: str = "frames"):
    dsai_msg = MagicMock()
    dsai_msg.id = "1-0"
    dsai_msg.data = {"event": json.dumps({
        "video_id": "cam1", "segment_id": 0, "frame_paths": ["t1/cam1/f.jpg"], "timestamps": [1.0],
        "sequence_numbers": [0], "extractor_id": "e1", "bucket_name": dsai_bucket,
        "timestamp": datetime.now(timezone.utc).isoformat(), "tenant_id": "t1", "camera_id": "cam1",
    })}
    return dsai_msg


def test_dsai_embedder_milvus_insert_failure_propagates():
    """If the Milvus write fails, the frame processor must raise so the event is not ACKed."""
    from deepSightAI.Trinetra.Embedder import embedder as dsai_emb
    dsai_coll = MagicMock()
    dsai_coll.schema.fields = [MagicMock()] * 7
    dsai_coll.insert.side_effect = RuntimeError("milvus down")
    with patch.object(dsai_emb, "download_rtsp_frame_objects", return_value=["/tmp/x.jpg"]), \
         patch.object(dsai_emb, "encode_images", return_value=__import__("torch").zeros((1, 512))), \
         patch.object(dsai_emb, "frame_exists", return_value=False), \
         patch.object(dsai_emb, "cleanup_temp_files"), \
         patch.object(dsai_emb, "dsai_check_circuit_breaker"), \
         patch.object(dsai_emb, "mark_rtsp_bucket_processed") as dsai_mark:
        with pytest.raises(RuntimeError):
            dsai_emb.process_rtsp_frames(MagicMock(), dsai_coll, "frames-rtsp-cam1", ["f.jpg"], timestamps=[1.0],
                                         tenant_id="t1", camera_id="cam1")
    dsai_mark.assert_not_called()


def test_dsai_embedder_uses_redis_delivery_count_for_dlq():
    """A message already delivered 3 times (e.g. by other workers) goes to the DLQ on this failure."""
    from deepSightAI.Trinetra.Embedder import embedder as dsai_emb
    dsai_consumer = MagicMock()
    dsai_consumer.autoclaim.return_value = []
    dsai_consumer.read.return_value = [_dsai_frame_msg()]
    dsai_consumer.dsai_delivery_count.return_value = 3
    dsai_producer = MagicMock()
    with patch.object(dsai_emb, "process_segment_frames", side_effect=RuntimeError("boom")), \
         patch.object(dsai_emb, "get_milvus_collection", return_value=MagicMock()), \
         patch.dict(os.environ, {"MAX_MESSAGE_RETRIES": "3"}):
        dsai_emb.process_events(consumer=dsai_consumer, producer=dsai_producer, minio_client=MagicMock(),
                                max_iterations=1)
    dsai_producer.publish.assert_called_with("events:dlq", ANY)
    dsai_consumer.ack.assert_called_once_with("frames", "1-0")


def test_dsai_embedder_does_not_ack_when_dlq_publish_fails():
    """If the DLQ write fails, leave the event pending so it is retried instead of lost."""
    from deepSightAI.Trinetra.Embedder import embedder as dsai_emb
    dsai_consumer = MagicMock()
    dsai_consumer.autoclaim.return_value = []
    dsai_consumer.read.return_value = [_dsai_frame_msg()]
    dsai_consumer.dsai_delivery_count.return_value = 5
    dsai_producer = MagicMock()
    dsai_producer.publish.side_effect = RuntimeError("redis down")
    with patch.object(dsai_emb, "process_segment_frames", side_effect=RuntimeError("boom")), \
         patch.object(dsai_emb, "get_milvus_collection", return_value=MagicMock()), \
         patch.dict(os.environ, {"MAX_MESSAGE_RETRIES": "3"}):
        dsai_emb.process_events(consumer=dsai_consumer, producer=dsai_producer, minio_client=MagicMock(),
                                max_iterations=1)
    dsai_consumer.ack.assert_not_called()


def test_dsai_consumer_delivery_count_reads_redis():
    from deepSightAI.Trinetra.Shared.Streaming.Consumer import StreamConsumer
    dsai_redis = MagicMock()
    dsai_redis.xpending_range.return_value = [{"message_id": "1-0", "times_delivered": 4}]
    dsai_consumer = StreamConsumer("embedder-group", "c1", redis_client=dsai_redis)
    assert dsai_consumer.dsai_delivery_count("frames", "1-0") == 4
    dsai_redis.xpending_range.side_effect = RuntimeError("down")
    assert dsai_consumer.dsai_delivery_count("frames", "1-0") == 0


# ==============================================================================
# Search
# ==============================================================================

@pytest.fixture
def dsai_search_client():
    from deepSightAI.Trinetra.SearchService.main import app, require_auth
    app.dependency_overrides[require_auth] = lambda: {"sub": "u", "tenant_id": "t1", "permissions": ["search:read"]}
    yield TestClient(app)
    app.dependency_overrides.pop(require_auth, None)


def test_dsai_search_backend_failure_is_503_not_empty(dsai_search_client):
    dsai_coll = MagicMock()
    dsai_coll.search.side_effect = RuntimeError("milvus down")
    with patch("deepSightAI.Trinetra.SearchService.main.get_milvus_collection", return_value=dsai_coll), \
         patch("deepSightAI.Trinetra.SearchService.main.dsai_encode_text_query", return_value=np.zeros(512, dtype=np.float32)):
        dsai_resp = dsai_search_client.post("/search/text", json={"query_text": "a red car"})
    assert dsai_resp.status_code == 503


def test_dsai_search_without_text_model_is_503(dsai_search_client):
    with patch("deepSightAI.Trinetra.SearchService.main.model", None), \
         patch("deepSightAI.Trinetra.SearchService.main.get_milvus_collection", return_value=MagicMock()):
        dsai_resp = dsai_search_client.post("/search/text", json={"query_text": "a red car"})
    assert dsai_resp.status_code == 503


def test_dsai_search_rejects_filter_injection(dsai_search_client):
    with patch("deepSightAI.Trinetra.SearchService.main.get_milvus_collection", return_value=MagicMock()), \
         patch("deepSightAI.Trinetra.SearchService.main.dsai_encode_text_query", return_value=np.zeros(512, dtype=np.float32)):
        dsai_resp = dsai_search_client.post("/search/text", json={
            "query_text": "a red car", "camera_ids": ['cam1"] or camera_id != "x']
        })
    assert dsai_resp.status_code == 422


def test_dsai_scalar_expr_quotes_plain_values():
    from deepSightAI.Trinetra.SearchService.main import dsai_build_scalar_expr
    assert dsai_build_scalar_expr(camera_ids=["cam_1", "cam-2"], time_start=1.0) == \
        'camera_id in ["cam_1", "cam-2"] and frame_timestamp >= 1.0'
    with pytest.raises(HTTPException):
        dsai_build_scalar_expr(plate_number='AB"12')


# ==============================================================================
# Auth keys
# ==============================================================================

def test_dsai_jwt_keys_fail_closed_without_key_files(monkeypatch):
    from deepSightAI.Trinetra.AuthService import auth_service as dsai_auth
    monkeypatch.delenv("JWT_PRIVATE_KEY_PATH", raising=False)
    monkeypatch.delenv("JWT_PUBLIC_KEY_PATH", raising=False)
    monkeypatch.setenv("DSAI_ALLOW_EPHEMERAL_JWT_KEYS", "false")
    with pytest.raises(RuntimeError, match="JWT key files not found"):
        dsai_auth.dsai_load_or_generate_rsa_keys()
    monkeypatch.setenv("DSAI_ALLOW_EPHEMERAL_JWT_KEYS", "true")
    dsai_priv, dsai_pub = dsai_auth.dsai_load_or_generate_rsa_keys()
    assert b"PRIVATE KEY" in dsai_priv and b"PUBLIC KEY" in dsai_pub


def test_dsai_image_search_rejects_unreadable_image(dsai_search_client):
    """An unreadable reference image is a 422, never a search with a random vector."""
    with patch("deepSightAI.Trinetra.SearchService.main.ensure_vehicle_collection", return_value=MagicMock()):
        dsai_resp = dsai_search_client.post("/search/vehicle", json={"reference_image_base64": "not-an-image"})
    assert dsai_resp.status_code == 422


def test_dsai_image_search_without_model_is_503(dsai_search_client):
    import base64, io
    from PIL import Image
    dsai_buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(dsai_buf, format="PNG")
    dsai_b64 = base64.b64encode(dsai_buf.getvalue()).decode()
    with patch("deepSightAI.Trinetra.SearchService.main.model", None), \
         patch("deepSightAI.Trinetra.SearchService.main.ensure_person_collection", return_value=MagicMock()):
        dsai_resp = dsai_search_client.post("/search/person", json={"reference_image_base64": dsai_b64})
    assert dsai_resp.status_code == 503
