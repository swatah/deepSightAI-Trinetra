"""
T2.1.3: License Plate Recognition plugin (law_enf)

Tests LPR plugin detects plates with 90%+ accuracy on test set.
For TDD, we use synthetic frames where plate number is encoded in the
top-left pixel region as ASCII values to avoid needing a real OCR model.
"""

import pytest
import numpy as np
from pathlib import Path
import sys

from Embedder.models.plugins.base import DetectionPlugin


# We'll import the actual plugin after it's created
@pytest.fixture
def lpr_plugin_class():
    from Embedder.models.plugins.law_enforcement.lpr import LPRPlugin
    return LPRPlugin


class TestLPRPlugin:
    """Test LPR plugin functionality and accuracy."""

    def create_frame_with_plate(self, plate_text: str, frame_size=(640, 480, 3)):
        """
        Helper to create a sample license plate image for testing.
        Uses visual character rendering instead of ASCII pixel encoding (VP-18, TEST-81).
        """
        from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_lpr import dsai_create_sample_plate_image
        return dsai_create_sample_plate_image(plate_text)

    def test_plugin_interface(self, lpr_plugin_class):
        """LPR plugin must inherit DetectionPlugin and define attributes."""
        assert issubclass(lpr_plugin_class, DetectionPlugin)
        assert lpr_plugin_class.name == "lpr"
        assert lpr_plugin_class.version == "1.0.0"
        assert "law_enf" in lpr_plugin_class.supported_sectors

    def test_detect_returns_plate_detection(self, lpr_plugin_class):
        """Given a frame with encoded plate, detect should return that plate."""
        plate = "ABC123"
        frame = self.create_frame_with_plate(plate)
        plugin = lpr_plugin_class()
        detections = plugin.detect(frame)

        assert isinstance(detections, list)
        assert len(detections) >= 1
        # Find plate detection
        plate_det = next((d for d in detections if d.get("label") == "plate"), None)
        assert plate_det is not None
        assert plate_det["plate_number"] == plate
        assert plate_det["confidence"] >= 0.9

    def test_accuracy_on_multiple_plates(self, lpr_plugin_class):
        """Test detection on multiple frames with different plates."""
        plates = ["XYZ789", "TEST01", "LMN456"]
        plugin = lpr_plugin_class()
        correct = 0

        for plate in plates:
            frame = self.create_frame_with_plate(plate)
            detections = plugin.detect(frame)
            plate_det = next((d for d in detections if d.get("label") == "plate"), None)
            if plate_det and plate_det.get("plate_number") == plate and plate_det.get("confidence", 0) >= 0.9:
                correct += 1

        accuracy = correct / len(plates)
        assert accuracy >= 0.9, f"Accuracy {accuracy:.2f} < 0.9"

    def test_plugin_config_used(self, lpr_plugin_class):
        """Plugin should accept config like confidence threshold."""
        config = {"confidence_threshold": 0.85}
        plugin = lpr_plugin_class(config)
        assert plugin.config["confidence_threshold"] == 0.85
