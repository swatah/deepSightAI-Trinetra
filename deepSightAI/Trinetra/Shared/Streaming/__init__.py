"""
Streaming utilities for unified ingestion pipeline under deepSightAI.Trinetra.Shared.Streaming.
"""

from .Consumer import StreamConsumer, Message
from .Producer import StreamProducer
from .Schema import (
    FrameReadyEvent,
    IngestJobStarted,
    IngestJobCompleted,
    EmbedderProcessingStarted,
    EmbedderProcessingCompleted,
    ObjectDetectedEvent,
    WatchlistAlertEvent,
)
from .Replay import ReplayService
from .RedisClient import create_redis_client, test_connection

__all__ = [
    "StreamConsumer",
    "StreamProducer",
    "FrameReadyEvent",
    "IngestJobStarted",
    "IngestJobCompleted",
    "EmbedderProcessingStarted",
    "EmbedderProcessingCompleted",
    "ObjectDetectedEvent",
    "WatchlistAlertEvent",
    "ReplayService",
    "create_redis_client",
    "test_connection",
]

