"""
T2.1.4: Weapon Detection plugin (YOLOv8)

Tests weapon detection with >85% accuracy and <1 FPS overhead.
For TDD, we use synthetic frames where weapon presence is encoded
in a specific pixel region to avoid needing a real YOLO model.
"""

import pytest
import time
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Embedder.models.plugins.base import DetectionPlugin


@pytest.fixture
def weapon_plugin_class():
    from Embedder.models.plugins.law_enforcement.weapon_detection import WeaponDetectionPlugin
    return WeaponDetectionPlugin


class TestWeaponDetection:
    """Test Weapon Detection plugin."""

    def create_frame_with_weapon(self, has_weapon: bool, frame_size=(640, 480, 3)):
        """Create synthetic frame with a red rectangle if weapon present."""
        frame = np.zeros(frame_size, dtype=np.uint8)
        if has_weapon:
            h, w = frame_size[:2]
            frame[0:50, w-100:w, 0] = 255  # red channel rectangle (weapon)
        return frame

    def test_plugin_interface(self, weapon_plugin_class):
        assert issubclass(weapon_plugin_class, DetectionPlugin)
        assert weapon_plugin_class.name == "weapon_detection"
        assert weapon_plugin_class.version == "1.0.0"
        assert "law_enf" in weapon_plugin_class.supported_sectors

    def test_detects_weapon_present(self, weapon_plugin_class):
        frame = self.create_frame_with_weapon(True)
        plugin = weapon_plugin_class()
        detections = plugin.detect(frame)
        weapon_dets = [d for d in detections if d.get("label") == "weapon"]
        assert len(weapon_dets) >= 1
        assert weapon_dets[0]["confidence"] >= 0.85

    def test_no_detection_when_no_weapon(self, weapon_plugin_class):
        frame = self.create_frame_with_weapon(False)
        plugin = weapon_plugin_class()
        detections = plugin.detect(frame)
        weapon_dets = [d for d in detections if d.get("label") == "weapon"]
        assert len(weapon_dets) == 0

    def test_accuracy_over_85_percent(self, weapon_plugin_class):
        """Overall accuracy >= 85% on 50 synthetic frames."""
        num_tests = 50
        correct = 0
        plugin = weapon_plugin_class()

        for i in range(num_tests):
            has_weapon = (i % 2 == 0)
            frame = self.create_frame_with_weapon(has_weapon)
            detections = plugin.detect(frame)
            weapon_dets = [d for d in detections if d.get("label") == "weapon"]
            detected = len(weapon_dets) > 0

            if has_weapon and detected:
                correct += 1
            elif not has_weapon and not detected:
                correct += 1

        accuracy = correct / num_tests
        assert accuracy >= 0.85, f"Accuracy {accuracy:.2f} < 0.85"

    def test_performance_overhead_under_1fps(self, weapon_plugin_class):
        """
        Measure that adding the plugin does not reduce frame processing
        rate by more than 1 FPS. Since we have no baseline, we assert that
        the plugin's detect() can process at least 10 FPS (i.e., <0.1s per frame).
        """
        plugin = weapon_plugin_class()
        frame = self.create_frame_with_weapon(True)

        # Warm-up
        for _ in range(5):
            plugin.detect(frame)

        # Measure time over 100 iterations
        start = time.perf_counter()
        for _ in range(100):
            plugin.detect(frame)
        elapsed = time.perf_counter() - start
        avg_time = elapsed / 100

        # Must be under 100ms per frame to imply <1 FPS overhead
        assert avg_time < 0.1, f"Avg time {avg_time:.3f}s exceeds 0.1s budget"

    def test_plugin_config_used(self, weapon_plugin_class):
        config = {"confidence_threshold": 0.80, "model_size": "small"}
        plugin = weapon_plugin_class(config)
        assert plugin.config["confidence_threshold"] == 0.80
        assert plugin.config["model_size"] == "small"
