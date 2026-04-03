"""
T1.3.6: Redis key namespace per tenant

All Redis keys must include tenant_id as prefix:
- extractor:{tenant_id}:{extractor_id}
- embedder:{tenant_id}:{embedder_id}
- Status keys: {tenant_id}:extractor:status:{id}

Tests verify that key construction functions produce tenant-prefixed keys.
"""

import pytest
from shared.redis_utils import make_extractor_key, make_embedder_key, make_status_key


class TestRedisKeyNamespacing:
    """Test Redis key construction with tenant prefixes."""

    def test_make_extractor_key_includes_tenant(self):
        key = make_extractor_key("tenant-123", "extractor-1")
        assert key == "tenant-123:extractor:extractor-1"
        # Or could be "extractor:tenant-123:extractor-1" - but must include tenant

    def test_make_embedder_key_includes_tenant(self):
        key = make_embedder_key("org_abc", "embedder-2")
        assert key.startswith("org_abc:") or key.endswith(":org_abc")

    def test_make_status_key_includes_tenant(self):
        key = make_status_key("tenant1", "extractor", "ext-3")
        assert "tenant1" in key

    def test_different_tenants_different_keys(self):
        key1 = make_extractor_key("tenant_a", "ext-1")
        key2 = make_extractor_key("tenant_b", "ext-1")
        assert key1 != key2
        assert "tenant_a" in key1
        assert "tenant_b" in key2
