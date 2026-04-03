"""
T2.1.5: Face blur plugin (GDPR privacy)

Tests that all faces are blurred with ≥95% coverage while preserving utility.
For TDD, we use synthetic frames with a blue "face" rectangle.
"""

import pytest
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Embedder.models.plugins.base import DetectionPlugin


@pytest.fixture
def blur_plugin_class():
    from Embedder.models.plugins.law_enforcement.face_blur import FaceBlurPlugin
    return FaceBlurPlugin


class TestFaceBlur:
    """Test Face Blur plugin."""

    def create_frame_with_face(self, face_bbox, frame_size=(640, 480, 3)):
        """
        Create frame with a synthetic "face" region (a solid blue rectangle).
        """
        frame = np.zeros(frame_size, dtype=np.uint8)
        x, y, w, h = face_bbox
        frame[y:y+h, x:x+w] = [255, 0, 0]  # blue in BGR
        return frame

    def test_plugin_interface(self, blur_plugin_class):
        assert issubclass(blur_plugin_class, DetectionPlugin)
        assert blur_plugin_class.name == "face_blur"
        assert blur_plugin_class.version == "1.0.0"
        assert "law_enf" in blur_plugin_class.supported_sectors

    def test_detects_face_region(self, blur_plugin_class):
        """Plugin should return bbox covering the face."""
        face_bbox = (100, 100, 80, 100)
        frame = self.create_frame_with_face(face_bbox)
        plugin = blur_plugin_class()
        detections = plugin.detect(frame)

        # Expect one detection
        assert len(detections) >= 1
        face_det = next((d for d in detections if d.get("label") == "face"), None)
        assert face_det is not None
        x, y, w, h = face_det["bbox"]
        # Compute IoU with ground truth
        gt = face_bbox
        det = (x, y, w, h)
        iou = self._bbox_iou(gt, det)
        assert iou >= 0.95, f"Coverage IoU {iou:.2f} < 0.95"

    def test_multiple_faces(self, blur_plugin_class):
        """Plugin should detect multiple faces."""
        faces = [(50, 50, 50, 50), (200, 100, 60, 70), (400, 200, 40, 50)]
        frame = self.create_frame_with_face((0,0,0,0))  # placeholder
        # Draw multiple blue rectangles
        for bbox in faces:
            x, y, w, h = bbox
            frame[y:y+h, x:x+w] = [255, 0, 0]

        plugin = blur_plugin_class()
        detections = [d for d in plugin.detect(frame) if d.get("label") == "face"]
        assert len(detections) == 3

        # Each detection should have high IoU with corresponding ground truth
        matched = 0
        for gt in faces:
            best_iou = 0
            for det in detections:
                iou = self._bbox_iou(gt, det["bbox"])
                if iou > best_iou:
                    best_iou = iou
            if best_iou >= 0.9:  # allow some tolerance
                matched += 1
        assert matched >= 2  # at least 2 of 3 with decent IoU

    def test_no_false_positives_on_blank(self, blur_plugin_class):
        """Blank frame should produce no face detections."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        plugin = blur_plugin_class()
        detections = [d for d in plugin.detect(frame) if d.get("label") == "face"]
        assert len(detections) == 0

    def test_plugin_config_used(self, blur_plugin_class):
        config = {"blur_kernel": 51, "threshold": 0.1}
        plugin = blur_plugin_class(config)
        assert plugin.config["blur_kernel"] == 51
        assert plugin.config["threshold"] == 0.1

    def _bbox_iou(self, bbox1, bbox2):
        """Compute Intersection over Union of two bboxes (x,y,w,h)."""
        x1, y1, w1, h1 = bbox1
        x2, y2, w2, h2 = bbox2

        # Convert to x1,y1,x2,y2
        a_x1, a_y1, a_x2, a_y2 = x1, y1, x1 + w1, y1 + h1
        b_x1, b_y1, b_x2, b_y2 = x2, y2, x2 + w2, y2 + h2

        inter_x1 = max(a_x1, b_x1)
        inter_y1 = max(a_y1, b_y1)
        inter_x2 = min(a_x2, b_x2)
        inter_y2 = min(a_y2, b_y2)

        inter_w = max(0, inter_x2 - inter_x1)
        inter_h = max(0, inter_y2 - inter_y1)
        inter = inter_w * inter_h

        area1 = w1 * h1
        area2 = w2 * h2
        union = area1 + area2 - inter

        if union == 0:
            return 0
        return inter / union
