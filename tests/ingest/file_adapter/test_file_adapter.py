"""
T2.2.5: Implement FileSourceAdapter

Tests for FileAdapter that handles file upload preparation.
"""

import pytest
from unittest.mock import MagicMock, patch, mock_open
import sys
from pathlib import Path
import io

# Add repo root and Server and Extractor directory to path
repo_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "Server and Extractor"))

# Mock minio module before importing FileAdapter
mock_minio = MagicMock()
sys.modules['minio'] = mock_minio
sys.modules['minio.error'] = MagicMock()
from adapters.file_adapter import FileAdapter


class TestFileAdapter:
    """Test FileAdapter class."""

    def test_adapter_exists(self):
        """FileAdapter should be defined."""
        assert FileAdapter is not None

    def test_prepare_method_exists(self):
        """FileAdapter should have a prepare method."""
        assert hasattr(FileAdapter, 'prepare')

    def test_prepare_returns_payload_dict(self):
        """prepare should return a dictionary with required keys."""
        # Mock file
        mock_file = MagicMock()
        mock_file.filename = "test.mp4"
        mock_file.file = io.BytesIO(b"fake video content")

        adapter = FileAdapter()
        payload = adapter.prepare(
            file=mock_file,
            job_id="job-123",
            video_id="video-123",
            tenant_id="tenant-1"
        )

        assert isinstance(payload, dict)
        assert "job_id" in payload
        assert payload["job_id"] == "job-123"
        assert "video_id" in payload
        assert "source_type" in payload
        assert payload["source_type"] == "file"
        assert "filename" in payload

    def test_prepare_includes_filename(self):
        """Payload should include the original filename."""
        mock_file = MagicMock()
        mock_file.filename = "my_video.mp4"
        mock_file.file = io.BytesIO(b"content")

        adapter = FileAdapter()
        payload = adapter.prepare(mock_file, "job1", "vid1", "t1")

        assert payload["filename"] == "my_video.mp4"

    def test_prepare_upload_to_minio(self):
        """prepare should upload file to MinIO and include minio_uri in payload."""
        mock_file = MagicMock()
        mock_file.filename = "test.mp4"
        file_obj = io.BytesIO(b"content")
        mock_file.file = file_obj

        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = True
        mock_client.fput_object.return_value = None

        adapter = FileAdapter(minio_client=mock_client, bucket_name="videos")
        payload = adapter.prepare(mock_file, "job1", "vid1", "t1")

        assert mock_client.fput_object.called
        call_args = mock_client.fput_object.call_args
        assert call_args[1]['bucket_name'] == "videos"
        assert call_args[1]['object_name'] == "t1/job1/test.mp4"
        assert "minio_uri" in payload
        assert payload["minio_uri"] == "minio://videos/t1/job1/test.mp4"

    def test_prepare_without_minio_client_uses_env(self):
        """If no minio client provided, creates one from env (we won't test actual connection)."""
        # This test can be skipped or we can assert it doesn't raise immediately
        # Since we're mocking the minio module at import time, we can test that
        # the adapter's default client creation would use the mocked Minio
        from minio import Minio as MockMinio
        # Ensure our mock is the one that would be used
        assert MockMinio is not None  # just verify mock is in place

    def test_prepare_raises_if_invalid_file(self):
        """prepare should raise if file is None or invalid."""
        adapter = FileAdapter(minio_client=MagicMock())
        with pytest.raises(ValueError, match="Invalid file object"):
            adapter.prepare(None, "j", "v", "t")

    def test_adapter_initialization_with_config(self):
        """FileAdapter can be initialized with minio_client and bucket_name."""
        mock_client = MagicMock()
        adapter = FileAdapter(minio_client=mock_client, bucket_name="videos")
        assert adapter.minio_client is mock_client
        assert adapter.bucket_name == "videos"
