"""
Redis client utilities for streaming ingestion.

Provides a simple interface to create Redis clients configured via environment.
"""

import os
from typing import Optional
import redis


def get_redis_url() -> str:
    """Get Redis connection URL from environment or default."""
    return os.getenv("REDIS_URL", "redis://redis:6379")


def create_redis_client(decode_responses: bool = True, **kwargs) -> redis.Redis:
    """
    Create a Redis client configured for the application.

    Uses REDIS_URL environment variable. Pass additional kwargs to redis.Redis.

    Args:
        decode_responses: Whether to decode response bytes to strings (default True)
        **kwargs: Additional arguments to redis.Redis constructor

    Returns:
        Configured Redis client instance
    """
    url = get_redis_url()
    # Parse URL to extract host/port/password if needed? redis.from_url handles it.
    return redis.Redis.from_url(url, decode_responses=decode_responses, **kwargs)


def test_connection(client: Optional[redis.Redis] = None) -> bool:
    """
    Test connectivity to Redis by pinging.

    Args:
        client: Redis client to test; if None, creates one via create_redis_client()

    Returns:
        True if PING succeeded, False otherwise
    """
    if client is None:
        client = create_redis_client()
    try:
        return client.ping()
    except Exception:
        return False
