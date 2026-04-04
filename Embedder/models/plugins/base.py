"""
T2.1.1: DetectionPlugin base class

Abstract base class for all detection plugins in deepSightAI Trinetra.
"""

from abc import ABC, abstractmethod
from typing import Any, List, Dict


class DetectionPlugin(ABC):
    """
    Abstract base class for detection plugins.

    Plugins must implement the `detect(frame)` method and define
    class attributes: name, version, supported_sectors.

    Attributes:
        name: Plugin name (e.g., "lpr", "weapon_detection")
        version: Plugin version string (e.g., "1.0.0")
        supported_sectors: List of tenant sectors this plugin supports
                          (e.g., ["law_enf", "commercial"])
        config: Plugin configuration dictionary (passed at init)
    """

    name: str = "base_plugin"
    version: str = "0.0.0"
    supported_sectors: List[str] = []
    config: Dict[str, Any] = {}

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize plugin with configuration.

        Args:
            config: Optional configuration dictionary. Defaults to empty dict.
        """
        self.config = config or {}

    @abstractmethod
    def detect(self, frame: Any) -> List[Dict[str, Any]]:
        """
        Run detection on a frame.

        Args:
            frame: The frame data (format depends on plugin implementation,
                  typically a numpy array or image).

        Returns:
            List of detection dictionaries. Each dict should contain at least:
            - label: str, detected object/class label
            - confidence: float, confidence score (0-1)
            - bbox: optional, [x, y, w, h] bounding box
            - Additional plugin-specific fields.

        Example:
            [{"label": "plate", "confidence": 0.95, "bbox": [10, 20, 100, 30]}]
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, version={self.version})"
