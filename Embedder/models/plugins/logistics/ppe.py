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
        """Find connected components in mask and add detections using fast labeling."""
        # Use scipy.ndimage.label if available, else fallback to simple bounding box of all mask pixels
        # Since synthetic rectangles are solid and non-overlapping, we can use a simple approach:
        # Find all mask pixels and then split by checking gaps? But easier: use opencv if available.
        # We'll try to use cv2.connectedComponents if opencv is present, else use scipy, else fallback to BFS.
        try:
            import cv2
            mask_uint8 = mask.astype(np.uint8) * 255
            num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask_uint8, connectivity=4)
            # stats: [label, left, top, width, height, area]
            for lbl in range(1, num_labels):
                x = stats[lbl, cv2.CC_STAT_LEFT]
                y = stats[lbl, cv2.CC_STAT_TOP]
                w = stats[lbl, cv2.CC_STAT_WIDTH]
                h = stats[lbl, cv2.CC_STAT_HEIGHT]
                area = stats[lbl, cv2.CC_STAT_AREA]
                if area < 10:
                    continue
                detections.append({
                    "label": label,
                    "confidence": 0.93,
                    "bbox": [int(x), int(y), int(w), int(h)]
                })
            return
        except ImportError:
            pass

        try:
            from scipy import ndimage
            labeled, num_features = ndimage.label(mask)
            # find_objects returns a list of tuples (slice_y, slice_x) for each label
            objects = ndimage.find_objects(labeled)
            for i, slc in enumerate(objects, start=1):
                if slc is None:
                    continue
                ys, xs = slc
                bbox_h = ys.stop - ys.start
                bbox_w = xs.stop - xs.start
                area = bbox_h * bbox_w
                if area < 10:
                    continue
                detections.append({
                    "label": label,
                    "confidence": 0.93,
                    "bbox": [int(xs.start), int(ys.start), int(bbox_w), int(bbox_h)]
                })
            return
        except ImportError:
            pass

        # Fallback BFS (optimized) - only iterate over foreground pixels
        visited = np.zeros_like(mask, dtype=bool)
        h, w = mask.shape
        fg_coords = np.argwhere(mask)  # (N, 2) array of (y, x)
        components = []

        for y, x in fg_coords:
            if not visited[y, x]:
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
            if len(comp) < 10:
                continue
            xs, ys = zip(*comp)
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)
            detection = {
                "label": label,
                "confidence": 0.93,
                "bbox": [int(x_min), int(y_min), int(x_max - x_min + 1), int(y_max - y_min + 1)]
            }
            detections.append(detection)
