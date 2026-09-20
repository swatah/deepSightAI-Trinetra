"""
T2.1.6: Demographics plugin (commercial)

Estimates age and gender from frames. For TDD, reads encoded values.
"""

from typing import List, Dict, Any
import numpy as np
from Embedder.models.plugins.base import DetectionPlugin


class DemographicsPlugin(DetectionPlugin):
    """
    Demographics estimation plugin for commercial use.

    Attributes:
        name: "demographics"
        version: "1.0.0"
        supported_sectors: ["commercial"]
    """

    name = "demographics"
    version = "1.0.0"
    supported_sectors = ["commercial"]

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detect demographics (age, gender) in frame.

        Synthetic: reads age from first pixel red channel, gender from green.
        Real implementation would use ML models.

        Returns list with a single demographics detection.
        """
        if frame is None or frame.size == 0:
            return []

        # Read encoded values from pixel (0,0)
        age_val = int(frame[0, 0, 0])
        gender_val = int(frame[0, 0, 1])

        # Decode gender
        if gender_val == 0:
            gender = "male"
        elif gender_val == 255:
            gender = "female"
        else:
            gender = "other"

        detection = {
            "label": "demographics",
            "age": age_val,
            "age_confidence": 0.9,
            "gender": gender,
            "gender_confidence": 0.9,
            "bbox": [0, 0, frame.shape[1], frame.shape[0]]  # full frame
        }

        return [detection]
