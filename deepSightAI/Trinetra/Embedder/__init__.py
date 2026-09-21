"""
Embedder package - CLIP image & text embedding and Redis Streams consumer.
"""

from .embedder import process_events, dsai_process_events

__all__ = [
    "process_events",
    "dsai_process_events",
]
