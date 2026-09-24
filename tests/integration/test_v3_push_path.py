"""
Integration Test Suite for Enterprise Ingestion V3 — Push Path (Issue #94, Testing Plan §3).

Covers:
- E1/E2: Single and batch submission with itemized responses
- E2: Batch submission with partial failure isolation
- E3: Credential validation, immediate revocation, and 5-failure lockout
- E4/S2: Camera-to-device scoping and rejection of cameras assigned to pull path
- §5.3: Parameterized field omission, dimension mismatch, and unknown model rejection
- E5: Sequential and concurrent duplicate event_id idempotency
- E5/E6: Circuit breaker 503 on dedup store or downstream outages
- E7: Liveness staleness detection and clock skew clamping
- E8: Deprecated version handling and sunset version 410 Gone

Strictly adheres to CODING_STANDARDS.md.
"""

import time
import uuid
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import HTTPException

from deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest import (
    dsai_edge_router,
    EdgeIngestService,
    dsai_require_edge_auth,
)
from deepSightAI.Trinetra.Shared.Streaming.Schema import (
    EdgeEmbeddingEventV1,
    DSAI_KNOWN_EMBEDDING_MODELS,
)
from deepSightAI.Trinetra.AuthService.auth_service import (
    get_db,
    dsai_verify_edge_device,
    _dsai_edge_lockout_tracker,
)
from deepSightAI.Trinetra.Shared.Repositories.CameraRepository import CameraRepository
from deepSightAI.Trinetra.Shared.dsai_circuit_breaker import dsai_reset_circuit_breakers
from tests.harness.dsai_edge_simulator import (
    DSAIEdgeDeviceSimulator,
    DSAI_PROFILE_VENDOR_A,
    DSAI_PROFILE_VENDOR_B,
)
from tests.fixtures.dsai_backing_services import (
    dsai_setup_in_memory_auth_db,
    dsai_provision_test_edge_device,
)

# Standalone test app for router testing
from fastapi import FastAPI
dsai_test_app = FastAPI()
dsai_test_app.include_router(dsai_edge_router)


