"""
T2.1.2: Implement plugin loader (config-based)

Tests the PluginLoader that discovers and loads plugins based on configuration.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from Embedder.models.plugin_loader import PluginLoader
from Embedder.models.plugins.base import DetectionPlugin


# Sample test plugins
class MockLPRPlugin(DetectionPlugin):
    name = "lpr"
    version = "1.0.0"
    supported_sectors = ["law_enf"]

    def detect(self, frame):
        return [{"label": "plate", "confidence": 0.9}]


class MockWeaponPlugin(DetectionPlugin):
    name = "weapon_detection"
    version = "2.0.0"
    supported_sectors = ["law_enf", "commercial"]

    def detect(self, frame):
        return [{"label": "weapon", "confidence": 0.85}]


class MockDemographicsPlugin(DetectionPlugin):
    name = "demographics"
    version = "1.5.0"
    supported_sectors = ["commercial"]

    def detect(self, frame):
        return [{"label": "person", "age": 30, "gender": "M"}]


class TestPluginLoader:
    """Test the PluginLoader class."""

    def test_loader_loads_enabled_plugins_for_sector(self):
        """Loader should load only enabled plugins that support the tenant's sector."""
        # Simulate configuration: tenant sector = law_enf, with plugins enabled
        config = {
            "plugins": {
                "lpr": {"enabled": True, "config": {"model_path": "/models/lpr"}},
                "weapon_detection": {"enabled": True, "config": {}},
                "demographics": {"enabled": False, "config": {}}
            }
        }
        loader = PluginLoader(config)
        # Mock available plugins registry
        loader.discover_plugins = lambda: {
            "lpr": MockLPRPlugin,
            "weapon_detection": MockWeaponPlugin,
            "demographics": MockDemographicsPlugin
        }

        plugins = loader.load_plugins(tenant_sector="law_enf")

        assert len(plugins) == 2
        assert any(isinstance(p, MockLPRPlugin) for p in plugins)
        assert any(isinstance(p, MockWeaponPlugin) for p in plugins)
        # Demographics not loaded (disabled or not for this sector)
        assert not any(isinstance(p, MockDemographicsPlugin) for p in plugins)

    def test_loader_filters_by_sector_compatibility(self):
        """Loader should only include plugins that support the tenant's sector."""
        config = {
            "plugins": {
                "lpr": {"enabled": True},
                "weapon_detection": {"enabled": True},
                "demographics": {"enabled": True}
            }
        }
        loader = PluginLoader(config)
        loader.discover_plugins = lambda: {
            "lpr": MockLPRPlugin,
            "weapon_detection": MockWeaponPlugin,
            "demographics": MockDemographicsPlugin
        }

        plugins = loader.load_plugins(tenant_sector="commercial")

        # Only weapon_detection and demographics support commercial
        assert len(plugins) == 2
        for p in plugins:
            assert "commercial" in p.supported_sectors

    def test_loader_passes_plugin_config_to_instance(self):
        """Plugin instances should be initialized with their specific config."""
        config = {
            "plugins": {
                "lpr": {"enabled": True, "config": {"threshold": 0.75, "model": "v3"}}
            }
        }
        loader = PluginLoader(config)
        loader.discover_plugins = lambda: {"lpr": MockLPRPlugin}

        plugins = loader.load_plugins(tenant_sector="law_enf")
        lpr_plugin = next(p for p in plugins if isinstance(p, MockLPRPlugin))

        assert lpr_plugin.config["threshold"] == 0.75
        assert lpr_plugin.config["model"] == "v3"

    def test_loader_returns_empty_if_no_enabled_plugins(self):
        """If no plugins are enabled, return empty list."""
        config = {
            "plugins": {
                "lpr": {"enabled": False},
                "weapon_detection": {"enabled": False}
            }
        }
        loader = PluginLoader(config)
        loader.discover_plugins = lambda: {"lpr": MockLPRPlugin, "weapon_detection": MockWeaponPlugin}

        plugins = loader.load_plugins(tenant_sector="law_enf")
        assert plugins == []

    def test_loader_raises_error_if_invalid_sector(self):
        """If tenant sector is None or empty, loader should raise ValueError."""
        config = {"plugins": {"lpr": {"enabled": True}}}
        loader = PluginLoader(config)
        loader.discover_plugins = lambda: {"lpr": MockLPRPlugin}

        with pytest.raises(ValueError, match="tenant_sector is required"):
            loader.load_plugins(tenant_sector=None)

        with pytest.raises(ValueError):
            loader.load_plugins(tenant_sector="")

    def test_plugin_loader_initialization_with_config(self):
        """PluginLoader should accept and store the global config."""
        config = {"plugins": {"lpr": {"enabled": True}}}
        loader = PluginLoader(config)
        assert loader.config == config
