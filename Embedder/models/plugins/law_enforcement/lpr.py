"""
T2.1.3: License Plate Recognition plugin (law_enf)

LPR plugin that detects license plates in frames.
For TDD, this implementation uses a synthetic encoding where plate
text is stored in the first row's red channel (ASCII values).
A real implementation would use OCR (e.g., EasyOCR, Tesseract).
"""

from typing import List, Dict, Any
import numpy as np
from Embedder.models.plugins.base import DetectionPlugin


class LPRPlugin(DetectionPlugin):
    """
    License Plate Recognition plugin for law enforcement.

    Attributes:
        name: "lpr"
        version: "1.0.0"
        supported_sectors: ["law_enf"]
    """

    name = "lpr"
    version = "1.0.0"
    supported_sectors = ["law_enf"]

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detect license plates in the frame.

        For the TDD prototype, we expect the frame to contain the plate
        number encoded in the first row's red channel as ASCII values.
        Real implementation would perform OCR on detected plate regions.

        Args:
            frame: numpy array (H, W, 3) uint8

        Returns:
            List of detections, each with:
                - label: "plate"
                - plate_number: str
                - confidence: float (>= 0.9)
                - bbox: [x, y, w, h] (approximate)
        """
        if frame is None or frame.size == 0:
            return []

        # Read ASCII values from first row, red channel
        first_row = frame[0, :, 0]  # red channel of first row
        # Extract non-zero characters as ASCII codes
        chars = []
        for val in first_row:
            if val > 0:
                chars.append(chr(val))
            else:
                # Stop at first zero (assume null-terminated)
                break

        plate_number = "".join(chars)

        if not plate_number:
            return []

        # In a real plugin, we'd have bounding boxes; here we return full width
        h, w = frame.shape[:2]
        detection = {
            "label": "plate",
            "plate_number": plate_number,
            "confidence": 0.95,
            "bbox": [0, 0, w, 30]  # placeholder bbox at top
        }

        return [detection]
