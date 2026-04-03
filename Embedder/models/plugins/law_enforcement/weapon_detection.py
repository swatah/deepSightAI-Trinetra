"""
T2.1.4: Weapon Detection plugin (YOLOv8)

For TDD, this is a synthetic detector that looks for a red rectangle
in the top-right corner of the frame. Real implementation would
load a YOLOv8 model and perform inference.
"""

from typing import List, Dict, Any
import numpy as np
from Embedder.models.plugins.base import DetectionPlugin


class WeaponDetectionPlugin(DetectionPlugin):
    """
    Weapon detection plugin for law enforcement using YOLOv8.

    Attributes:
        name: "weapon_detection"
        version: "1.0.0"
        supported_sectors: ["law_enf"]
    """

    name = "weapon_detection"
    version = "1.0.0"
    supported_sectors = ["law_enf"]

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detect weapons in the frame.

        Synthetic implementation: detects a red rectangle in top-right corner.
        Real implementation would use YOLOv8 model.

        Args:
            frame: numpy array (H, W, 3) uint8

        Returns:
            List of detections with label "weapon", confidence, bbox.
        """
        if frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        # Look for red rectangle in top-right corner (same region as synthetic test)
        # We assume the weapon is encoded as a rectangle with high red channel and low green/blue.
        roi = frame[0:50, w-100:w]  # region of interest
        # Simple heuristic: if average red > 200 and green/blue are low, consider weapon present
        mean_red = np.mean(roi[:, :, 0])
        mean_green = np.mean(roi[:, :, 1])
        mean_blue = np.mean(roi[:, :, 2])

        if mean_red > 200 and mean_green < 100 and mean_blue < 100:
            confidence = min(0.85 + (mean_red - 200) / 1000, 0.99)
            detection = {
                "label": "weapon",
                "confidence": confidence,
                "bbox": [w - 100, 0, 100, 50],
                "type": "synthetic_placeholder"
            }
            return [detection]

        return []
