"""
T2.1.1: Design plugin interface and discovery

Tests the DetectionPlugin base class contract.
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from Embedder.models.plugins.base import DetectionPlugin


class TestDetectionPlugin:
    """Test the DetectionPlugin interface."""

    def test_plugin_is_abstract_base_class(self):
        """DetectionPlugin should be an abstract base class (cannot instantiate directly)."""
        with pytest.raises(TypeError):
            DetectionPlugin()

    def test_detect_method_signature(self):
        """Plugin classes must implement detect(frame) method."""
        # Create a concrete implementation for testing
        class TestPlugin(DetectionPlugin):
            def detect(self, frame):
                return [{"label": "test", "confidence": 0.9}]

        plugin = TestPlugin()
        result = plugin.detect({"dummy": "frame"})
        assert isinstance(result, list)

    def test_plugin_has_name(self):
        """Plugins should have a name attribute."""
        class TestPlugin(DetectionPlugin):
            name = "test_plugin"
            def detect(self, frame):
                return []

        plugin = TestPlugin()
        assert hasattr(plugin, "name")
        assert plugin.name == "test_plugin"

    def test_plugin_has_version(self):
        """Plugins should have a version attribute."""
        class TestPlugin(DetectionPlugin):
            version = "1.0.0"
            def detect(self, frame):
                return []

        plugin = TestPlugin()
        assert hasattr(plugin, "version")
        assert plugin.version == "1.0.0"

    def test_plugin_has_supported_sectors(self):
        """Plugins should declare which tenant sectors they support."""
        class TestPlugin(DetectionPlugin):
            supported_sectors = ["law_enf", "commercial"]
            def detect(self, frame):
                return []

        plugin = TestPlugin()
        assert hasattr(plugin, "supported_sectors")
        assert "law_enf" in plugin.supported_sectors

    def test_plugin_initialization_with_config(self):
        """Plugins should accept configuration during initialization."""
        class TestPlugin(DetectionPlugin):
            def __init__(self, config):
                super().__init__(config)
                self.config = config

            def detect(self, frame):
                return []

        config = {"threshold": 0.5}
        plugin = TestPlugin(config)
        assert plugin.config == config
