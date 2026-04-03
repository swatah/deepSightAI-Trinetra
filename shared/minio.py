"""
T1.3.4: MinIO tenant-prefixed bucket paths

Provides utility to construct MinIO object keys with tenant prefix.
All data stored in MinIO should be namespaced under `{tenant_id}/`
to ensure tenant isolation in object storage.
"""


def make_prefixed_key(tenant_id: str, *parts: str) -> str:
    """
    Construct a MinIO object key with tenant_id as prefix.

    Args:
        tenant_id: Unique tenant identifier
        *parts: Path components (without leading/trailing slashes)

    Returns:
        Object key string: `{tenant_id}/{joined_parts}`

    Example:
        make_prefixed_key("tenant_abc", "frames", "segment_0001", "frame-00001.jpg")
        -> "tenant_abc/frames/segment_0001/frame-00001.jpg"
    """
    # Clean parts: strip any leading/trailing slashes to avoid double slashes
    cleaned_parts = []
    for part in parts:
        part_str = str(part).strip("/")
        if part_str:
            cleaned_parts.append(part_str)
    path = "/".join(cleaned_parts)
    return f"{tenant_id}/{path}"


def is_tenant_prefixed(object_key: str, tenant_id: str) -> bool:
    """
    Check if an object key already starts with the given tenant_id prefix.

    Args:
        object_key: The MinIO object key to check
        tenant_id: The tenant ID to look for at the start

    Returns:
        True if object_key begins with "tenant_id/", False otherwise.
    """
    if not object_key:
        return False
    prefix = f"{tenant_id}/"
    return object_key.startswith(prefix)
