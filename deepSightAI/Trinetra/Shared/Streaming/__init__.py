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
    DeadLetterQueueEvent,
)
from .ResilientConsumer import ResilientStreamConsumer
from .Replay import ReplayService
from .RedisClient import create_redis_client, test_connection

__all__ = [
    "StreamConsumer",
    "StreamProducer",
    "ResilientStreamConsumer",
    "FrameReadyEvent",
    "IngestJobStarted",
    "IngestJobCompleted",
    "EmbedderProcessingStarted",
    "EmbedderProcessingCompleted",
    "ObjectDetectedEvent",
    "WatchlistAlertEvent",
    "DeadLetterQueueEvent",
    "ReplayService",
    "create_redis_client",
    "test_connection",
]


