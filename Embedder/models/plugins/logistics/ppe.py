"""
T2.1.8: PPE detection plugin (logistics)

Detects hard hats (yellow) and safety vests (orange) in frames.
Synthetic: color-based detection.
"""

from typing import List, Dict, Any
import numpy as np
from Embedder.models.plugins.base import DetectionPlugin


class PPEDetectionPlugin(DetectionPlugin):
    """
    PPE detection plugin for logistics safety compliance.

    Attributes:
        name: "ppe_detection"
        version: "1.0.0"
        supported_sectors: ["logistics"]
    """

    name = "ppe_detection"
    version = "1.0.0"
    supported_sectors = ["logistics"]

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detect personal protective equipment (hard hats, safety vests).

        Synthetic implementation: looks for yellow (BGR: 0,255,255) for hard hats,
        and orange/amber (BGR: 0,165,255) for safety vests.
        Returns bounding boxes and confidences.
        """
        if frame is None or frame.size == 0:
            return []

        detections = []
        # Hard hat: yellow
        yellow_mask = (
            (frame[:, :, 0] == 0) &
            (frame[:, :, 1] == 255) &
            (frame[:, :, 2] == 255)
        )
        self._add_detections_from_mask(yellow_mask, frame, "hard_hat", detections)

        # Safety vest: orange (0,165,255)
        orange_mask = (
            (frame[:, :, 0] == 0) &
            (frame[:, :, 1] == 165) &
            (frame[:, :, 2] == 255)
        )
        self._add_detections_from_mask(orange_mask, frame, "safety_vest", detections)

        return detections

    def _add_detections_from_mask(self, mask: np.ndarray, frame: np.ndarray, label: str, detections: list):
        """Find connected components in mask and add detections."""
        # Use connected components (BFS) similar to face blur
        visited = np.zeros_like(mask, dtype=bool)
        h, w = mask.shape
        components = []

        for y in range(h):
            for x in range(w):
                if mask[y, x] and not visited[y, x]:
                    stack = [(x, y)]
                    pixels = []
                    while stack:
                        px, py = stack.pop()
                        if visited[py, px]:
                            continue
                        visited[py, px] = True
                        pixels.append((px, py))
                        for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)]:
                            nx, ny = px+dx, py+dy
                            if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not visited[ny, nx]:
                                stack.append((nx, ny))
                    components.append(pixels)

        for comp in components:
            if len(comp) < 10:  # filter tiny noise
                continue
            xs, ys = zip(*comp)
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)
            bbox_w = x_max - x_min + 1
            bbox_h = y_max - y_min + 1
            # configure confidence based on size? Use fixed high.
            confidence = 0.93
            detection = {
                "label": label,
                "confidence": confidence,
                "bbox": [int(x_min), int(y_min), int(bbox_w), int(bbox_h)]
            }
            detections.append(detection)
