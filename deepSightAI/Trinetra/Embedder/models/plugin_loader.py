"""
T2.1.2: Plugin loader (config-based)

Discovers and loads detection plugins based on tenant sector configuration.
"""

import importlib
import inspect
from pathlib import Path
from typing import Dict, List, Type

from Embedder.models.plugins.base import DetectionPlugin


class PluginLoader:
    """
    Loads and instantiates detection plugins based on configuration.

    The loader reads global configuration to determine which plugins
    are enabled, then filters plugins by the tenant's sector and instantiates
    them with their specific configuration.

    Attributes:
        config: The global configuration dict with a "plugins" key.
    """

    def __init__(self, config: Dict):
        """
        Initialize loader with configuration.

        Expected config structure:
        {
            "plugins": {
                "plugin_name": {
                    "enabled": bool,
                    "config": { ... plugin-specific config ...}
                },
                ...
            }
        }
        """
        self.config = config

    def discover_plugins(self) -> Dict[str, Type[DetectionPlugin]]:
        """
        Discover all available DetectionPlugin subclasses in the plugins package.

        Returns:
            Dictionary mapping plugin names to plugin classes.
        """
        plugins_package = "Embedder.models.plugins"
        package_dir = Path(__file__).parent / "plugins"

        discovered = {}

        # Recursively iterate over all Python files in the plugins package
        for file_path in package_dir.rglob("*.py"):
            # Skip __init__.py and base.py
            if file_path.name == "__init__.py" or file_path.name == "base.py":
                continue

            # Compute module name relative to plugins package
            relative_path = file_path.relative_to(package_dir)
            module_name = ".".join(relative_path.with_suffix("").parts)
            full_module_name = f"{plugins_package}.{module_name}"

            try:
                module = importlib.import_module(full_module_name)
            except ImportError as e:
                # Log warning but continue discovery
                print(f"[PluginLoader] Failed to import {full_module_name}: {e}")
                continue

            # Find classes that are subclasses of DetectionPlugin (but not DetectionPlugin itself)
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, DetectionPlugin) and obj is not DetectionPlugin:
                    # Use plugin's 'name' attribute
                    plugin_name = getattr(obj, "name", name.lower())
                    discovered[plugin_name] = obj

        return discovered

    def load_plugins(self, tenant_sector: str) -> List[DetectionPlugin]:
        """
        Load enabled plugins compatible with the given tenant sector.

        Args:
            tenant_sector: The tenant's sector (e.g., "law_enf", "commercial").

        Returns:
            List of instantiated plugin objects.

        Raises:
            ValueError: If tenant_sector is None or empty.
        """
        if not tenant_sector:
            raise ValueError("tenant_sector is required")

        # Get available plugins
        available_plugins = self.discover_plugins()

        # Get plugin configurations from global config
        plugins_config = self.config.get("plugins", {})

        instantiated = []

        for plugin_name, plugin_class in available_plugins.items():
            # Check if plugin is enabled in config
            plugin_cfg = plugins_config.get(plugin_name, {})
            if not plugin_cfg.get("enabled", False):
                continue

            # Check sector compatibility
            if tenant_sector not in plugin_class.supported_sectors:
                continue

            # Instantiate with plugin-specific config
            instance_config = plugin_cfg.get("config", {})
            try:
                instance = plugin_class(instance_config)
                instantiated.append(instance)
            except Exception as e:
                print(f"[PluginLoader] Failed to instantiate {plugin_name}: {e}")
                continue

        return instantiated
