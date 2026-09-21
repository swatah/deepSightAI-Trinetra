"""
Plugins package for Vision Processing Service.
"""

from .dsai_base import DetectionPlugin
from .dsai_plugin_loader import PluginLoader
from .dsai_pp_human import PPHumanPlugin
from .dsai_pp_vehicle import PPVehiclePlugin
from .dsai_vehicle_attributes import PPVehicleAttributePlugin

__all__ = [
    "DetectionPlugin",
    "PluginLoader",
    "PPHumanPlugin",
    "PPVehiclePlugin",
    "PPVehicleAttributePlugin",
]
