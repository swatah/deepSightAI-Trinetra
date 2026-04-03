"""
T2.2.4: Create Unified Ingest Service endpoint

Tests for POST /ingest endpoint that handles multiple source types.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock
import sys
from pathlib import Path
from datetime import datetime
import uuid

# Add repo root and Server and Extractor directory to path
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "Server and Extractor"))

# We'll import the app after it's created
from ingest_service import app, get_extractor, publish_event, get_job_id

# Override dependencies for testing
def mock_get_extractor():
    """Mock extractor registry - returns a mock extractor."""
    return {"extractor_url": "http://test-extractor:8000"}

def mock_publish_event(stream, event):
    """Mock event publisher."""
    pass

app.dependency_overrides[get_extractor] = mock_get_extractor
app.dependency_overrides[publish_event] = mock_publish_event


@pytest.fixture
def client():
    """Test client for the ingest service."""
    return TestClient(app)


class TestUnifiedIngestEndpoint:
    """Test POST /ingest endpoint."""

    def test_ingest_file_upload_returns_job_id(self, client):
        """Uploading a file should return job_id and status accepted."""
        # Create a fake file
        files = {"file": ("test.mp4", b"fake video content", "video/mp4")}
        data = {"source_type": "file"}

        response = client.post("/ingest", files=files, data=data)

        assert response.status_code == 200
        result = response.json()
        assert "job_id" in result
        assert result["status"] == "accepted"
        assert "video_id" in result
        # Validate job_id is a UUID
        uuid.UUID(result["job_id"])  # should not raise

    def test_ingest_rtsp_url_returns_job_id(self, client):
        """Submitting RTSP URL should return job_id and status."""
        json_data = {
            "source_type": "rtsp",
            "rtsp_url": "rtsp://camera.example.com/stream"
        }

        response = client.post("/ingest", json=json_data)

        assert response.status_code == 200
        result = response.json()
        assert "job_id" in result
        assert result["status"] == "accepted"
        assert result["source_type"] == "rtsp"

    def test_ingest_invalid_source_type_returns_400(self, client):
        """Invalid source_type should return 400."""
        json_data = {
            "source_type": "invalid",
            "rtsp_url": "rtsp://example.com"
        }

        response = client.post("/ingest", json=json_data)
        assert response.status_code == 400
        assert "source_type" in response.json()["detail"].lower()

    def test_ingest_file_without_file_returns_400(self, client):
        """source_type='file' without file upload should return 400."""
        response = client.post("/ingest", data={"source_type": "file"})
        assert response.status_code == 400

    def test_ingest_rtsp_without_url_returns_400(self, client):
        """source_type='rtsp' without rtsp_url should return 400."""
        response = client.post("/ingest", json={"source_type": "rtsp"})
        assert response.status_code == 400

    def test_ingest_publishes_started_event(self, client):
        """Should publish IngestJobStarted event to control:ingest stream."""
        with patch('ingest_service.publish_event') as mock_publish:
            files = {"file": ("test.mp4", b"content", "video/mp4")}
            data = {"source_type": "file"}

            response = client.post("/ingest", files=files, data=data)

            assert response.status_code == 200
            # Check that publish_event was called
            assert mock_publish.called
            # Get the call arguments
            call_args = mock_publish.call_args
            stream_name = call_args[0][0]
            event = call_args[0][1]
            assert stream_name == "control:ingest"
            assert event.event_type == "ingest.started"
            assert event.job_id == response.json()["job_id"]

    def test_ingest_dispatches_to_extractor(self, client):
        """Should dispatch job to extractor service."""
        with patch('ingest_service.get_extractor') as mock_get_ext, \
             patch('ingest_service.dispatch_to_extractor') as mock_dispatch:

            mock_get_ext.return_value = {"extractor_url": "http://extractor:8000"}

            files = {"file": ("test.mp4", b"content", "video/mp4")}
            data = {"source_type": "file"}

            response = client.post("/ingest", files=files, data=data)

            assert response.status_code == 200
            assert mock_dispatch.called
            # dispatch_to_extractor should be called with extractor_url, job_payload

    def test_ingest_returns_job_status_endpoint(self, client):
        """GET /ingest/{job_id} should return job status (optional but nice to have)."""
        # This is a bonus: the design mentions optional status endpoint
        response = client.get("/ingest/nonexistent-job")
        # Should return 200 or 404 depending on implementation
        # For now, we can skip this test or expect 404
        assert response.status_code in [200, 404]

    def test_ingest_file_upload_with_tenant_header(self, client):
        """If tenant_id is provided via header or auth, should include in event."""
        # This can be advanced - test tenant propagation
        files = {"file": ("test.mp4", b"content", "video/mp4")}
        data = {"source_type": "file"}

        response = client.post("/ingest", files=files, data=data, headers={"X-Tenant-ID": "tenant-123"})

        assert response.status_code == 200
        # Check that event includes tenant_id if header present
        with patch('ingest_service.publish_event') as mock_publish:
            client.post("/ingest", files=files, data=data, headers={"X-Tenant-ID": "tenant-123"})
            event = mock_publish.call_args[0][1]
            assert getattr(event, 'tenant_id', None) == 'tenant-123'


class TestAdapters:
    """Test adapter implementations (stubs for T2.2.5 and T2.2.6)."""

    def test_file_adapter_exists(self):
        """FileAdapter should be importable."""
        try:
            from Server_and_Extractor.adapters import FileAdapter
            assert hasattr(FileAdapter, 'prepare')
            assert hasattr(FileAdapter, 'dispatch_payload')
        except ImportError:
            pytest.skip("FileAdapter not implemented yet (T2.2.5)")

    def test_rtsp_adapter_exists(self):
        """RtspAdapter should be importable."""
        try:
            from Server_and_Extractor.adapters import RtspAdapter
            assert hasattr(RtspAdapter, 'prepare')
            assert hasattr(RtspAdapter, 'dispatch_payload')
        except ImportError:
            pytest.skip("RtspAdapter not implemented yet (T2.2.6)")


class TestEventPublishing:
    """Test that events are correctly published."""

    def test_ingest_job_started_event_structure(self):
        """Verify IngestJobStarted event has required fields."""
        from shared.streaming.schema import IngestJobStarted

        event = IngestJobStarted(
            job_id="test-job",
            source_type="file",
            source_identifier="videos/test.mp4",
            tenant_id="default",
            timestamp=datetime.utcnow()
        )
        assert event.event_type == "ingest.started"
        assert event.job_id == "test-job"
        assert event.source_type in ["file", "rtsp", "hls"]