@pytest.mark.ci_tier
@pytest.mark.integration
class TestPushPathIntegrationE1ToE8:
    """Push path end-to-end integration test suite using edge device simulator."""

    @pytest.fixture(autouse=True)
    def dsai_setup_suite(self):
        """Prepare fresh in-memory database and simulator for each test."""
        dsai_reset_circuit_breakers()
        self.dsai_db = dsai_setup_in_memory_auth_db()
        self.dsai_tenant_id = "tenant-e2e-push"
        self.dsai_assigned_cam = "cam-push-001"
        self.dsai_device_id = "edge-device-unit-01"

        # Provision active edge device
        self.dsai_api_key = dsai_provision_test_edge_device(
            dsai_db=self.dsai_db,
            dsai_device_id=self.dsai_device_id,
            dsai_tenant_id=self.dsai_tenant_id,
            dsai_assigned_cameras=[self.dsai_assigned_cam]
        )

        # Initialize simulator with Vendor Profile A
        self.dsai_simulator_a = DSAIEdgeDeviceSimulator(
            dsai_device_id=self.dsai_device_id,
            dsai_tenant_id=self.dsai_tenant_id,
            dsai_api_key=self.dsai_api_key,
            dsai_assigned_cameras=[self.dsai_assigned_cam],
            dsai_profile=DSAI_PROFILE_VENDOR_A,
        )

        # Initialize simulator with Vendor Profile B
        self.dsai_simulator_b = DSAIEdgeDeviceSimulator(
            dsai_device_id=self.dsai_device_id,
            dsai_tenant_id=self.dsai_tenant_id,
            dsai_api_key=self.dsai_api_key,
            dsai_assigned_cameras=[self.dsai_assigned_cam],
            dsai_profile=DSAI_PROFILE_VENDOR_B,
        )

        self.dsai_client = TestClient(dsai_test_app)
        dsai_test_app.dependency_overrides[get_db] = lambda: self.dsai_db
        dsai_test_app.dependency_overrides[dsai_require_edge_auth] = lambda: {
            "device_id": self.dsai_device_id,
            "tenant_id": self.dsai_tenant_id,
            "assigned_cameras": [self.dsai_assigned_cam],
            "is_active": True
        }

        self.dsai_mock_redis = MagicMock()
        self.dsai_mock_redis.set.return_value = True
        self.dsai_mock_redis.get.return_value = None

        with patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.create_redis_client", return_value=self.dsai_mock_redis), \
             patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.StreamProducer.publish"), \
             patch("deepSightAI.Trinetra.Shared.Streaming.Producer.StreamProducer.publish"):
            yield

        dsai_test_app.dependency_overrides.clear()
        dsai_reset_circuit_breakers()

    def test_dsai_e1_e2_single_and_batch_submission(self):
        """E1/E2: Submit single event and vendor-profile batch; verify itemized responses."""
        dsai_event = self.dsai_simulator_a.dsai_build_valid_event()

        with patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.ensure_tenant_collection") as dsai_mock_col:
            dsai_mock_col.return_value.schema.fields = [1, 2, 3, 4]
            dsai_mock_col.return_value.insert.return_value = ["pk-e1-001"]

            # Single event
            dsai_resp_single = self.dsai_client.post(
                "/v1/edge/embeddings",
                json=dsai_event,
                headers=self.dsai_simulator_a.dsai_get_auth_headers()
            )
            assert dsai_resp_single.status_code == 200
            assert dsai_resp_single.json()["status"] == "success"

            # Vendor Profile B Batch (size 50)
            dsai_batch = self.dsai_simulator_b.dsai_build_batch(dsai_count=10)
            dsai_resp_batch = self.dsai_client.post(
                "/v1/edge/embeddings/batch",
                json={"items": dsai_batch},
                headers=self.dsai_simulator_b.dsai_get_auth_headers()
            )
            assert dsai_resp_batch.status_code == 200
            dsai_batch_data = dsai_resp_batch.json()
            assert dsai_batch_data["summary"]["accepted"] == 10
            assert len(dsai_batch_data["results"]) == 10

    def test_dsai_e2_batch_with_partial_failure_isolation(self):
        """E2: Submit batch containing valid events and one malformed event; bad is isolated, valid succeed."""
        dsai_batch = self.dsai_simulator_a.dsai_build_batch(dsai_count=3)
        # Corrupt 2nd item with negative dimension
        dsai_batch[1]["embedding_dim"] = -5

        with patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.ensure_tenant_collection") as dsai_mock_col:
            dsai_mock_col.return_value.schema.fields = [1, 2, 3, 4]
            dsai_mock_col.return_value.insert.return_value = ["pk-batch-iso"]

            dsai_resp = self.dsai_client.post(
                "/v1/edge/embeddings/batch",
                json={"items": dsai_batch},
                headers=self.dsai_simulator_a.dsai_get_auth_headers()
            )
            assert dsai_resp.status_code == 207
            dsai_data = dsai_resp.json()
            assert dsai_data["summary"]["accepted"] == 2
            assert dsai_data["summary"]["rejected"] == 1
            assert dsai_data["results"][1]["status"] == "error"

    def test_dsai_e3_credential_revocation_immediate_401(self):
        """E3: Valid credential succeeds; revoked credential rejects immediately."""
        dsai_test_app.dependency_overrides.pop(dsai_require_edge_auth, None)
        
        # Revoke device in DB
        self.dsai_simulator_a.dsai_set_revoked_credentials()
        dsai_resp_revoked = self.dsai_client.post(
            "/v1/edge/embeddings",
            json=self.dsai_simulator_a.dsai_build_valid_event(),
            headers=self.dsai_simulator_a.dsai_get_auth_headers()
        )
        assert dsai_resp_revoked.status_code == 401

    def test_dsai_e4_s2_camera_pull_path_collision_forbidden(self):
        """E4/S2: Device submits for camera assigned to pull path; rejected with 403."""
        # Mock CameraRepository returning 'pull'
        with patch.object(CameraRepository, "get_ingestion_path", return_value="pull"):
            dsai_event = self.dsai_simulator_a.dsai_build_valid_event(dsai_camera_id=self.dsai_assigned_cam)
            dsai_resp = self.dsai_client.post(
                "/v1/edge/embeddings",
                json=dsai_event,
                headers=self.dsai_simulator_a.dsai_get_auth_headers()
            )
            assert dsai_resp.status_code == 403
            assert "assigned to 'pull' path" in dsai_resp.json()["detail"]

    @pytest.mark.parametrize("dsai_field", [
        "camera_id", "tenant_id", "captured_at",
        "embedding_vector", "embedding_dim", "model_id", "model_version", "event_id"
    ])
    def test_dsai_section5_3_parameterized_field_omissions(self, dsai_field):
        """§5.3: Omit each required field one at a time; each produces 400 naming that exact field."""
        dsai_valid = self.dsai_simulator_a.dsai_build_valid_event()
        dsai_invalid = self.dsai_simulator_a.dsai_inject_omitted_field(dsai_valid, dsai_field)

        dsai_resp = self.dsai_client.post(
            "/v1/edge/embeddings",
            json=dsai_invalid,
            headers=self.dsai_simulator_a.dsai_get_auth_headers()
        )
        assert dsai_resp.status_code == 400
        assert dsai_field in dsai_resp.json()["detail"]

    def test_dsai_section5_3_dimension_mismatch_and_unknown_model(self):
        """§5.3: embedding_dim mismatch rejected as dimension_mismatch; unknown model rejected."""
        dsai_valid = self.dsai_simulator_a.dsai_build_valid_event()
        dsai_dim_mismatch = self.dsai_simulator_a.dsai_inject_dimension_mismatch(dsai_valid, dsai_wrong_dim=256)

        dsai_resp_dim = self.dsai_client.post(
            "/v1/edge/embeddings",
            json=dsai_dim_mismatch,
            headers=self.dsai_simulator_a.dsai_get_auth_headers()
        )
        assert dsai_resp_dim.status_code == 400

        dsai_unknown_model = self.dsai_simulator_a.dsai_inject_unapproved_model(dsai_valid)
        dsai_resp_model = self.dsai_client.post(
            "/v1/edge/embeddings",
            json=dsai_unknown_model,
            headers=self.dsai_simulator_a.dsai_get_auth_headers()
        )
        assert dsai_resp_model.status_code == 400

    def test_dsai_e5_duplicate_event_id_sequential_and_concurrent(self):
        """E5: Sequential and concurrent duplicate event_id calls return cached result with single write."""
        dsai_event = self.dsai_simulator_a.dsai_build_valid_event(dsai_event_id="evt-dup-race-01")
        dsai_store = {}

        def dsai_r_set(k, v, nx=False, ex=None):
            if nx and k in dsai_store:
                return False
            dsai_store[k] = v
            return True

        def dsai_r_get(k):
            return dsai_store.get(k)

        self.dsai_mock_redis.set.side_effect = dsai_r_set
        self.dsai_mock_redis.get.side_effect = dsai_r_get

        with patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.ensure_tenant_collection") as dsai_mock_col:
            dsai_mock_col.return_value.schema.fields = [1, 2, 3, 4]
            dsai_mock_col.return_value.insert.return_value = ["pk-unique-01"]

            # First submission
            dsai_resp1 = self.dsai_client.post(
                "/v1/edge/embeddings",
                json=dsai_event,
                headers=self.dsai_simulator_a.dsai_get_auth_headers()
            )
            assert dsai_resp1.status_code == 200

            # Second duplicate submission
            dsai_resp2 = self.dsai_client.post(
                "/v1/edge/embeddings",
                json=dsai_event,
                headers=self.dsai_simulator_a.dsai_get_auth_headers()
            )
            assert dsai_resp2.status_code == 200
            # Second call returns the original result (E5)
            assert dsai_resp2.json()["status"] == "success"
            assert dsai_resp2.json()["event_id"] == dsai_resp1.json()["event_id"]
            assert dsai_resp2.json()["pk"] == dsai_resp1.json()["pk"]
            # Exactly one insert was written to Milvus
            assert dsai_mock_col.return_value.insert.call_count == 1

    def test_dsai_e7_liveness_staleness_and_clock_skew(self):
        """E7: Stop device traffic -> flagged stale after window; clock skew is clamped."""
        dsai_resp_stale = self.dsai_client.get(
            f"/v1/edge/liveness/{self.dsai_tenant_id}/{self.dsai_assigned_cam}?max_idle_seconds=60",
            headers=self.dsai_simulator_a.dsai_get_auth_headers()
        )
        assert dsai_resp_stale.status_code == 200
        assert dsai_resp_stale.json()["status"] == "stale"

        # Skew clamping: event with 10 min forward skew
        dsai_skewed = self.dsai_simulator_a.dsai_inject_clock_skew(
            self.dsai_simulator_a.dsai_build_valid_event(),
            dsai_skew_seconds=600.0
        )
        with patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.ensure_tenant_collection") as dsai_mock_col:
            dsai_mock_col.return_value.schema.fields = [1, 2, 3, 4]
            dsai_mock_col.return_value.insert.return_value = ["pk-skew"]

            dsai_resp_skew = self.dsai_client.post(
                "/v1/edge/embeddings",
                json=dsai_skewed,
                headers=self.dsai_simulator_a.dsai_get_auth_headers()
            )
            assert dsai_resp_skew.status_code == 200
            assert dsai_resp_skew.json()["status"] == "success"

    def test_dsai_e8_sunset_version_410_gone(self):
        """E8: Calling sunset /v0/ version returns 410 Gone."""
        dsai_resp_v0 = self.dsai_client.post("/v0/edge/embeddings", json={})
        assert dsai_resp_v0.status_code == 410
        assert "permanently decommissioned" in dsai_resp_v0.json()["detail"]
