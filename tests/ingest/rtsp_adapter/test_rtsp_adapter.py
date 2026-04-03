"""
T2.2.6: Implement RtspSourceAdapter

Tests for RtspAdapter that handles RTSP stream ingestion.
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Add repo root and Server and Extractor directory to path
repo_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "Server and Extractor"))

from adapters.rtsp_adapter import RtspAdapter


class TestRtspAdapter:
    """Test RtspAdapter class."""

    def test_adapter_exists(self):
        """RtspAdapter should be defined."""
        assert RtspAdapter is not None

    def test_prepare_method_exists(self):
        """RtspAdapter should have a prepare method."""
        assert hasattr(RtspAdapter, 'prepare')

    def test_prepare_returns_payload_dict(self):
        """prepare should return a dictionary with required keys."""
        adapter = RtspAdapter()
        payload = adapter.prepare(
            rtsp_url="rtsp://camera.example.com/stream",
            job_id="job-123",
            video_id="video-123",
            tenant_id="tenant-1"
        )

        assert isinstance(payload, dict)
        assert payload["job_id"] == "job-123"
        assert payload["video_id"] == "video-123"
        assert payload["source_type"] == "rtsp"
        assert payload["rtsp_url"] == "rtsp://camera.example.com/stream"
        assert payload["tenant_id"] == "tenant-1"

    def test_prepare_validates_rtsp_url(self):
        """prepare should validate RTSP URL format (basic check)."""
        adapter = RtspAdapter()

        # Valid RTSP URL
        payload = adapter.prepare(
            rtsp_url="rtsp://192.168.1.1:554/stream",
            job_id="j",
            video_id="v",
            tenant_id="t"
        )
        assert payload["rtsp_url"] == "rtsp://192.168.1.1:554/stream"

        # Could also accept other URL schemes? For now, just ensure it's passed through
        payload2 = adapter.prepare(
            rtsp_url="rtsps://secure.example.com/stream",
            job_id="j2",
            video_id="v2",
            tenant_id="t2"
        )
        assert payload2["rtsp_url"] == "rtsps://secure.example.com/stream"

    def test_prepare_no_validation_by_default(self):
        """Currently prepare does not validate connectivity (that's extractor's job)."""
        adapter = RtspAdapter()
        # Should accept any string URL without checking
        payload = adapter.prepare(
            rtsp_url="not-a-real-url",
            job_id="j",
            video_id="v",
            tenant_id="t"
        )
        assert payload["rtsp_url"] == "not-a-real-url"

    def test_adapter_initialization_with_config(self):
        """RtspAdapter can be initialized with config if needed."""
        adapter = RtspAdapter(timeout=30.0, retries=3)
        assert adapter.timeout == 30.0
        assert adapter.retries == 3

    def test_prepare_generates_unique_identifiers(self):
        """prepare should use provided IDs correctly."""
        adapter = RtspAdapter()
        payload = adapter.prepare(
            rtsp_url="rtsp://cam/stream",
            job_id="job-abc-123",
            video_id="video-def-456",
            tenant_id="tenant-xyz"
        )
        assert payload["job_id"] == "job-abc-123"
        assert payload["video_id"] == "video-def-456"
        # IDs should be passed through, not regenerated
