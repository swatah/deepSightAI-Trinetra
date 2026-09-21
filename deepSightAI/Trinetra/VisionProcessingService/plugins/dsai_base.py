"""
DetectionPlugin Base Class (VP-13).

Abstract base class for all object detection and attribute extraction plugins.
"""

from abc import ABC, abstractmethod
from typing import Any, List, Dict, Optional


class DetectionPlugin(ABC):
    """
    Abstract base class for detection plugins in Vision Processing Service.

    Attributes:
        name: Plugin name (e.g. 'pp_human', 'pp_vehicle')
        version: Plugin semantic version
        supported_sectors: List of tenant sectors this plugin supports
        config: Plugin-specific configuration dictionary
    """

    name: str = "base_plugin"
    version: str = "1.0.0"
    supported_sectors: List[str] = ["law_enf", "commercial", "logistics", "default"]
    config: Dict[str, Any] = {}

    def __init__(self, dsai_config: Optional[Dict[str, Any]] = None):
        self.config = dsai_config or {}
        self.dsai_config = self.config

    @abstractmethod
    def detect(self, frame: Any) -> List[Dict[str, Any]]:
        """
        Run detection on a frame. Must be implemented by all subclasses.
        """
        pass

    def dsai_detect(self, dsai_frame: Any) -> List[Dict[str, Any]]:
        """Alias conforming to dsai_ naming convention."""
        return self.detect(dsai_frame)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, version={self.version})"
