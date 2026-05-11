"""
Test that Embedder service consumes events from Redis Stream (T2.2.8).
This test will FAIL until embedder.py is refactored to use event-driven architecture.
"""
import pytest
import inspect  # Added missing import
from unittest.mock import patch, MagicMock, ANY
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from shared.streaming.consumer import StreamConsumer
from shared.streaming.schema import FrameReadyEvent


def test_embedder_uses_event_consumer():
    """
    Test that embedder imports and uses StreamConsumer to process events.
    This is a RED test - it should FAIL until T2.2.8 is implemented.
    """
    # Try to import embedder module
    try:
        import Embedder.embedder as embedder_module
    except ImportError as e:
        pytest.fail(f"Embedder module not importable: {e}")
    
    # Check if embedder has a StreamConsumer instance or usage
    # Since embedder.py currently uses polling, this test will fail
    
    # Read the source to see if it uses StreamConsumer
    source = inspect.getsource(embedder_module)
    
    # Assertions that should FAIL for current polling implementation:
    # 1. Should import StreamConsumer
    assert "from shared.streaming.consumer import StreamConsumer" in source, \
        "Embedder must import StreamConsumer"
    
    # 2. Should create a StreamConsumer instance
    assert "StreamConsumer(" in source, \
        "Embedder must instantiate StreamConsumer"
    
    # 3. Should call consumer.read() in a loop
    assert ".read(" in source, \
        "Embedder must call consumer.read() to consume events"
    
    # 4. Should NOT use old polling functions (list_video_prefixes, list_objects) in main loop
    # Note: these may still exist but shouldn't be in the main processing loop
    # For now, simple check: the process_events function should use consumer, not polling
    assert "list_video_prefixes" not in source.split("def process_events")[1] if "def process_events" in source else True, \
        "Event-driven process_events should not call list_video_prefixes"


def test_embedder_has_process_events_function():
    """Embedder should have process_events() function that uses consumer."""
    try:
        import Embedder.embedder as embedder_module
    except ImportError as e:
        pytest.fail(f"Embedder module not importable: {e}")
    
    assert hasattr(embedder_module, 'process_events'), \
        "Embedder must have process_events() function (event-driven loop)"
    # Should NOT have old process_frames polling function as main entry
    # Or if it exists, it should be deprecated/not used
    source = inspect.getsource(embedder_module)
    # Check that main block calls process_events, not process_frames
    assert "process_events()" in source, \
        "Main block should call process_events()"


def test_embedder_acknowledges_events():
    """Embedder should acknowledge events after successful processing."""
    import Embedder.embedder as embedder_module
    source = inspect.getsource(embedder_module)
    
    assert "consumer.ack(" in source, \
        "Embedder must acknowledge events after processing"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])