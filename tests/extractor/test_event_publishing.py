"""
T2.2.7: Add event publishing to extractor after frame upload

Tests for FrameReadyEvent publishing from extractor service.
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
import os
from datetime import datetime

# Add repo root to path: test file is at tests/extractor/test_...py
# repo_root is the project root containing Server and Extractor
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "Server and Extractor"))

# Mock external dependencies if they are not installed to allow module import for testing
# GStreamer
try:
    import gi
    from gi.repository import Gst, GLib
except ImportError:
    gi = MagicMock()
    sys.modules['gi'] = gi
    sys.modules['gi.repository'] = MagicMock()
    sys.modules['gi.repository.Gst'] = MagicMock()
    sys.modules['gi.repository.GLib'] = MagicMock()
    gi.require_version = MagicMock()
    Gst = MagicMock()
    Gst.init = MagicMock()
    GLib = MagicMock()

# ffmpeg-python
try:
    import ffmpeg
except ImportError:
    sys.modules['ffmpeg'] = MagicMock()

# httpx
try:
    import httpx
except ImportError:
    sys.modules['httpx'] = MagicMock()

# minio and minio.error
try:
    from minio import Minio
    import minio.error
except ImportError:
    sys.modules['minio'] = MagicMock()
    sys.modules['minio.error'] = MagicMock()

# Now import extractor components
try:
    from extractor import run_file_extraction_job, GStreamerRtspExtractor, publish_frame_ready_event, get_producer
    EXTRACTOR_AVAILABLE = True
except Exception as e:
    print(f"DEBUG: Failed to import extractor: {e}")
    import traceback
    traceback.print_exc()
    EXTRACTOR_AVAILABLE = False
    pytest.skip(f"Extractor module not available: {e}", allow_module_level=True)


class TestPublishFrameReadyEvent:
    """Test the publish_frame_ready_event helper."""

    @patch('extractor._producer')
    def test_publish_calls_producer_with_correct_stream(self, mock_producer):
        """Should publish to frames:{video_id} stream."""
        mock_producer.publish.return_value = "msg-id-123"

        publish_frame_ready_event(
            video_id="video-123",
            segment_id=0,
            frame_paths=["frames/video-123/seg_0000/f1.jpg"],
            timestamps=[0.0],
            sequence_numbers=[0]
        )

        assert mock_producer.publish.called
        args = mock_producer.publish.call_args[0]
        stream_name = args[0]
        event = args[1]
        assert stream_name == "frames"
        assert event.video_id == "video-123"
        assert event.segment_id == 0
        assert event.frame_paths == ["frames/video-123/seg_0000/f1.jpg"]
        assert event.timestamps == [0.0]
        assert event.sequence_numbers == [0]
        assert event.event_type == "frame.ready"
        assert event.extractor_id == "default_extractor"
        assert event.bucket_name == "frames"

    @patch('extractor._producer')
    def test_publish_handles_errors(self, mock_producer):
        """If publish fails, should not raise."""
        mock_producer.publish.side_effect = Exception("Redis down")
        publish_frame_ready_event(
            video_id="v",
            segment_id=0,
            frame_paths=["a.jpg"],
            timestamps=[0],
            sequence_numbers=[0]
        )

    @patch('extractor._producer')
    def test_publish_with_custom_bucket(self, mock_producer):
        """Should use provided bucket_name."""
        publish_frame_ready_event(
            video_id="v",
            segment_id=1,
            frame_paths=["a.jpg"],
            timestamps=[0],
            sequence_numbers=[0],
            bucket_name="custom"
        )
        event = mock_producer.publish.call_args[0][1]
        assert event.bucket_name == "custom"


class TestFileExtractionPublishesEvent:
    """Test that run_file_extraction_job publishes after frames uploaded."""

    @patch('extractor.httpx.Client')
    @patch('extractor.Minio')
    @patch('extractor.publish_frame_ready_event')
    @patch('extractor.ffmpeg')
    @patch('extractor.GStreamerFileExtractor')
    def test_file_job_publishes_frame_ready_event(
        self, mock_extractor_cls, mock_ffmpeg, mock_publish,
        mock_minio_cls, mock_httpx_client
    ):
        """After uploading frames, should publish FrameReadyEvent."""
        # Setup mocks
        mock_extractor = mock_extractor_cls.return_value
        def fake_extract(input_file, output_dir):
            os.makedirs(output_dir, exist_ok=True)
            for i in range(3):
                with open(os.path.join(output_dir, f"frame_{i:05d}.jpg"), 'wb') as f:
                    f.write(b"fake")
        mock_extractor.extract_frames.side_effect = fake_extract

        mock_minio = MagicMock()
        mock_minio.bucket_exists.return_value = True
        mock_minio_cls.return_value = mock_minio

        def fake_fget(bucket, key, local_path):
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, 'wb') as f:
                f.write(b"video")
        mock_minio.fget_object.side_effect = fake_fget

        mock_httpx = MagicMock()
        mock_httpx_client.return_value.__enter__.return_value = mock_httpx

        # Execute
        run_file_extraction_job("videos/test.mp4", 0, 0.0, 10.0)

        # Verify
        assert mock_publish.called
        kwargs = mock_publish.call_args[1]
        assert kwargs['video_id'] == "test"
        assert kwargs['segment_id'] == 0
        assert len(kwargs['frame_paths']) == 3
        assert kwargs['timestamps'] == [0.0, 1.0, 2.0]
        assert kwargs['sequence_numbers'] == [0, 1, 2]
