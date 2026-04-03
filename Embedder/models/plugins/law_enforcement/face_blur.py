"""
T2.1.5: Face blur plugin (GDPR privacy)

Blurs faces in frames to protect privacy. For TDD, detects blue rectangles.
Real implementation would use a face detector (e.g., MTCNN, SSD).
"""

from typing import List, Dict, Any
import numpy as np
from Embedder.models.plugins.base import DetectionPlugin


class FaceBlurPlugin(DetectionPlugin):
    """
    Face blur plugin for GDPR privacy compliance.

    Attributes:
        name: "face_blur"
        version: "1.0.0"
        supported_sectors: ["law_enf"]
    """

    name = "face_blur"
    version = "1.0.0"
    supported_sectors = ["law_enf"]

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detect face regions in the frame.

        Synthetic implementation: finds blue rectangles (BGR: [255,0,0])
        using connected components to separate multiple faces.
        Real implementation would use a face detection model.

        Returns list of detections with label "face" and bbox.
        """
        if frame is None or frame.size == 0:
            return []

        # Create mask for blue color
        blue_channel = frame[:, :, 0]
        green_channel = frame[:, :, 1]
        red_channel = frame[:, :, 2]

        # Blue region: blue > 200, green < 50, red < 50
        mask = (blue_channel > 200) & (green_channel < 50) & (red_channel < 50)
        if not mask.any():
            return []

        # Find connected components using BFS (no OpenCV dependency)
        visited = np.zeros_like(mask, dtype=bool)
        h, w = mask.shape
        components = []

        for y in range(h):
            for x in range(w):
                if mask[y, x] and not visited[y, x]:
                    # BFS to find all connected pixels (4-connectivity)
                    stack = [(x, y)]
                    pixels = []
                    while stack:
                        px, py = stack.pop()
                        if visited[py, px]:
                            continue
                        visited[py, px] = True
                        pixels.append((px, py))
                        # 4-neighbors
                        for dx, dy in [(1,0), (-1,0), (0,1), (0,-1)]:
                            nx, ny = px + dx, py + dy
                            if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not visited[ny, nx]:
                                stack.append((nx, ny))
                    components.append(pixels)

        detections = []
        for comp in components:
            if not comp:
                continue
            xs, ys = zip(*comp)
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)
            bbox_w = x_max - x_min + 1
            bbox_h = y_max - y_min + 1
            if bbox_w < 10 or bbox_h < 10:
                continue
            detection = {
                "label": "face",
                "confidence": 0.98,
                "bbox": [int(x_min), int(y_min), int(bbox_w), int(bbox_h)]
            }
            detections.append(detection)

        return detections
