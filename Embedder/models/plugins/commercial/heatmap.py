"""
T2.1.7: Heatmap and queue detection (commercial)

Accumulates activity heatmap from frames and detects queue lines.
For TDD, activity encoded as red patches.
"""

from typing import List, Dict, Any, Tuple
import numpy as np
from Embedder.models.plugins.base import DetectionPlugin


class HeatmapPlugin(DetectionPlugin):
    """
    Heatmap and queue detection plugin for commercial analytics.

    Attributes:
        name: "heatmap"
        version: "1.0.0"
        supported_sectors: ["commercial"]
    """

    name = "heatmap"
    version = "1.0.0"
    supported_sectors = ["commercial"]

    def __init__(self, config: dict = None):
        super().__init__(config)
        # Grid resolution for heatmap
        self.resolution = self.config.get("resolution", (32, 32))  # (cols, rows)
        self.decay_factor = self.config.get("decay_factor", 1.0)  # no decay by default
        self.heatmap = np.zeros(self.resolution, dtype=np.float32)
        # For queue detection: track consecutive activity per column
        self.col_streak = {}  # col -> consecutive count
        self.min_queue_frames = self.config.get("min_queue_frames", 5)
        self.detected_queues = []  # list of (x, w) tuples in grid columns

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Process a frame to update heatmap and detect queues.

        Synthetic: finds red patches (activity) and accumulates into grid cells.
        Also updates column streaks to identify queues (vertical alignment).

        Returns a detection dict with metadata; primarily updates internal state.
        """
        if frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        # Find activity pixels (red dominant)
        red = frame[:, :, 0]
        green = frame[:, :, 1]
        blue = frame[:, :, 2]
        activity_mask = (red > 200) & (green < 50) & (blue < 50)

        # Map activity pixels to heatmap grid cells
        grid_h, grid_w = self.resolution
        # Compute cell coordinates for each activity pixel
        ys, xs = np.where(activity_mask)
        if len(xs) == 0:
            return []

        # Map to grid cells
        cell_x = (xs * grid_w // w).astype(int)
        cell_y = (ys * grid_h // h).astype(int)

        # Fast linear bin count (1D bincount with reshaping)
        # Compute linear index: row * grid_w + col
        indices = cell_y * grid_w + cell_x
        counts = np.bincount(indices, minlength=grid_h * grid_w)
        self.heatmap += counts.reshape(grid_h, grid_w)

        # For queue detection: count activity per column (in grid col)
        active_cols = set(cell_x)
        # Update streaks: increment for columns that had activity, reset others
        all_cols = set(range(grid_w))
        for col in all_cols:
            if col in active_cols:
                self.col_streak[col] = self.col_streak.get(col, 0) + 1
            else:
                self.col_streak[col] = 0
        # Check for new queues: columns with streak >= min_queue_frames and not already detected
        for col, streak in self.col_streak.items():
            if streak >= self.min_queue_frames and col not in self.detected_queues:
                self.detected_queues.append(col)

        return [{"label": "heatmap_update", "activity_pixels": int(len(xs))}]

    def get_heatmap(self) -> np.ndarray:
        """Return the accumulated heatmap grid."""
        return self.heatmap.copy()

    def get_queue_regions(self) -> List[Tuple[int, int, int, int]]:
        """
        Return queue bounding boxes in grid coordinates (x, y, w, h).
        For each detected queue column, we create a bbox covering full height.
        """
        regions = []
        if not self.detected_queues:
            return regions
        # Merge adjacent columns into contiguous queue zones
        cols = sorted(self.detected_queues)
        # Group consecutive columns
        start = cols[0]
        prev = cols[0]
        for col in cols[1:]:
            if col == prev + 1:
                prev = col
            else:
                # Close current group
                x = start
                w = prev - start + 1
                regions.append((x, 0, w, self.resolution[1]))  # full vertical span
                start = col
                prev = col
        # Final group
        x = start
        w = prev - start + 1
        regions.append((x, 0, w, self.resolution[1]))
        return regions
