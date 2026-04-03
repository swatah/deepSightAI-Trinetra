"""
T2.1.10: Performance benchmarking suite

Tests that each plugin's overhead is less than 10% of embedding time.
Uses mock CLIP model to avoid heavy dependencies.
"""

import pytest
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from Embedder.models.plugin_loader import PluginLoader
from Embedder.models.plugins.base import DetectionPlugin


# Performance thresholds
PLUGIN_OVERHEAD_THRESHOLD = 0.10   # Plugin time must be < 10% of embedding time


def get_plugins_to_benchmark():
    """Return list of plugin classes to benchmark."""
    loader = PluginLoader({"plugins": {}})
    all_plugins = loader.discover_plugins()
    return list(all_plugins.items())


@pytest.fixture(scope="session")
def mock_clip_model():
    """Mock CLIP model that simulates embedding time (~50ms)."""
    class MockModel:
        def encode_image(self, image_tensor):
            time.sleep(0.05)  # Simulate 50ms embedding
            return MagicMock()

    class MockPreprocess:
        def __call__(self, image):
            return MagicMock()

    return {
        "model": MockModel(),
        "preprocess": MockPreprocess(),
        "onnx_session": None,
        "device": "cpu"
    }


def create_frame_for_plugin(plugin_name):
    """Create a synthetic frame with a large detection region for the given plugin."""
    import numpy as np
    # Use a moderate frame size to keep tests fast (240p)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    if plugin_name == "face_blur":
        # Large blue rectangle in center
        y, x = 70, 100  # top-left
        h, w = 100, 120  # height, width
        frame[y:y+h, x:x+w] = [255, 0, 0]  # blue in BGR
    elif plugin_name == "weapon_detection":
        # Red rectangle in top-right corner (as in weapon test)
        frame_h, frame_w = frame.shape[:2]
        frame[0:25, frame_w-50:frame_w] = [255, 0, 0]  # red
    elif plugin_name == "lpr":
        # License plate: white rectangle
        y, x = 150, 75
        h, w = 40, 150
        frame[y:y+h, x:x+w] = [255, 255, 255]
    elif plugin_name == "heatmap":
        # Activity red patch
        y, x = 50, 50
        h, w = 75, 100
        frame[y:y+h, x:x+w] = [255, 0, 0]
    elif plugin_name == "demographics":
        # No specific pattern needed; blank is fine
        pass
    elif plugin_name == "ppe_detection":
        # Hard hat (yellow) and safety vest (orange)
        # Hard hat: yellow (0,255,255) - top
        frame[25:60, 80:160] = [0, 255, 255]
        # Safety vest: orange (0,165,255) - bottom
        frame[100:160, 60:140] = [0, 165, 255]
    else:
        pass
    return frame


@pytest.mark.perf
@pytest.mark.parametrize("plugin_name,plugin_class", get_plugins_to_benchmark())
def test_plugin_overhead_less_than_10_percent(mock_clip_model, plugin_name, plugin_class):
    """
    Benchmark: Plugin detection should be < 10% of CLIP embedding time.

    Uses mock CLIP model and realistic synthetic frames with large detections.
    """
    # Create a frame tailored to this plugin
    synthetic_frame = create_frame_for_plugin(plugin_name)

    # Create plugin instance with empty config
    plugin = plugin_class({})

    # Warm-up
    for _ in range(2):
        _ = plugin.detect(synthetic_frame)

    # Measure plugin detection time (20 iterations)
    num_iterations = 20
    times_plugin = []
    for _ in range(num_iterations):
        start = time.perf_counter()
        _ = plugin.detect(synthetic_frame)
        times_plugin.append(time.perf_counter() - start)

    avg_plugin_time = sum(times_plugin) / len(times_plugin)

    # Measure embedding time using mock (simulates typical CLIP inference)
    times_embed = []
    for _ in range(5):
        start = time.perf_counter()
        _ = mock_clip_model["model"].encode_image(None)
        times_embed.append(time.perf_counter() - start)

    avg_embedding_time = sum(times_embed) / len(times_embed)

    # Calculate overhead ratio
    overhead_ratio = avg_plugin_time / avg_embedding_time if avg_embedding_time > 0 else float('inf')

    # Log results
    print(f"\n[{plugin_name}]")
    print(f"  Avg embedding time (mock): {avg_embedding_time*1000:.2f} ms")
    print(f"  Avg plugin time: {avg_plugin_time*1000:.2f} ms")
    print(f"  Overhead ratio: {overhead_ratio:.2%}")

    # Assert overhead is less than 10%
    assert overhead_ratio < PLUGIN_OVERHEAD_THRESHOLD, \
        f"Plugin {plugin_name} overhead {overhead_ratio:.2%} exceeds 10% threshold"
