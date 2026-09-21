"""
Relocated PluginLoader re-export (VP-13).
Canonical definition is now in deepSightAI.Trinetra.VisionProcessingService.plugins.
"""

from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_plugin_loader import PluginLoader
from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_base import DetectionPlugin

__all__ = ["PluginLoader", "DetectionPlugin"]
