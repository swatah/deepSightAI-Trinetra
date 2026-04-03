"""
T2.1.7: Heatmap and queue detection (commercial)

Tests that plugin generates heatmap data from footage and detects queues.
Synthetic: activity encoded as red patches; queue as vertical line of patches.
"""

import pytest
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Embedder.models.plugins.base import DetectionPlugin


@pytest.fixture
def heatmap_plugin_class():
    from Embedder.models.plugins.commercial.heatmap import HeatmapPlugin
    return HeatmapPlugin


class TestHeatmapPlugin:
    """Test Heatmap and Queue detection plugin."""

    def create_frame_with_activity(self, region_idx=0, frame_size=(640, 480, 3)):
        """
        Create a synthetic frame with activity in one of predefined regions.
        We'll define 4 quadrants as regions. Set a red patch in the given region.
        """
        frame = np.zeros(frame_size, dtype=np.uint8)
        h, w = frame.shape[:2]
        # Define regions: 0=top-left, 1=top-right, 2=bottom-left, 3=bottom-right
        half_h, half_w = h // 2, w // 2
        regions = [
            (0, 0, half_w, half_h),         # top-left
            (half_w, 0, half_w, half_h),    # top-right
            (0, half_h, half_w, half_h),    # bottom-left
            (half_w, half_h, half_w, half_h) # bottom-right
        ]
        x, y, rw, rh = regions[region_idx % 4]
        # Draw red patch in that region
        frame[y:y+rh, x:x+rw, 0] = 255  # red channel
        return frame

    def test_plugin_interface(self, heatmap_plugin_class):
        assert issubclass(heatmap_plugin_class, DetectionPlugin)
        assert heatmap_plugin_class.name == "heatmap"
        assert heatmap_plugin_class.version == "1.0.0"
        assert "commercial" in heatmap_plugin_class.supported_sectors

    def test_heatmap_accumulation(self, heatmap_plugin_class):
        """Process frames with activity in different regions and check heatmap."""
        config = {"resolution": (2, 2)}
        plugin = heatmap_plugin_class(config)
        num_per_region = 25

        # Send frames with activity in each region
        for region in range(4):
            for _ in range(num_per_region):
                frame = self.create_frame_with_activity(region)
                plugin.detect(frame)

        # Get heatmap; it should have higher counts in regions where activity occurred
        heatmap = plugin.get_heatmap()
        assert heatmap.shape == (2, 2)

        # Each region's count should be approximately num_per_region (allow tolerance)
        for region in range(4):
            r, c = divmod(region, 2)
            count = heatmap[r, c]
            # Should be at least num_per_region - some tolerance
            assert count >= num_per_region * 0.8, f"Region {region} count {count} too low"

    def test_queue_detection(self, heatmap_plugin_class):
        """
        Queue detection: consecutive frames showing activity in the same
        vertical column over time (people lining up) should be flagged as a queue.
        """
        config = {"resolution": (32, 32), "min_queue_frames": 3}
        plugin = heatmap_plugin_class(config)
        h, w = 480, 640
        # Simulate a queue: same x-range but varying y positions along a vertical line
        column_px = w // 2
        patch_width = 20
        patch_height = 30
        queue_y_positions = [100, 150, 200, 250, 300]

        # Create frames where each frame adds a patch at a specific y in the queue
        for y in queue_y_positions:
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            frame[y:y+patch_height, column_px:column_px+patch_width, 0] = 255
            plugin.detect(frame)

        # After processing, plugin should have detected a queue region
        queue_bboxes = plugin.get_queue_regions()
        assert len(queue_bboxes) >= 1
        # The queue column in grid coordinates
        grid_w = 32
        col_grid = int(column_px * grid_w / w)  # 320*32/640 = 16
        q = queue_bboxes[0]
        qx, qy, qw, qh = q
        # The detected queue bbox's x should include that grid column
        assert qx <= col_grid <= qx + qw

    def test_plugin_config_used(self, heatmap_plugin_class):
        config = {"resolution": (32, 32), "decay_factor": 0.99}
        plugin = heatmap_plugin_class(config)
        assert plugin.config["resolution"] == (32, 32)
        assert plugin.config["decay_factor"] == 0.99
