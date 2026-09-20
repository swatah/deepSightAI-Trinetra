"""
Redis Streams producer for event publication.

Provides StreamProducer class to publish Pydantic events to Redis Streams with
configurable max length for backpressure.
"""

from .redis_client import create_redis_client


class StreamProducer:
    """
    Publishes events to Redis Streams.

    Attributes:
        client: Redis client instance (created if not provided)
    """

    def __init__(self, redis_client=None):
        """
        Initialize producer.

        Args:
            redis_client: Optional pre-configured Redis client. If None,
                         creates one via create_redis_client().
        """
        self.client = redis_client or create_redis_client()

    def publish(self, stream_name: str, event, maxlen: int = 10000):
        """
        Publish an event to a Redis Stream.

        The event is serialized to JSON and stored under the 'event' field.

        Args:
            stream_name: Name of the Redis Stream (e.g., "frames:video-123")
            event: Pydantic model instance representing the event.
            maxlen: Maximum length of the stream (approximate trimming).
                    Default 10,000 entries to bound memory usage.

        Returns:
            The Redis entry ID (e.g., "1656789123456-0").

        Raises:
            TypeError: If event does not support model_dump_json().
            RedisError: If publishing fails.
        """
        if not hasattr(event, 'model_dump_json'):
            raise TypeError("Event must be a Pydantic model with model_dump_json() method")

        payload = event.model_dump_json()
        # Publish to stream with maxlen to enforce retention policy
        # Using approximate=True for O(1) trimming (roughly maxlen)
        return self.client.xadd(stream_name, {"event": payload}, maxlen=maxlen)
