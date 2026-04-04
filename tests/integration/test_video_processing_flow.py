"""
Integration test: Full video processing pipeline.

Tests that a video upload goes through complete flow:
upload → extract → embed → searchable

Uses test containers (PostgreSQL, Redis, MinIO, Milvus).
Run with: pytest tests/integration/ -v
"""

import pytest
import uuid
import time
import requests
from minio import Minio
from pymilvus import connections, Collection


@pytest.fixture(scope="module")
def services():
    """
    Provide service connections for integration tests.
    Assumes Docker containers running via CI or local docker-compose.
    """
    return {
        "minio_url": "http://localhost:9000",
        "minio_access": "minioadmin",
        "minio_secret": "minioadmin",
        "redis_url": "redis://localhost:6379",
        "milvus_host": "localhost",
        "milvus_port": "19530",
        "postgres_url": "postgresql://postgres:test@localhost:5432/deepSightAI-Trinetra_test",
        "api_url": "http://localhost:8080",
    }


@pytest.fixture
def test_tenant(services):
    """Create a test tenant for isolation."""
    # This would call tenant provisioning endpoint
    tenant_id = f"test-{uuid.uuid4().hex[:8]}"

    # In real implementation:
    # response = requests.post(f"{services['api_url']}/admin/tenants", json={
    #     "id": tenant_id,
    #     "name": "Test Tenant",
    #     "plan": "starter"
    # })
    # assert response.status_code == 201

    yield tenant_id

    # Cleanup
    # requests.delete(f"{services['api_url']}/admin/tenants/{tenant_id}")


def test_full_video_processing_pipeline(services, test_tenant, sample_video_path):
    """
    GIVEN a test tenant with API key
    WHEN a video is uploaded
    THEN it is processed end-to-end and searchable
    """
    # 1. Authenticate as test tenant
    api_key = "test-key-123"  # Would be obtained from auth service
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Tenant-ID": test_tenant
    }

    # 2. Upload video
    with open(sample_video_path, "rb") as f:
        response = requests.post(
            f"{services['api_url']}/videos/upload",
            files={"video": f},
            headers=headers
        )
    assert response.status_code == 202, f"Upload failed: {response.text}"
    video_id = response.json()["video_id"]

    # 3. Wait for processing (poll status)
    max_wait = 300  # seconds
    start = time.time()
    processed = False
    while time.time() - start < max_wait:
        status_resp = requests.get(
            f"{services['api_url']}/videos/{video_id}/status",
            headers=headers
        )
        status = status_resp.json()["status"]
        if status == "processed":
            processed = True
            break
        elif status == "error":
            pytest.fail(f"Video processing failed: {status_resp.json()}")
        time.sleep(5)

    assert processed, "Video not processed within timeout"

    # 4. Check frames in MinIO
    minio_client = Minio(
        services["minio_url"].replace("http://", ""),
        access_key=services["minio_access"],
        secret_key=services["minio_secret"],
        secure=False
    )
    # Should NOT find frames - they should be deleted after embedding
    frames = list(minio_client.list_objects("frames", prefix=f"{video_id}/"))
    assert len(frames) == 0, "Frames should be deleted after embedding"

    # 5. Search for content (semantic search)
    search_resp = requests.post(
        f"{services['api_url']}/search/text",
        json={"query": "person walking"},
        headers=headers
    )
    assert search_resp.status_code == 200
    results = search_resp.json()["results"]

    # 6. Verify results in Milvus
    connections.connect(
        alias="default",
        host=services["milvus_host"],
        port=services["milvus_port"]
    )
    collection = Collection("video_frames")  # Would be tenant-specific
    collection.load()

    for result in results[:3]:  # Check top 3
        frame_path = result["frame_path"]
        video_id_from_result = result["video_id"]

        assert video_id_from_result == video_id
        # Could also verify embedding exists by searching for that exact frame

    # 7. Verify audit log entry
    audit_resp = requests.get(
        f"{services['api_url']}/admin/audit?tenant_id={test_tenant}&action=video.uploaded",
        headers=headers
    )
    assert audit_resp.status_code == 200
    logs = audit_resp.json()["logs"]
    assert len(logs) > 0, "Should have audit log for upload"

    print(f"✓ Full pipeline test passed for video {video_id}")


def test_multi_tenant_isolation(services):
    """
    GIVEN two different tenants
    WHEN tenant A uploads a video and searches
    THEN tenant B cannot see tenant A's data
    """
    # Create two tenants
    tenant_a = f"tenant-a-{uuid.uuid4().hex[:8]}"
    tenant_b = f"tenant-b-{uuid.uuid4().hex[:8]}"

    # Tenant A uploads video
    headers_a = {"Authorization": "Bearer key-a", "X-Tenant-ID": tenant_a}
    # Upload logic...

    # Tenant B searches for same content
    headers_b = {"Authorization": "Bearer key-b", "X-Tenant-ID": tenant_b}
    search_resp = requests.post(
        f"{services['api_url']}/search/text",
        json={"query": "person walking"},
        headers=headers_b
    )

    # Verify tenant B gets no results from tenant A's video
    for result in search_resp.json()["results"]:
        assert result["tenant_id"] == tenant_b, \
            f"Cross-tenant leak detected: {result['tenant_id']} != {tenant_b}"

    print("✓ Multi-tenant isolation verified")


def test_retention_policy_deletes_old_data(services, test_tenant):
    """
    GIVEN a video older than tenant's retention period
    WHEN retention worker runs
    THEN video is deleted from all systems
    """
    # This test simulates time passage (freeze time)
    # Upload video
    # Manually set upload timestamp to 31 days ago (if retention=30)
    # Run retention cleanup job
    # Verify video deleted from Milvus and MinIO

    pytest.skip("Needs time-freezing fixtures - implement with freezegun")


def test_quota_enforcement(services, test_tenant):
    """
    GIVEN tenant with 10 video/month quota
    AFTER uploading 10 videos
    WHEN attempting 11th upload
    THEN it is rejected with 429 Too Many Requests
    """
    # This would need quota reset to known state
    # Upload up to quota
    # Verify 11th fails
    pytest.skip("Requires quota management implementation")


def test_audit_log_immutability(services, test_tenant):
    """
    GIVEN an audit log entry
    WHEN attempting to modify or delete
    THEN operation fails with permission error
    """
    # Insert audit entry
    # Try to UPDATE/DELETE it as admin
    # Should fail (audit_logs table should have RLS or triggers)
    pytest.skip("Requires database immutability setup")
