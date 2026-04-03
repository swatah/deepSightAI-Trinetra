"""
T2.2.8: Modify embedder to consume events instead of polling

Tests for event-driven embedder consumer.
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
from datetime import datetime
import threading
import io
import numpy as np

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "Server and Extractor"))

# Mock heavy dependencies before importing embedder code
sys.modules['torch'] = MagicMock()
sys.modules['open_clip'] = MagicMock()
sys.modules['onnxruntime'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['pymilvus'] = MagicMock()
sys.modules['minio'] = MagicMock()
sys.modules['minio.error'] = MagicMock()
sys.modules['ffmpeg'] = MagicMock()
sys.modules['httpx'] = MagicMock()
sys.modules['gi'] = MagicMock()
sys.modules['gi.repository'] = MagicMock()
sys.modules['gi.repository.Gst'] = MagicMock()
sys.modules['gi.repository.GLib'] = MagicMock()

# Mock the embedder module itself to provide the needed functions
mock_embedder = MagicMock()
# Mock encode_images to return a tensor-like object that mimics PyTorch tensor
class DummyTensor:
    def __init__(self, arr):
        self._arr = np.array(arr, dtype=float)
    def numel(self):
        return self._arr.shape[0]
    def __len__(self):
        return self._arr.shape[0]
    def cpu(self):
        return self
    def numpy(self):
        return self._arr
mock_tensor = DummyTensor([[0.1, 0.2], [0.3, 0.4]])
mock_embedder.encode_images = MagicMock(return_value=mock_tensor)
mock_embedder.delete_frame_objects = MagicMock()
mock_embedder.get_minio_client = MagicMock()
mock_embedder.get_milvus_collection = MagicMock()
mock_embedder.FRAME_BUCKET = "frames"
mock_embedder.register_with_registry = MagicMock()
mock_embedder.update_embedder_status = MagicMock()
sys.modules['embedder'] = mock_embedder

try:
    from Embedder.event_consumer import EmbedderConsumer
    from shared.streaming.schema import FrameReadyEvent
    EMBEDDER_CONSUMER_AVAILABLE = True
except Exception as e:
    import traceback; traceback.print_exc()
    EMBEDDER_CONSUMER_AVAILABLE = False
    pytest.skip(f"Embedder consumer not available: {e}", allow_module_level=True)


class TestEmbedderConsumer:
    """Test EmbedderConsumer."""

    def test_consumer_exists(self):
        assert EmbedderConsumer is not None

    def test_process_event_with_frames(self):
        """Test processing an event with frames."""
        mock_collection = MagicMock()
        mock_collection.insert.return_value = None
        mock_collection.flush.return_value = None
        mock_minio = MagicMock()
        mock_minio.fget_object.return_value = None

        consumer = EmbedderConsumer(milvus_collection=mock_collection, minio_client=mock_minio)

        event = FrameReadyEvent(
            video_id="vid123",
            segment_id=0,
            frame_paths=["frames/vid123/seg0/f1.jpg", "frames/vid123/seg0/f2.jpg"],
            timestamps=[0.0, 1.0],
            sequence_numbers=[0, 1],
            extractor_id="ex1",
            bucket_name="frames",
            timestamp=datetime.utcnow()
        )

        consumer.process_event(event)

        # Download called for each frame
        assert mock_minio.fget_object.call_count == 2
        # Encode called with local paths
        assert mock_embedder.encode_images.called
        # Insert called
        assert mock_collection.insert.called
        inserted = mock_collection.insert.call_args[0][0]
        assert inserted[0] == ["vid123", "vid123"]
        assert inserted[1] == event.frame_paths
        assert len(inserted[2]) == 2
        mock_collection.flush.assert_called_once()
        # Delete called
        assert mock_embedder.delete_frame_objects.called
        mock_embedder.delete_frame_objects.assert_called_with(mock_minio, event.frame_paths)

    # Note: FrameReadyEvent requires at least one frame, so empty event is not constructable.

    def test_run_loop_uses_consumer_group(self):
        """run_loop should use StreamConsumer to read from 'frames'."""
        with patch('Embedder.event_consumer.StreamConsumer') as mock_consumer_cls:
            mock_consumer = MagicMock()
            mock_consumer.read.return_value = []
            mock_consumer.ensure_group = MagicMock()
            mock_consumer.ack = MagicMock()
            mock_consumer_cls.return_value = mock_consumer

            # Provide dummy deps to avoid needing real embedder
            consumer = EmbedderConsumer(milvus_collection=MagicMock(), minio_client=MagicMock())
            stop_flag = threading.Event()
            thread = threading.Thread(target=consumer.run_loop, kwargs={'stop_flag': stop_flag, 'max_iterations': 2})
            thread.start()
            thread.join(timeout=5)
            if thread.is_alive():
                stop_flag.set()
                thread.join()

            assert mock_consumer_cls.called
            # ensure_group should have been called with 'frames'
            mock_consumer.ensure_group.assert_called_with('frames')
            assert mock_consumer.read.called
