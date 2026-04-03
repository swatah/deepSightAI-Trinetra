"""
T2.2.3: Implement Redis Streams consumer with consumer groups

Tests for StreamConsumer that reads events from Redis Streams with consumer group support.
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
from datetime import datetime
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.streaming.consumer import StreamConsumer, Message
from shared.streaming.schema import FrameReadyEvent


class TestMessage:
    """Test Message class."""

    def test_message_creation(self):
        """Message can be created with stream, msg_id, and data."""
        msg = Message(stream="frames:video1", msg_id="123-0", data={"event": '{"type": "frame.ready"}'})
        assert msg.stream == "frames:video1"
        assert msg.id == "123-0"
        assert msg.data == {"event": '{"type": "frame.ready"}'}


class TestStreamConsumerInit:
    """Test StreamConsumer initialization."""

    def test_init_with_given_group_and_consumer(self):
        """Consumer can be initialized with explicit group and consumer_id."""
        mock_client = MagicMock()
        consumer = StreamConsumer(group_name="embedder-group", consumer_id="embedder-1", redis_client=mock_client)
        assert consumer.group_name == "embedder-group"
        assert consumer.consumer_id == "embedder-1"
        assert consumer.client is mock_client

    def test_init_generates_consumer_id_if_not_provided(self):
        """If consumer_id not provided, generates unique ID."""
        mock_client = MagicMock()
        consumer = StreamConsumer(group_name="group1")
        assert consumer.group_name == "group1"
        assert consumer.consumer_id.startswith("consumer-")
        assert len(consumer.consumer_id) > 10  # should have some randomness

    def test_init_creates_redis_client_if_none_provided(self):
        """If no redis_client provided, creates one via create_redis_client."""
        with patch('shared.streaming.consumer.create_redis_client') as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client
            consumer = StreamConsumer(group_name="test")
            assert consumer.client is mock_client
            mock_create.assert_called_once()


class TestStreamConsumerEnsureGroup:
    """Test ensure_group method."""

    def test_creates_consumer_group_if_not_exists(self):
        """ensure_group should call xgroup_create with mkstream=True and id='$'."""
        mock_client = MagicMock()
        consumer = StreamConsumer(group_name="mygroup", redis_client=mock_client)

        consumer.ensure_group("mystream")

        mock_client.xgroup_create.assert_called_once_with(
            stream="mystream",
            groupname="mygroup",
            id='$',
            mkstream=True
        )

    def test_handles_busygroup_error_gracefully(self):
        """If group already exists (BUSYGROUP error), ensure_group should not raise."""
        mock_client = MagicMock()
        # Simulate Redis BUSYGROUP error
        error = Exception("BUSYGROUP group already exists")
        error.args = ("BUSYGROUP group already exists",)  # Simulate ResponseError
        mock_client.xgroup_create.side_effect = error

        consumer = StreamConsumer(group_name="existing", redis_client=mock_client)
        # Should not raise
        consumer.ensure_group("somestream")

    def test_reraises_other_exceptions(self):
        """Non-BUSYGROUP exceptions should propagate."""
        mock_client = MagicMock()
        mock_client.xgroup_create.side_effect = Exception("Some other error")

        consumer = StreamConsumer(group_name="g", redis_client=mock_client)

        with pytest.raises(Exception, match="Some other error"):
            consumer.ensure_group("stream")


class TestStreamConsumerRead:
    """Test read method."""

    def test_read_calls_xreadgroup_with_correct_params(self):
        """read should call xreadgroup with group, consumer, stream='>', count, block."""
        mock_client = MagicMock()
        # Mock xreadgroup to return empty result
        mock_client.xreadgroup.return_value = []

        consumer = StreamConsumer(group_name="group1", consumer_id="consumer1", redis_client=mock_client)
        messages = consumer.read("mystream", count=5, block_ms=1000)

        mock_client.xreadgroup.assert_called_once_with(
            groupname="group1",
            consumername="consumer1",
            streams={"mystream": '>'},
            count=5,
            block=1000
        )
        assert messages == []

    def test_read_parses_messages_into_message_objects(self):
        """read should return list of Message objects with stream, id, and data."""
        mock_client = MagicMock()
        # Simulate Redis return format: [(stream, [(msg_id, {field: value}), ...])]
        mock_client.xreadgroup.return_value = [
            ("frames:video1", [
                ("1656789123-0", {"event": '{"type": "frame.ready"}', "other": "value"}),
                ("1656789124-0", {"event": '{"type": "ingest.started"}'})
            ])
        ]

        consumer = StreamConsumer(group_name="g", consumer_id="c", redis_client=mock_client)
        messages = consumer.read("frames:video1")

        assert len(messages) == 2
        assert messages[0].stream == "frames:video1"
        assert messages[0].id == "1656789123-0"
        assert messages[0].data == {"event": '{"type": "frame.ready"}', "other": "value"}
        assert messages[1].id == "1656789124-0"

    def test_read_empty_result_returns_empty_list(self):
        """If xreadgroup returns None or empty, read should return empty list."""
        mock_client = MagicMock()
        mock_client.xreadgroup.return_value = None  # or []

        consumer = StreamConsumer(group_name="g", consumer_id="c", redis_client=mock_client)

        assert consumer.read("stream1") == []

        mock_client.xreadgroup.return_value = []
        assert consumer.read("stream2") == []

    def test_read_handles_multiple_streams(self):
        """read should work even if multiple streams are returned (though we only query one)."""
        mock_client = MagicMock()
        mock_client.xreadgroup.return_value = [
            ("stream1", [("id1", {"data": "1"})]),
            ("stream2", [("id2", {"data": "2"})])
        ]

        consumer = StreamConsumer(group_name="g", consumer_id="c", redis_client=mock_client)
        messages = consumer.read("stream1")

        # Should return all messages from all streams in the result
        assert len(messages) == 2
        assert set(m.stream for m in messages) == {"stream1", "stream2"}

    def test_read_block_zero_for_non_blocking(self):
        """When block_ms=0, should pass block=0 (non-blocking)."""
        mock_client = MagicMock()
        mock_client.xreadgroup.return_value = []

        consumer = StreamConsumer(group_name="g", consumer_id="c", redis_client=mock_client)
        consumer.read("stream", block_ms=0)

        call_kwargs = mock_client.xreadgroup.call_args[1]
        assert call_kwargs['block'] == 0

    def test_read_block_none(self):
        """When block_ms=None, should pass block=None (non-blocking immediate return)."""
        mock_client = MagicMock()
        mock_client.xreadgroup.return_value = []

        consumer = StreamConsumer(group_name="g", consumer_id="c", redis_client=mock_client)
        consumer.read("stream", block_ms=None)

        # Check that block=None was passed
        call_kwargs = mock_client.xreadgroup.call_args[1]
        assert call_kwargs['block'] is None

    def test_read_calls_ensure_group_before_reading(self):
        """read should call ensure_group first to ensure group exists."""
        mock_client = MagicMock()
        mock_client.xreadgroup.return_value = []

        consumer = StreamConsumer(group_name="g", consumer_id="c", redis_client=mock_client)

        with patch.object(consumer, 'ensure_group', wraps=consumer.ensure_group) as mock_ensure:
            consumer.read("mystream")
            mock_ensure.assert_called_once_with("mystream")


class TestStreamConsumerAck:
    """Test ack method."""

    def test_ack_calls_xack_with_correct_params(self):
        """ack should call xack(stream, group, message_id)."""
        mock_client = MagicMock()
        consumer = StreamConsumer(group_name="mygroup", consumer_id="c", redis_client=mock_client)

        consumer.ack("mystream", "msg-123")

        mock_client.xack.assert_called_once_with("mystream", "mygroup", "msg-123")

    def test_ack_multiple_message_ids(self):
        """ack can acknowledge multiple message IDs."""
        mock_client = MagicMock()
        consumer = StreamConsumer(group_name="g", redis_client=mock_client)

        consumer.ack("stream", "id1", "id2", "id3")

        # xack can take multiple message IDs as varargs
        mock_client.xack.assert_called_once_with("stream", "g", "id1", "id2", "id3")


class TestStreamConsumerPending:
    """Test pending method."""

    def test_pending_without_consumer_calls_xpending(self):
        """pending(stream) without consumer should call xpending with just stream and group."""
        mock_client = MagicMock()
        mock_client.xpending.return_value = {"total": 5, "min": 0, "max": 10}
        consumer = StreamConsumer(group_name="g", redis_client=mock_client)

        result = consumer.pending("mystream")

        mock_client.xpending.assert_called_once_with("mystream", "g")
        assert result == {"total": 5, "min": 0, "max": 10}

    def test_pending_with_consumer_filters_by_consumer(self):
        """pending(stream, consumer='specific') should pass consumer parameter."""
        mock_client = MagicMock()
        mock_client.xpending.return_value = {"consumer": "c1", "messages": []}
        consumer = StreamConsumer(group_name="g", redis_client=mock_client)

        result = consumer.pending("mystream", consumer="c1")

        mock_client.xpending.assert_called_once_with("mystream", "g", consumer="c1")
        assert result["consumer"] == "c1"


class TestStreamConsumerClaim:
    """Test claim method."""

    def test_claim_calls_xclaim_with_correct_params(self):
        """claim should call xclaim(stream, group, new_consumer, message_id)."""
        mock_client = MagicMock()
        mock_client.xclaim.return_value = [("msg1", {"data": "value"})]
        consumer = StreamConsumer(group_name="g", redis_client=mock_client)

        result = consumer.claim("mystream", "msg-123", "new-consumer-1")

        mock_client.xclaim.assert_called_once_with(
            "mystream", "g", "new-consumer-1", "msg-123"
        )
        assert result == [("msg1", {"data": "value"})]

    def test_claim_returns_claimed_messages(self):
        """claim should return the claimed message data."""
        mock_client = MagicMock()
        mock_client.xclaim.return_value = [
            ("id-1", {"event": '{"type": "frame.ready"}'}),
            ("id-2", {"event": '{"type": "ingest.completed"}'})
        ]
        consumer = StreamConsumer(group_name="g", redis_client=mock_client)

        result = consumer.claim("stream", "msg1", "consumer2")

        assert len(result) == 2
        assert result[0][0] == "id-1"
        assert result[1][0] == "id-2"


class TestStreamConsumerIntegrationWithSchema:
    """Test integration with event schemas - deserializing events from streams."""

    def test_read_frame_ready_event_deserialization(self):
        """Consumer should be able to read and parse FrameReadyEvent from stream."""
        mock_client = MagicMock()
        # Create a realistic FrameReadyEvent JSON
        now = datetime.utcnow()
        event = FrameReadyEvent(
            video_id="video-123",
            segment_id=0,
            frame_paths=["frames/vid1/f1.jpg", "frames/vid1/f2.jpg"],
            timestamps=[0.0, 1.0],
            sequence_numbers=[0, 1],
            extractor_id="extractor-1",
            bucket_name="frames",
            timestamp=now
        )
        payload = {"event": event.model_dump_json()}

        mock_client.xreadgroup.return_value = [
            ("frames:video-123", [("1656789123-0", payload)])
        ]

        consumer = StreamConsumer(group_name="embedder-group", consumer_id="embedder-1", redis_client=mock_client)
        messages = consumer.read("frames:video-123")

        assert len(messages) == 1
        msg = messages[0]
        # Parse the event JSON
        import json
        event_data = json.loads(msg.data["event"])
        assert event_data["video_id"] == "video-123"
        assert event_data["event_type"] == "frame.ready"
        assert len(event_data["frame_paths"]) == 2

    def test_multiple_consumers_use_different_consumer_ids(self):
        """Multiple consumers in same group should have unique consumer IDs."""
        mock_client = MagicMock()
        mock_client.xreadgroup.return_value = []

        consumer1 = StreamConsumer(group_name="embedder-group")
        consumer2 = StreamConsumer(group_name="embedder-group")

        assert consumer1.consumer_id != consumer2.consumer_id
        assert consumer1.group_name == consumer2.group_name == "embedder-group"
