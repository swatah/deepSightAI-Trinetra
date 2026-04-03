"""
T1.3.5: Milvus tenant isolation

Tests that Milvus data is isolated by tenant using separate collections.
"""

import pytest
from shared.milvus import get_collection_name, ensure_tenant_collection, drop_tenant_collection


class TestMilvusTenantIsolation:
    """Test Milvus tenant isolation."""

    def test_get_collection_name_includes_tenant(self):
        """Collection name should include tenant_id."""
        name = get_collection_name("tenant-abc")
        assert name == "video_frames_tenant_abc"

        name2 = get_collection_name("org_123")
        assert name2 == "video_frames_org_123"

    def test_get_collection_name_sanitizes(self):
        """Tenant IDs with hyphens should be converted to underscores."""
        name = get_collection_name("my-org")
        assert "-" not in name
        assert name == "video_frames_my_org"

    def test_ensure_tenant_collection_creates_schema(self):
        """Should create collection with required fields."""
        # Integration test - requires Milvus running
        pytest.skip("Requires Milvus container - run integration tests")

    def test_drop_tenant_collection_removes_collection(self):
        """Should drop the tenant's collection."""
        pytest.skip("Requires Milvus container")

    @pytest.mark.integration
    def test_tenant_collections_are_independent(self):
        """Different tenants get different collections."""
        pytest.skip("Requires Milvus container")
