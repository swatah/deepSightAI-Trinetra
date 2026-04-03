"""
T2.2.1: Design event schema and Redis Streams integration

Tests for event Pydantic models and Redis client utilities.
"""

import pytest
import json
from datetime import datetime
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import the modules we will implement
from shared.streaming.schema import (
    IngestJobStarted,
    IngestJobCompleted,
    FrameReadyEvent,
    EmbedderProcessingStarted,
    EmbedderProcessingCompleted,
)
from shared.streaming.redis_client import create_redis_client, get_redis_url


class TestEventSchema:
    """Test event Pydantic models."""

    def test_ingest_job_started_creation(self):
        """Can create IngestJobStarted with required fields."""
        event = IngestJobStarted(
            job_id="job-123",
            source_type="file",
            source_identifier="videos/abc.mp4",
            tenant_id="tenant-1",
            timestamp=datetime.utcnow()
        )
        assert event.job_id == "job-123"
        assert event.event_type == "ingest.started"
        assert event.source_type == "file"

    def test_ingest_job_started_serialization(self):
        """IngestJobStarted serializes to JSON correctly."""
        ts = datetime(2025, 1, 1, 12, 0, 0)
        event = IngestJobStarted(
            job_id="job-1",
            source_type="rtsp",
            source_identifier="rtsp://camera/stream",
            tenant_id="acme",
            timestamp=ts
        )
        data = json.loads(event.model_dump_json())
        assert data["job_id"] == "job-1"
        assert data["event_type"] == "ingest.started"
        assert data["source_type"] == "rtsp"
        assert data["timestamp"] == ts.isoformat()

    def test_ingest_job_started_deserialization(self):
        """Can parse IngestJobStarted from JSON."""
        payload = {
            "event_type": "ingest.started",
            "job_id": "job-456",
            "source_type": "file",
            "source_identifier": "videos/test.mp4",
            "tenant_id": "tenant-99",
            "timestamp": "2025-01-02T15:30:00"
        }
        event = IngestJobStarted(**payload)
        assert event.job_id == "job-456"
        assert event.tenant_id == "tenant-99"

    def test_ingest_job_started_invalid_source_type(self):
        """Invalid source_type should raise validation error."""
        with pytest.raises(Exception):  # pydantic.ValidationError
            IngestJobStarted(
                job_id="x",
                source_type="invalid",
                source_identifier="x",
                tenant_id="x",
                timestamp=datetime.utcnow()
            )

    def test_ingest_job_completed_creation(self):
        event = IngestJobCompleted(
            job_id="job-999",
            source_type="file",
            video_id="video-abc",
            frame_count=300,
            duration_seconds=30.5,
            timestamp=datetime.utcnow()
        )
        assert event.frame_count == 300
        assert event.duration_seconds == 30.5

    def test_frame_ready_event_creation(self):
        event = FrameReadyEvent(
            video_id="video-1",
            segment_id=0,
            frame_paths=[
                "frames/video1/segment_0000/frame_00001.jpg",
                "frames/video1/segment_0000/frame_00002.jpg",
                "frames/video1/segment_0000/frame_00003.jpg"
            ],
            timestamps=[0.0, 1.0, 2.0],
            sequence_numbers=[0, 1, 2],
            extractor_id="extractor-1",
            bucket_name="frames",
            timestamp=datetime.utcnow()
        )
        assert len(event.frame_paths) == 3
        assert event.extractor_id == "extractor-1"

    def test_frame_ready_event_mismatched_lengths_should_fail(self):
        """frame_paths and timestamps must have same length."""
        with pytest.raises(Exception):
            FrameReadyEvent(
                video_id="v1",
                segment_id=0,
                frame_paths=["a.jpg", "b.jpg"],
                timestamps=[1.0],  # mismatch
                sequence_numbers=[0, 1],
                extractor_id="ex1",
                bucket_name="frames",
                timestamp=datetime.utcnow()
            )

    def test_embedder_processing_events(self):
        started = EmbedderProcessingStarted(
            video_id="v1",
            consumer_id="embedder-1",
            timestamp=datetime.utcnow()
        )
        assert started.event_type == "embedder.started"

        completed = EmbedderProcessingCompleted(
            video_id="v1",
            frames_processed=100,
            embeddings_inserted=100,
            duration_seconds=5.2,
            timestamp=datetime.utcnow()
        )
        assert completed.frames_processed == 100
        assert completed.embeddings_inserted == 100


class TestRedisClient:
    """Test Redis client utility functions."""

    def test_create_redis_client_from_env(self):
        """create_redis_client uses REDIS_URL from environment."""
        with patch.dict('os.environ', {'REDIS_URL': 'redis://test-redis:6379'}):
            with patch('redis.Redis') as mock_redis_cls:
                client = create_redis_client()
                mock_redis_cls.from_url.assert_called_once_with('redis://test-redis:6379', decode_responses=True)

    def test_create_redis_client_default(self):
        """create_redis_client uses default URL if env not set."""
        with patch.dict('os.environ', {}, clear=True):
            with patch('redis.Redis') as mock_redis_cls:
                client = create_redis_client()
                mock_redis_cls.from_url.assert_called_once_with('redis://redis:6379', decode_responses=True)

    def test_get_redis_url_from_env(self):
        with patch.dict('os.environ', {'REDIS_URL': 'redis://custom:6380'}):
            url = get_redis_url()
            assert url == 'redis://custom:6380'

    def test_get_redis_url_default(self):
        with patch.dict('os.environ', {}, clear=True):
            url = get_redis_url()
            assert url == 'redis://redis:6379'
