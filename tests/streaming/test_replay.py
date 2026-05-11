"""
Test replay service: reprocess historical events for a video (T2.2.9).
"""
import pytest
from unittest.mock import patch, MagicMock
from shared.streaming.replay import ReplayService
from shared.streaming.schema import FrameReadyEvent
from shared.streaming.producer import StreamProducer
from datetime import datetime


def test_replay_service_reprocesses_events():
    """ReplayService.replay(video_id) reads past events and republishes them."""
    with patch('shared.streaming.replay.create_redis_client') as mock_redis, \
         patch('shared.streaming.replay.StreamProducer') as mock_producer_cls:
        # Setup
        fake_event1 = FrameReadyEvent(
            event_type="frame.ready", video_id="vid123",
            segment_id=0, frame_paths=["vid123/seg1/frame1.jpg"],
            timestamps=[0.0], sequence_numbers=[0], extractor_id="extractor-1",
            bucket_name="frames", timestamp=datetime(2025, 4, 3, 10, 0, 0)
        )
        fake_event2 = FrameReadyEvent(
            event_type="frame.ready", video_id="vid123",
            segment_id=1, frame_paths=["vid123/seg2/frame1.jpg"],
            timestamps=[30.0], sequence_numbers=[1], extractor_id="extractor-1",
            bucket_name="frames", timestamp=datetime(2025, 4, 3, 10, 1, 0)
        )
        # Redis XRANGE returns (msg_id, {data})
        mock_redis.return_value.xrange.return_value = [
            ("msg-1", {"event": fake_event1.model_dump_json()}),
            ("msg-2", {"event": fake_event2.model_dump_json()}),
        ]
        mock_producer = MagicMock(spec=StreamProducer)
        mock_producer_cls.return_value = mock_producer
        
        service = ReplayService()
        count = service.replay("vid123")
        
        assert count == 2
        assert mock_producer.publish.call_count == 2
        # Verify events have correct video_id
        published_events = [call[0][1] for call in mock_producer.publish.call_args_list]
        assert all(isinstance(e, FrameReadyEvent) for e in published_events)
        assert all(e.video_id == "vid123" for e in published_events)


def test_replay_service_filters_other_videos():
    """Replay should only republish events matching the given video_id."""
    with patch('shared.streaming.replay.create_redis_client') as mock_redis, \
         patch('shared.streaming.replay.StreamProducer') as mock_producer_cls:
        fake_event1 = FrameReadyEvent(
            event_type="frame.ready", video_id="vid123",
            segment_id=0, frame_paths=["vid123/seg1/frame1.jpg"],
            timestamps=[0.0], sequence_numbers=[0], extractor_id="extractor-1",
            bucket_name="frames", timestamp=datetime(2025, 4, 3, 10, 0, 0)
        )
        fake_event2 = FrameReadyEvent(
            event_type="frame.ready", video_id="vid456",
            segment_id=0, frame_paths=["vid456/seg1/frame1.jpg"],
            timestamps=[0.0], sequence_numbers=[0], extractor_id="extractor-1",
            bucket_name="frames", timestamp=datetime(2025, 4, 3, 10, 1, 0)
        )
        mock_redis.return_value.xrange.return_value = [
            ("msg-1", {"event": fake_event1.model_dump_json()}),
            ("msg-2", {"event": fake_event2.model_dump_json()}),
        ]
        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer
        
        service = ReplayService()
        count = service.replay("vid123")
        
        assert count == 1
        assert mock_producer.publish.call_count == 1
        # Check that only vid123 event was published
        published_event = mock_producer.publish.call_args[0][1]
        assert published_event.video_id == "vid123"


def test_replay_service_handles_invalid_events():
    """Replay should skip invalid events and continue."""
    with patch('shared.streaming.replay.create_redis_client') as mock_redis, \
         patch('shared.streaming.replay.StreamProducer') as mock_producer_cls:
        # One valid, one invalid (corrupted JSON)
        valid_event = FrameReadyEvent(
            event_type="frame.ready", video_id="vid123",
            segment_id=0, frame_paths=["vid123/seg1/frame1.jpg"],
            timestamps=[0.0], sequence_numbers=[0], extractor_id="extractor-1",
            bucket_name="frames", timestamp=datetime(2025, 4, 3, 10, 0, 0)
        )
        mock_redis.return_value.xrange.return_value = [
            ("msg-1", {"event": valid_event.model_dump_json()}),
            ("msg-2", {"event": "invalid json"}),
        ]
        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer
        
        service = ReplayService()
        count = service.replay("vid123")
        
        assert count == 1  # Only valid event counted
        assert mock_producer.publish.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])