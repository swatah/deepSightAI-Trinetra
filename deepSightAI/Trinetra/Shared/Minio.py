"""
T1.3.4: MinIO tenant-prefixed bucket paths under deepSightAI.Trinetra.Shared.Minio.
"""


def make_prefixed_key(tenant_id: str, *parts: str) -> str:
    """
    Construct a MinIO object key with tenant_id as prefix.
    """
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
    """
    if not object_key:
        return False
    prefix = f"{tenant_id}/"
    return object_key.startswith(prefix)
