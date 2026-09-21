"""
Redis Streams producer for event publication.

Provides StreamProducer class to publish Pydantic events to Redis Streams with
configurable max length for backpressure.
"""

from .RedisClient import create_redis_client


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

    def publish(self, stream_name: str, event, maxlen: int = 10000, correlation_id: str = None, x_request_id: str = None, **kwargs):
        """
        Publish an event to a Redis Stream.

        Supports Pydantic models or dict payloads and propagates correlation_id (REL-54).
        """
        import json
        effective_req_id = correlation_id or x_request_id or kwargs.get("x_request_id")
        if hasattr(event, 'model_dump_json'):
            payload = event.model_dump_json()
            req_id = effective_req_id or getattr(event, "correlation_id", None)
        elif isinstance(event, dict):
            payload = json.dumps(event)
            req_id = effective_req_id or event.get("correlation_id") or event.get("request_id")
        else:
            raise TypeError("Event must be a Pydantic model with model_dump_json() or a dict")

        entry_data = {"event": payload}
        if req_id:
            entry_data["x_request_id"] = str(req_id)
            entry_data["correlation_id"] = str(req_id)
        return self.client.xadd(stream_name, entry_data, maxlen=maxlen)

