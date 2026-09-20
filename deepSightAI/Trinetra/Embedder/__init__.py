"""
Embedder package - CLIP image & text embedding and Redis Streams consumer.
"""

from .event_consumer import EmbedderConsumer

__all__ = [
    "EmbedderConsumer",
]
