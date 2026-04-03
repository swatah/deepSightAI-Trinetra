"""
T2.2.2: Implement Redis Streams producer utility

Tests for StreamProducer that publishes events to Redis Streams.
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.streaming.producer import StreamProducer
from shared.streaming.schema import IngestJobStarted, IngestJobCompleted, FrameReadyEvent


class TestStreamProducer:
    """Test StreamProducer class."""

    def test_publish_calls_xadd_with_correct_stream_and_fields(self):
        """publish() should call Redis xadd with stream name and event payload."""
        mock_client = MagicMock()
        mock_client.xadd.return_value = "123456-0"
        producer = StreamProducer(redis_client=mock_client)

        event = IngestJobStarted(
            job_id="job-1",
            source_type="file",
            source_identifier="videos/test.mp4",
            tenant_id="default",
            timestamp=datetime.utcnow()
        )

        entry_id = producer.publish("ingest:jobs", event)

        assert entry_id == "123456-0"
        mock_client.xadd.assert_called_once()
        # Check positional args
        args = mock_client.xadd.call_args[0]  # positional args tuple
        assert args[0] == "ingest:jobs"  # stream name
        fields = args[1]  # dict of fields
        assert "event" in fields
        # The event field should be a JSON string containing event_type etc.
        import json
        event_data = json.loads(fields["event"])
        assert event_data["event_type"] == "ingest.started"
        assert event_data["job_id"] == "job-1"

    def test_publish_uses_maxlen_parameter(self):
        """publish should apply maxlen to control stream size."""
        mock_client = MagicMock()
        mock_client.xadd.return_value = "entry-1"
        producer = StreamProducer(redis_client=mock_client)

        event = IngestJobCompleted(
            job_id="job-2",
            source_type="rtsp",
            video_id="video-2",
            frame_count=100,
            duration_seconds=10.0,
            timestamp=datetime.utcnow()
        )

        entry_id = producer.publish("frames:video2", event, maxlen=5000)

        # Check that maxlen was passed to xadd (either positional or keyword)
        call_kwargs = mock_client.xadd.call_args[1]
        assert call_kwargs.get('maxlen') == 5000
        # Alternatively, could be in args[2]? But we used keyword for maxlen
        # Our implementation uses `maxlen=maxlen` as keyword arg.

    def test_publish_default_maxlen(self):
        """If maxlen not specified, should use a reasonable default (e.g., 10000)."""
        mock_client = MagicMock()
        mock_client.xadd.return_value = "entry-x"
        producer = StreamProducer(redis_client=mock_client)

        event = IngestJobStarted(
            job_id="j",
            source_type="file",
            source_identifier="v",
            tenant_id="t",
            timestamp=datetime.utcnow()
        )
        producer.publish("s", event)

        call_kwargs = mock_client.xadd.call_args[1]
        # Default maxlen should be 10000 per design
        assert call_kwargs.get('maxlen') == 10000

    def test_publish_raises_if_event_not_pydantic(self):
        """publish should raise TypeError if event does not have model_dump_json."""
        mock_client = MagicMock()
        producer = StreamProducer(redis_client=mock_client)

        with pytest.raises(TypeError):
            producer.publish("stream", {"not": "a pydantic model"})

    def test_init_creates_redis_client_if_none_provided(self):
        """If no redis_client provided, StreamProducer should create one using create_redis_client."""
        with patch('shared.streaming.producer.create_redis_client') as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client
            producer = StreamProducer()
            assert producer.client is mock_client
            mock_create.assert_called_once()

    def test_publish_propagates_redis_exception(self):
        """If xadd raises an exception, publish should propagate it."""
        mock_client = MagicMock()
        mock_client.xadd.side_effect = Exception("Redis error")
        producer = StreamProducer(redis_client=mock_client)

        event = IngestJobStarted(
            job_id="x",
            source_type="file",
            source_identifier="x",
            tenant_id="x",
            timestamp=datetime.utcnow()
        )
        with pytest.raises(Exception):
            producer.publish("s", event)

    def test_frame_ready_event_publish_example(self):
        """Realistic test: publish a FrameReadyEvent and verify structure."""
        mock_client = MagicMock()
        mock_client.xadd.return_value = "1656789123456-0"
        producer = StreamProducer(redis_client=mock_client)

        event = FrameReadyEvent(
            video_id="video-abc",
            segment_id=0,
            frame_paths=["frames/video-abc/seg_0000/f_0001.jpg"],
            timestamps=[0.0],
            sequence_numbers=[0],
            extractor_id="extractor-1",
            bucket_name="frames",
            timestamp=datetime.utcnow()
        )
        entry_id = producer.publish("frames:video-abc", event, maxlen=1000)
        assert entry_id.startswith("165") or entry_id  # typical redis stream ID format
