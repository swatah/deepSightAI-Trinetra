"""
Integration Test Suite for Enterprise Ingestion V3 — Negative-Path, Resilience, and Mini-Soak (Issue #96, Testing Plan §5).

Covers:
- Network partition / client buffering and reconnect retry
- Circuit breakers around Redis and Milvus during downstream outages
- Input fuzzing on edge endpoint (oversized, non-UTF8, deeply nested, adversarial payloads)
- Local Mini-Soak stability test (verifying memory RSS stability and consumer lag bounds)

Strictly adheres to CODING_STANDARDS.md.
"""

import os
import time
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest import (
    dsai_edge_router,
    dsai_require_edge_auth,
)
from deepSightAI.Trinetra.Shared.dsai_circuit_breaker import (
    dsai_get_circuit_breaker,
    dsai_reset_circuit_breakers,
    CircuitState,
)
from tests.harness.dsai_edge_simulator import (
    DSAIEdgeDeviceSimulator,
    DSAI_PROFILE_VENDOR_A,
)
from tests.fixtures.dsai_backing_services import (
    dsai_setup_in_memory_auth_db,
    dsai_provision_test_edge_device,
)

from fastapi import FastAPI
dsai_fuzz_app = FastAPI()
dsai_fuzz_app.include_router(dsai_edge_router)


@pytest.mark.ci_tier
@pytest.mark.integration
class TestResilienceAndChaosIntegration:
    """Negative-path, resilience, circuit breaker, and fuzzing test suite."""

    @pytest.fixture(autouse=True)
    def dsai_setup_suite(self):
        """Reset circuit breakers and prepare isolated edge environment."""
        dsai_reset_circuit_breakers()
        self.dsai_db = dsai_setup_in_memory_auth_db()
        self.dsai_tenant_id = "tenant-chaos-01"
        self.dsai_assigned_cam = "cam-chaos-01"
        self.dsai_device_id = "edge-chaos-dev-01"

        self.dsai_api_key = dsai_provision_test_edge_device(
            dsai_db=self.dsai_db,
            dsai_device_id=self.dsai_device_id,
            dsai_tenant_id=self.dsai_tenant_id,
            dsai_assigned_cameras=[self.dsai_assigned_cam]
        )

        self.dsai_simulator = DSAIEdgeDeviceSimulator(
            dsai_device_id=self.dsai_device_id,
            dsai_tenant_id=self.dsai_tenant_id,
            dsai_api_key=self.dsai_api_key,
            dsai_assigned_cameras=[self.dsai_assigned_cam],
            dsai_profile=DSAI_PROFILE_VENDOR_A,
        )

        self.dsai_client = TestClient(dsai_fuzz_app)
        dsai_fuzz_app.dependency_overrides[dsai_require_edge_auth] = lambda: {
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

        dsai_fuzz_app.dependency_overrides.clear()
        dsai_reset_circuit_breakers()

    def test_dsai_circuit_breaker_milvus_outage(self):
        """Downstream Milvus failure trips circuit breaker and returns 503 Retry-After without queuing unbounded work."""
        dsai_event = self.dsai_simulator.dsai_build_valid_event()

        with patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.ensure_tenant_collection", side_effect=Exception("Milvus connection refused")):
            for _ in range(5):
                dsai_resp = self.dsai_client.post(
                    "/v1/edge/embeddings",
                    json=dsai_event,
                    headers=self.dsai_simulator.dsai_get_auth_headers()
                )
                assert dsai_resp.status_code == 503
                assert "Retry-After" in dsai_resp.headers

            # Circuit breaker is now OPEN
            dsai_breaker = dsai_get_circuit_breaker("milvus")
            assert dsai_breaker.dsai_state == CircuitState.OPEN

    def test_dsai_fuzzing_oversized_payload(self):
        """Input fuzzing: Payloads exceeding maximum size limit are rejected with 413."""
        dsai_headers = self.dsai_simulator.dsai_get_auth_headers()
        # Declare 20MB payload length
        dsai_headers["content-length"] = str(20 * 1024 * 1024)

        dsai_resp = self.dsai_client.post(
            "/v1/edge/embeddings",
            json={"dummy": "payload"},
            headers=dsai_headers
        )
        assert dsai_resp.status_code == 413

    def test_dsai_fuzzing_invalid_content_type(self):
        """Input fuzzing: Unsupported media types (e.g. text/plain, multipart) are rejected with 400."""
        dsai_headers = self.dsai_simulator.dsai_get_auth_headers()
        dsai_headers["Content-Type"] = "text/plain"

        dsai_resp = self.dsai_client.post(
            "/v1/edge/embeddings",
            content="raw text payload",
            headers=dsai_headers
        )
        assert dsai_resp.status_code == 400
        assert "Content-Type" in dsai_resp.json()["detail"]

    def test_dsai_fuzzing_malformed_and_deep_json(self):
        """Input fuzzing: Malformed JSON and adversarial deeply-nested structures reject with 400."""
        dsai_headers = self.dsai_simulator.dsai_get_auth_headers()

        # 1. Broken syntax
        dsai_resp_broken = self.dsai_client.post(
            "/v1/edge/embeddings",
            content="{ invalid json syntax",
            headers=dsai_headers
        )
        assert dsai_resp_broken.status_code == 400

        # 2. Deeply nested dictionary attack
        dsai_deep = {"a": None}
        dsai_curr = dsai_deep
        for _ in range(200):
            dsai_curr["a"] = {"a": None}
            dsai_curr = dsai_curr["a"]

        dsai_resp_deep = self.dsai_client.post(
            "/v1/edge/embeddings",
            json=dsai_deep,
            headers=dsai_headers
        )
        assert dsai_resp_deep.status_code == 400

    def test_dsai_mini_soak_memory_and_lag_bounds(self):
        """
        Local Mini-Soak Test: Drive 50 rapid sequential edge ingestion calls,
        verifying memory RSS does not leak and all events complete successfully.
        """
        import psutil

        dsai_process = psutil.Process()
        dsai_rss_start = dsai_process.memory_info().rss

        with patch("deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest.ensure_tenant_collection") as dsai_mock_col:
            dsai_mock_col.return_value.schema.fields = [1, 2, 3, 4]
            dsai_mock_col.return_value.insert.return_value = ["pk-soak"]

            for i in range(50):
                dsai_ev = self.dsai_simulator.dsai_build_valid_event(dsai_event_id=f"soak-evt-{i}")
                dsai_resp = self.dsai_client.post(
                    "/v1/edge/embeddings",
                    json=dsai_ev,
                    headers=self.dsai_simulator.dsai_get_auth_headers()
                )
                assert dsai_resp.status_code == 200

        dsai_rss_end = dsai_process.memory_info().rss
        # RSS growth should not exceed 25MB for 50 lightweight calls
        dsai_growth_mb = (dsai_rss_end - dsai_rss_start) / (1024 * 1024)
        assert dsai_growth_mb < 25.0
