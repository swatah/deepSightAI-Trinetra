"""
T1.3.6: Redis key namespace per tenant under deepSightAI.Trinetra.Shared.RedisUtils.
"""


def _sanitize_tenant_id(tenant_id: str) -> str:
    return tenant_id.replace(" ", "_")


def make_extractor_key(tenant_id: str, extractor_id: str) -> str:
    safe_tenant = _sanitize_tenant_id(tenant_id)
    return f"{safe_tenant}:extractor:{extractor_id}"


def make_embedder_key(tenant_id: str, embedder_id: str) -> str:
    safe_tenant = _sanitize_tenant_id(tenant_id)
    return f"{safe_tenant}:embedder:{embedder_id}"


def make_status_key(tenant_id: str, service_type: str, service_id: str) -> str:
    safe_tenant = _sanitize_tenant_id(tenant_id)
    return f"{safe_tenant}:{service_type}:status:{service_id}"


def make_tenant_prefix(tenant_id: str) -> str:
    safe_tenant = _sanitize_tenant_id(tenant_id)
    return f"{safe_tenant}:"


def get_tenant_from_key(key: str, default: str = None) -> str | None:
    if ":" not in key:
        return default
    prefix = key.split(":", 1)[0]
    return prefix if prefix != "" else default
