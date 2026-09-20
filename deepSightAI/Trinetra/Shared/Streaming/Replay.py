"""
ReplayService: reprocess historical events for a video.

Provides functionality to read past events from Redis Stream and republish them
to trigger re-processing (e.g., for error recovery or data correction).
"""

from .RedisClient import create_redis_client
from .Producer import StreamProducer
from .Schema import FrameReadyEvent


class ReplayService:
    """
    Replay past frame events for a given video.
    
    Reads historical events from a Redis Stream and republishes them to the
    same stream, allowing the embedder to re-process them.
    
    Attributes:
        client: Redis client instance
        producer: StreamProducer instance for publishing replayed events
    """
    
    def __init__(self, redis_client=None, producer=None):
        """
        Initialize replay service.
        
        Args:
            redis_client: Optional pre-configured Redis client
            producer: Optional StreamProducer instance
        """
        self.client = redis_client or create_redis_client()
        self.producer = producer or StreamProducer()
    
    def replay(self, video_id: str, stream: str = "events:frame_ready") -> int:
        """
        Read all historical events for video_id and republish them.
        
        Args:
            video_id: Video identifier to replay
            stream: Redis stream name (default "events:frame_ready")
        
        Returns:
            Number of events replayed
        """
        try:
            events = self.client.xrange(stream, "-", "+")
        except TypeError:
            events = self.client.xrange(name=stream, min="-", max="+")
        replayed = 0
        
        for msg_id, data in events:
            try:
                event_json = data.get("event")
                if not event_json:
                    continue
                
                event = FrameReadyEvent.model_validate_json(event_json)
                
                if event.video_id == video_id:
                    self.producer.publish(stream, event)
                    replayed += 1
                    
            except Exception as e:
                print(f"Warning: skipping msg {msg_id}: {e}")
                continue
        
        return replayed
