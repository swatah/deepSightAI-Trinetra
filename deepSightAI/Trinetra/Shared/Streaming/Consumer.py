"""
Redis Streams consumer with consumer group support.

Provides StreamConsumer for reliable message consumption with acknowledgement.
"""

import uuid
import redis
from .RedisClient import create_redis_client


class Message:
    """Represents a single message from a Redis Stream."""
    def __init__(self, stream: str, msg_id: str, data: dict):
        self.stream = stream
        self.id = msg_id
        self.data = data


class StreamConsumer:
    """
    Consumer for Redis Streams using consumer groups.

    Handles consumer group creation (if needed), reading messages, and acknowledgements.

    Attributes:
        group_name: Name of the consumer group
        consumer_id: Unique identifier for this consumer instance
    """
    def __init__(self, group_name: str, consumer_id: str = None, redis_client=None):
        self.group_name = group_name
        self.consumer_id = consumer_id or f"consumer-{uuid.uuid4().hex[:8]}"
        self.client = redis_client or create_redis_client()

    def ensure_group(self, stream_name: str):
        """
        Ensure the consumer group exists for the given stream.
        Creates the group if it does not exist (idempotent).

        Args:
            stream_name: Name of the Redis stream
        """
        try:
            # Create consumer group with last ID '$' (only new messages)
            self.client.xgroup_create(stream=stream_name, groupname=self.group_name, id='$', mkstream=True)
        except TypeError:
            try:
                self.client.xgroup_create(name=stream_name, groupname=self.group_name, id='$', mkstream=True)
            except Exception as e:
                error_msg = str(e).lower()
                if 'busygroup' in error_msg or 'group already exists' in error_msg:
                    return
                raise
        except Exception as e:
            error_msg = str(e).lower()
            if 'busygroup' in error_msg or 'group already exists' in error_msg:
                return
            else:
                raise

    def read(self, stream_name: str, count: int = 10, block_ms: int = 5000):
        """
        Read messages from a stream using the consumer group.

        Args:
            stream_name: Name of the stream to read from
            count: Maximum number of messages to fetch
            block_ms: Milliseconds to block waiting for messages (0 = indefinite, None = non-blocking)

        Returns:
            List of Message objects. Empty list if no messages.
        """
        self.ensure_group(stream_name)

        try:
            result = self.client.xreadgroup(
                groupname=self.group_name,
                consumername=self.consumer_id,
                streams={stream_name: '>'},
                count=count,
                block=block_ms
            )
        except redis.exceptions.TimeoutError:
            return []

        messages = []
        if result:
            for stream, msg_list in result:
                for msg_id, data in msg_list:
                    messages.append(Message(stream=stream, msg_id=msg_id, data=data))
        return messages

    def ack(self, stream_name: str, *message_ids: str):
        """
        Acknowledge successful processing of one or more messages.

        Args:
            stream_name: Stream name
            *message_ids: One or more message identifiers to acknowledge
        """
        if not message_ids:
            return
        self.client.xack(stream_name, self.group_name, *message_ids)

    def pending(self, stream_name: str, consumer=None):
        """
        Get list of pending messages (claimed but not acked) for the consumer group.
        If consumer is specified, filter by that consumer.

        Returns:
            List of pending message IDs and their data.
        """
        if consumer:
            return self.client.xpending(stream_name, self.group_name, consumer=consumer)
        else:
            return self.client.xpending(stream_name, self.group_name)

    def claim(self, stream_name: str, message_id: str, new_consumer_id: str):
        """
        Claim a pending message from another consumer.

        Args:
            stream_name: Stream name
            message_id: Message ID to claim
            new_consumer_id: The consumer that will now handle the message

        Returns:
            List of (message_id, data) tuples for claimed messages
        """
        return self.client.xclaim(stream_name, self.group_name, new_consumer_id, message_id)
