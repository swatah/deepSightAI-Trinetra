"""
Test cases for the round-robin load balancer in registry.py.

These run against a real Redis instance rather than a mock. The selection
logic is implemented as a Lua script (see registry.py's _CLAIM_AVAILABLE_SCRIPT)
so that discovery + status-check + claim happen as one atomic, uninterruptible
operation on the Redis server -- that's what closes the race where two
concurrent callers could otherwise both see "available" before either writes
"busy". Mocking individual hget/hset calls can't exercise that: the Lua
script is bound to whatever Redis client exists at import time, and there's
nothing meaningful to assert about atomicity against a mock that isn't
actually concurrent. A real Redis instance is required to test this for real.

Set REDIS_URL to point at a running Redis (defaults to redis://localhost:6379).
Tests are skipped if no Redis is reachable.
"""
import concurrent.futures
import os
import sys

import pytest
import redis

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'Server and Extractor'))

TEST_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


def _redis_available():
    try:
        redis.Redis.from_url(TEST_REDIS_URL, socket_connect_timeout=1).ping()
        return True
    except redis.exceptions.RedisError:
        return False


pytestmark = pytest.mark.skipif(not _redis_available(), reason=f"No Redis reachable at {TEST_REDIS_URL}")


@pytest.fixture
def registry_module():
    """Import registry bound to the test Redis, with a clean keyspace per test."""
    os.environ["REDIS_URL"] = TEST_REDIS_URL
    sys.modules.pop("registry", None)
    import registry as registry_module

    for key in registry_module.r.keys("extractor*") + registry_module.r.keys("embedder*"):
        registry_module.r.delete(key)

    yield registry_module

    for key in registry_module.r.keys("extractor*") + registry_module.r.keys("embedder*"):
        registry_module.r.delete(key)


def _register(registry_module, kind, short, n):
    """kind: 'extractor' or 'embedder'; short: 'ext' or 'emb' (used in instance ids)."""
    for i in range(1, n + 1):
        instance_id = f"{short}{i}"
        registry_module.r.hset(
            f"{kind}:{instance_id}",
            mapping={
                f"{kind}_id": instance_id,
                f"{kind}_url": f"http://{instance_id}:8000",
                "status": "available",
            },
        )


def test_get_available_extractor_round_robin(registry_module):
    _register(registry_module, "extractor", "ext", 3)

    # Six calls (two full rounds), resetting each claimed extractor back to
    # "available" afterward -- expect a stable round-robin order.
    results = []
    for _ in range(6):
        result = registry_module.get_available_extractor()
        results.append(result["extractor_id"])
        registry_module.r.hset(f"extractor:{result['extractor_id']}", "status", "available")

    assert results == ["ext1", "ext2", "ext3", "ext1", "ext2", "ext3"]


def test_get_available_extractor_no_available(registry_module):
    with pytest.raises(Exception) as exc_info:
        registry_module.get_available_extractor()
    assert "No available extractors" in str(exc_info.value)


def test_get_available_embedder_round_robin(registry_module):
    _register(registry_module, "embedder", "emb", 3)

    results = []
    for _ in range(6):
        result = registry_module.get_available_embedder()
        results.append(result["embedder_id"])
        registry_module.r.hset(f"embedder:{result['embedder_id']}", "status", "available")

    assert results == ["emb1", "emb2", "emb3", "emb1", "emb2", "emb3"]


def test_get_available_embedder_no_available(registry_module):
    with pytest.raises(Exception) as exc_info:
        registry_module.get_available_embedder()
    assert "No available embedders" in str(exc_info.value)


def test_concurrent_claims_never_double_assign(registry_module):
    """
    Regression test for the round-robin race: fire many concurrent claims at a
    small number of available extractors and confirm each one is claimed by
    exactly one caller, with no duplicate assignment and no crash. This is the
    property a mock-based test can't verify -- it requires real concurrent
    requests against real shared state.
    """
    _register(registry_module, "extractor", "ext", 3)

    def claim():
        try:
            return registry_module.get_available_extractor()
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as ex:
        results = list(ex.map(lambda _: claim(), range(50)))

    claimed_ids = [r["extractor_id"] for r in results if r]
    assert len(claimed_ids) == 3, f"expected exactly 3 successful claims, got {len(claimed_ids)}: {claimed_ids}"
    assert len(set(claimed_ids)) == 3, f"duplicate claim detected: {claimed_ids}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
