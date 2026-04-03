"""
T1.3.4: MinIO tenant-prefixed bucket paths

Tests that MinIO object keys are constructed with tenant prefix.
"""

import pytest
from shared.minio import make_prefixed_key, is_tenant_prefixed


class TestMinioTenantPrefix:
    """Test tenant-prefixed key utilities."""

    def test_make_prefixed_key_creates_correct_path(self):
        key = make_prefixed_key("tenant-123", "videos/intro.mp4")
        assert key == "tenant-123/videos/intro.mp4"

    def test_make_prefixed_key_handles_trailing_slash(self):
        key = make_prefixed_key("tenant_abc", "/frames/frame1.jpg")
        assert key == "tenant_abc/frames/frame1.jpg"
        key2 = make_prefixed_key("tenant_abc", "frames/frame1.jpg")
        assert key2 == "tenant_abc/frames/frame1.jpg"

    def test_make_prefixed_key_with_multiple_parts(self):
        parts = ["videos", "segment_0001", "frame-00001.jpg"]
        key = make_prefixed_key("tenant-xyz", *parts)
        assert key == "tenant-xyz/videos/segment_0001/frame-00001.jpg"

    def test_is_tenant_prefixed_checks_exact_tenant(self):
        assert is_tenant_prefixed("tenant-alpha/videos/vid1.mp4", "tenant-alpha")
        assert is_tenant_prefixed("tenant-abc/frames/frame.jpg", "tenant-abc")
        # Different tenant ID -> False
        assert not is_tenant_prefixed("tenant-alpha/videos/vid1.mp4", "tenant-beta")
        # Not prefixed at all
        assert not is_tenant_prefixed("videos/vid1.mp4", "tenant-alpha")
        # Just the word "tenant" is not a match unless exact
        assert not is_tenant_prefixed("tenant/video.mp4", "tenant-alpha")

    def test_prefix_includes_both_videos_and_frames(self):
        video_key = make_prefixed_key("tenant1", "videos/intro.mp4")
        frames_key = make_prefixed_key("tenant1", "frames/seg0/frame1.jpg")
        assert video_key.startswith("tenant1/")
        assert frames_key.startswith("tenant1/")
