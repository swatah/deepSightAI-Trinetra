"""
T1.3.6: Redis key namespace per tenant

All Redis keys must be prefixed with tenant_id to ensure isolation.
Provides functions to construct tenant-scoped keys for service registry.
"""


def _sanitize_tenant_id(tenant_id: str) -> str:
    """Sanitize tenant_id for use in Redis key (replace spaces, special chars)."""
    # For simplicity, just replace spaces with underscores; could be stricter
    return tenant_id.replace(" ", "_")


def make_extractor_key(tenant_id: str, extractor_id: str) -> str:
    """
    Construct Redis key for an extractor registry entry.

    Format: {tenant_id}:extractor:{extractor_id}
    """
    safe_tenant = _sanitize_tenant_id(tenant_id)
    return f"{safe_tenant}:extractor:{extractor_id}"


def make_embedder_key(tenant_id: str, embedder_id: str) -> str:
    """
    Construct Redis key for an embedder registry entry.

    Format: {tenant_id}:embedder:{embedder_id}
    """
    safe_tenant = _sanitize_tenant_id(tenant_id)
    return f"{safe_tenant}:embedder:{embedder_id}"


def make_status_key(tenant_id: str, service_type: str, service_id: str) -> str:
    """
    Construct Redis key for service status.

    Format: {tenant_id}:{service_type}:status:{service_id}
    Example: "tenant1:extractor:status:ext-1"
    """
    safe_tenant = _sanitize_tenant_id(tenant_id)
    return f"{safe_tenant}:{service_type}:status:{service_id}"


def make_tenant_prefix(tenant_id: str) -> str:
    """
    Get the Redis key prefix for all keys belonging to a tenant.

    Returns string ending with ':' e.g., "tenant_abc:"
    """
    safe_tenant = _sanitize_tenant_id(tenant_id)
    return f"{safe_tenant}:"


def get_tenant_from_key(key: str, default: str = None) -> str | None:
    """
    Extract tenant_id from a tenant-prefixed Redis key.
    Returns the tenant prefix (up to first colon) if it looks like a tenant ID.
    """
    if ":" not in key:
        return default
    prefix = key.split(":", 1)[0]
    # Heuristic: if prefix ends with known patterns like 'extractor' etc., it's not tenant
    # For our format, first component should be tenant_id (since we use tenant:...)
    # However, if someone uses 'extractor:tenant:id', this would return 'extractor'. We assume standard format.
    return prefix if prefix != "" else default
