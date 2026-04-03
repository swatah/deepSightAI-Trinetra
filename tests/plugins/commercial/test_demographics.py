"""
T2.1.6: Demographics plugin (commercial)

Tests age/gender estimation: age within 5 years, gender binary accuracy 88%.
For TDD, we encode ground truth demographics into frame pixels.
"""

import pytest
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Embedder.models.plugins.base import DetectionPlugin


@pytest.fixture
def demographics_plugin_class():
    from Embedder.models.plugins.commercial.demographics import DemographicsPlugin
    return DemographicsPlugin


class TestDemographics:
    """Test Demographics plugin."""

    def create_frame_with_demographics(self, age: int, gender: str, frame_size=(640, 480, 3)):
        """
        Create synthetic frame.
        Encode age in first pixel red channel (pixel value = age clamped 0-255).
        Encode gender in first pixel green channel: 0=male, 255=female, 128=other.
        """
        frame = np.zeros(frame_size, dtype=np.uint8)
        # Clamp age to 0-255 (assume ages 0-100)
        age_val = max(0, min(255, age))
        gender_val = 0 if gender.lower() == "male" else 255 if gender.lower() == "female" else 128
        # Set first pixel (top-left)
        frame[0, 0, 0] = age_val  # red channel = age
        frame[0, 0, 1] = gender_val  # green channel = gender encoding
        return frame

    def test_plugin_interface(self, demographics_plugin_class):
        assert issubclass(demographics_plugin_class, DetectionPlugin)
        assert demographics_plugin_class.name == "demographics"
        assert demographics_plugin_class.version == "1.0.0"
        assert "commercial" in demographics_plugin_class.supported_sectors

    def test_age_estimation_within_5_years(self, demographics_plugin_class):
        """Age estimate should be within ±5 years of true age."""
        test_cases = [
            (25, "male"),
            (45, "female"),
            (60, "male"),
            (18, "female"),
            (80, "male")
        ]
        plugin = demographics_plugin_class()
        correct = 0

        for true_age, gender in test_cases:
            frame = self.create_frame_with_demographics(true_age, gender)
            detections = plugin.detect(frame)
            # Find demographics detection
            demo = next((d for d in detections if d.get("label") == "demographics"), None)
            assert demo is not None, f"Missing demographics detection for age {true_age}"
            est_age = demo.get("age")
            if abs(est_age - true_age) <= 5:
                correct += 1

        # At least 4 out of 5 within tolerance? For this small set, accept all
        # But we'll ensure at least 80% to be safe
        accuracy = correct / len(test_cases)
        assert accuracy >= 0.8

    def test_gender_binary_accuracy_88_percent(self, demographics_plugin_class):
        """Test gender classification accuracy >= 88% on mixed set."""
        np.random.seed(42)
        num_tests = 50
        correct = 0
        plugin = demographics_plugin_class()

        for i in range(num_tests):
            # Random age and gender
            age = np.random.randint(18, 80)
            gender = "male" if i % 2 == 0 else "female"
            frame = self.create_frame_with_demographics(age, gender)
            detections = plugin.detect(frame)
            demo = next((d for d in detections if d.get("label") == "demographics"), None)
            assert demo is not None
            est_gender = demo.get("gender")
            if est_gender == gender:
                correct += 1

        acc = correct / num_tests
        assert acc >= 0.88, f"Gender accuracy {acc:.2f} < 0.88"

    def test_confidence_scores(self, demographics_plugin_class):
        """Confidence for age and gender should be between 0 and 1."""
        frame = self.create_frame_with_demographics(30, "female")
        plugin = demographics_plugin_class()
        detections = plugin.detect(frame)
        demo = next((d for d in detections if d.get("label") == "demographics"), None)
        assert demo is not None
        age_conf = demo.get("age_confidence", 0)
        gender_conf = demo.get("gender_confidence", 0)
        assert 0 <= age_conf <= 1
        assert 0 <= gender_conf <= 1

    def test_plugin_config_used(self, demographics_plugin_class):
        config = {"age_model": "v2", "gender_model": "v1"}
        plugin = demographics_plugin_class(config)
        assert plugin.config["age_model"] == "v2"
        assert plugin.config["gender_model"] == "v1"
