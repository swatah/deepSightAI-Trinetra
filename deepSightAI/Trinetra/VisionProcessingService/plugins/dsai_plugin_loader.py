"""
PluginLoader for Vision Processing Service (VP-13, VP-14, VP-24, VP-25).

Discovers, filters, and loads detection plugins based on:
- Global configuration
- Tenant sector compatibility (VP-24)
- Per-tenant and per-camera enable/disable overrides (VP-25)
"""

import os
import inspect
import importlib
from pathlib import Path
from typing import Dict, List, Type, Optional, Any

from deepSightAI.Trinetra.Shared.LoggingSetup import dsai_get_logger
from deepSightAI.Trinetra.Shared.Errors import ConfigurationError
from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_base import DetectionPlugin

logger = dsai_get_logger("deepSightAI.Trinetra.VisionProcessingService.PluginLoader")


class PluginLoader:
    """
    Dynamically discovers and instantiates detection plugins.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.dsai_config = self.config

    def discover_plugins(self) -> Dict[str, Type[DetectionPlugin]]:
        """
        Discover all available DetectionPlugin subclasses in the plugins directories.
        """
        discovered: Dict[str, Type[DetectionPlugin]] = {}

        # Search both VPS plugins directory and Embedder plugins directory
        search_dirs = [
            Path(__file__).parent,
            Path(__file__).parent.parent.parent / "Embedder" / "models" / "plugins"
        ]

        for pkg_dir in search_dirs:
            if not pkg_dir.exists():
                continue
            for file_path in pkg_dir.rglob("*.py"):
                if file_path.name.startswith("__") or file_path.name in ("base.py", "dsai_base.py", "plugin_loader.py", "dsai_plugin_loader.py"):
                    continue

                # Determine relative module
                if "Embedder" in file_path.parts:
                    rel = file_path.relative_to(pkg_dir)
                    mod_name = f"Embedder.models.plugins.{'.'.join(rel.with_suffix('').parts)}"
                else:
                    rel = file_path.relative_to(pkg_dir)
                    mod_name = f"deepSightAI.Trinetra.VisionProcessingService.plugins.{'.'.join(rel.with_suffix('').parts)}"

                try:
                    mod = importlib.import_module(mod_name)
                except Exception as e:
                    logger.debug(f"Could not import {mod_name}: {e}")
                    continue

                for name, obj in inspect.getmembers(mod, inspect.isclass):
                    if issubclass(obj, DetectionPlugin) and obj is not DetectionPlugin:
                        p_name = getattr(obj, "name", name.lower())
                        discovered[p_name] = obj

        return discovered

    def is_plugin_enabled(
        self,
        plugin_name: str,
        tenant_id: str = "default",
        camera_id: Optional[str] = None,
        tenant_sector: Optional[str] = None
    ) -> bool:
        """
        Check if a plugin is enabled, respecting sector, global, per-tenant, and per-camera overrides (VP-24, VP-25).
        """
        plugins_cfg = self.config.get("plugins", {})
        plugin_cfg = plugins_cfg.get(plugin_name, {})

        # 1. Global enable check
        if not plugin_cfg.get("enabled", True):
            return False

        # 2. Sector compatibility check
        if tenant_sector:
            supported = plugin_cfg.get("sectors", [])
            if supported and tenant_sector not in supported:
                return False

        # 3. Tenant override check
        tenant_overrides = self.config.get("tenants", {}).get(tenant_id, {})
        if plugin_name in tenant_overrides.get("disabled_plugins", []):
            return False
        if plugin_name in tenant_overrides:
            val = tenant_overrides[plugin_name]
            if isinstance(val, bool) and not val:
                return False

        # 4. Camera override check
        if camera_id:
            cam_overrides = (
                tenant_overrides.get("camera_overrides", {}).get(camera_id, {})
                or tenant_overrides.get("cameras", {}).get(camera_id, {})
            )
            if plugin_name in cam_overrides.get("disabled_plugins", []):
                return False
            if plugin_name in cam_overrides:
                cam_val = cam_overrides[plugin_name]
                if isinstance(cam_val, bool) and not cam_val:
                    return False

        return True

    def load_plugins(
        self,
        tenant_sector: Optional[str] = None,
        tenant_id: str = "default",
        camera_id: Optional[str] = None,
        **kwargs
    ) -> List[DetectionPlugin]:
        """
        Load instantiated detection plugins compatible with sector, tenant, and camera (VP-24, VP-25).
        """
        if not tenant_sector:
            raise ValueError("tenant_sector is required")

        available = self.discover_plugins()
        plugins_cfg = self.config.get("plugins", {})
        instantiated: List[DetectionPlugin] = []

        for name, cls in available.items():
            # Check enabled with overrides
            if not self.is_plugin_enabled(name, tenant_id, camera_id):
                continue

            # Sector compatibility check (VP-24)
            supported = getattr(cls, "supported_sectors", [])
            if tenant_sector not in supported and "*" not in supported:
                continue

            # Instantiate with plugin configuration
            cfg = plugins_cfg.get(name, {}).get("config", {})
            try:
                instance = cls(cfg)
                instantiated.append(instance)
            except Exception as e:
                logger.error(f"Failed to instantiate plugin {name}: {e}")
                raise ConfigurationError(f"Plugin {name} initialization error: {e}")

        return instantiated

    # Aliases
    dsai_discover_plugins = discover_plugins
    dsai_is_plugin_enabled = is_plugin_enabled
    dsai_load_plugins = load_plugins
