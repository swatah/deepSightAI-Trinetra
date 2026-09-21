"""
Phase 4 Test Suite: Production Hardening, Resilience & CI Gating.
Covers:
  - AUTH-45, AUTH-46, AUTH-47: Fail-Closed Authentication & RBAC Scopes
  - AUTH-50: Tenant Scoping from Auth Context across Postgres & Milvus
  - REL-52: Sanitized Error Handlers & Stack Trace Shielding
  - REL-54: X-Request-ID Generation & Propagation (HTTP and Redis)
  - REL-57, REL-58, REL-59: Resilient Consumer, Bounded Retries, DLQ Routing, and Idle-Message Sweep
  - REL-60: Connection Retry Wrappers for Milvus & PostgreSQL
  - REL-63: Health and Readiness Probes across Services
  - REL-64: Prometheus Scrapeable /metrics Endpoints
  - Fault Injection: Storage/Redis mid-flight disconnect resilience
  - DEP-71: Alembic Multi-Tenant Migration Tool
"""

import os
import re
import sys
import time
import uuid
import json
from datetime import datetime, timezone
from typing import Dict, Any, List
from unittest.mock import MagicMock, patch

from deepSightAI.Trinetra.Shared.Streaming.Consumer import Message

import pytest
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import OperationalError

from deepSightAI.Trinetra.Shared.DB import (
    Base,
    dsai_connect_db_with_retry,
    dsai_get_tenant_schemas,
    get_tenant_connection,
)
from deepSightAI.Trinetra.Shared.Milvus import dsai_connect_milvus_with_retry
from deepSightAI.Trinetra.Shared.Streaming.Schema import (
    DeadLetterQueueEvent,
    FrameReadyEvent,
    ObjectDetectedEvent,
)
from deepSightAI.Trinetra.Shared.Streaming.Producer import StreamProducer
from deepSightAI.Trinetra.Shared.Streaming.dsai_resilient_consumer import (
    ResilientStreamConsumer,
)
from deepSightAI.Trinetra.Shared.dsai_middleware import (
    RequestIDMiddleware,
    dsai_require_auth,
    dsai_get_auth_context,
)
from deepSightAI.Trinetra.Shared.dsai_error_handlers import (
    dsai_register_error_handlers,
    register_error_handlers,
)
from deepSightAI.Trinetra.Shared.dsai_metrics import (
    dsai_record_detection,
    dsai_record_processing_latency,
    dsai_record_query_latency,
    dsai_record_alert_match,
    dsai_set_dlq_depth,
    dsai_generate_metrics_response,
)
from deepSightAI.Trinetra.AuthService.rbac import require_permission
from deepSightAI.Trinetra.AuthService.auth_service import (
    app as dsai_auth_app,
    create_access_token,
)
from deepSightAI.Trinetra.AuditService.audit_service import app as dsai_audit_app
from deepSightAI.Trinetra.ServerAndExtractor.main_api import app as dsai_main_api_app
from deepSightAI.Trinetra.SearchService.main import app as dsai_search_app
from deepSightAI.Trinetra.VisionProcessingService.dsai_vps import app as dsai_vps_app
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_service import (
    app as dsai_watchlist_app,
)
from deepSightAI.Trinetra.VisionProcessingService.dsai_consumer import (
    VisionProcessingConsumer,
)
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_consumer import (
    WatchlistMatcherConsumer,
)
import importlib.util

dsai_migrate_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "dsai_migrate.py")
dsai_migrate_spec = importlib.util.spec_from_file_location("dsai_migrate", dsai_migrate_path)
dsai_migrate_tool = importlib.util.module_from_spec(dsai_migrate_spec)
dsai_migrate_spec.loader.exec_module(dsai_migrate_tool)


# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def dsai_test_app():
    """Build a minimal test FastAPI app with RequestIDMiddleware and error handlers."""
    dsai_app = FastAPI()
    dsai_app.add_middleware(RequestIDMiddleware)
    dsai_register_error_handlers(dsai_app)

    @dsai_app.get("/health")
    def dsai_health():
        return {"status": "ok"}

    @dsai_app.get("/ready")
    def dsai_ready():
        return {"status": "ready"}

    @dsai_app.get("/metrics")
    def dsai_metrics():
        return dsai_generate_metrics_response()

    @dsai_app.get("/unhandled-error")
    def dsai_unhandled():
        raise RuntimeError("Internal database secret: password123 leaked in raw trace")

    @dsai_app.get("/http-error")
    def dsai_http_err():
        raise HTTPException(status_code=400, detail="Invalid request parameters provided")

    @dsai_app.get("/protected")
    def dsai_protected(user=Depends(dsai_require_auth)):
        return {"message": "protected-ok", "user": user}

    @dsai_app.get("/admin-only")
    def dsai_admin_only(
        user=Depends(dsai_require_auth),
        perm=Depends(require_permission("cameras:write")),
    ):
        return {"message": "admin-action-permitted"}

    return dsai_app


@pytest.fixture
def dsai_client(dsai_test_app):
    """Starlette TestClient for the test FastAPI app."""
    return TestClient(dsai_test_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# AUTH-45, AUTH-46, AUTH-47: Fail-Closed Auth & RBAC
# ---------------------------------------------------------------------------

class TestFailClosedAuthAndRBAC:
    """Test fail-closed authentication and RBAC scope enforcement."""

    def test_unauthenticated_request_rejected(self, dsai_client):
        """Requests without Authorization header must return 401 Unauthorized."""
        dsai_resp = dsai_client.get("/protected")
        assert dsai_resp.status_code == 401
        dsai_data = dsai_resp.json()
        assert "detail" in dsai_data
        assert "Authorization" in dsai_data["detail"] or "required" in dsai_data["detail"].lower()

    def test_invalid_bearer_token_rejected(self, dsai_client):
        """Malformed or invalid tokens must fail closed with 401."""
        dsai_resp = dsai_client.get(
            "/protected",
            headers={"Authorization": "Bearer not-a-valid-jwt-token"},
        )
        assert dsai_resp.status_code == 401

    def test_authenticated_token_accepted(self, dsai_client):
        """Valid bearer token succeeds and extracts user payload."""
        dsai_token = create_access_token(
            data={"sub": "agent-user", "tenant_id": "tenant-alpha", "roles": ["viewer"]}
        )
        dsai_resp = dsai_client.get(
            "/protected",
            headers={"Authorization": f"Bearer {dsai_token}"},
        )
        assert dsai_resp.status_code == 200
        assert dsai_resp.json()["message"] == "protected-ok"

    def test_rbac_permission_enforcement_forbidden(self, dsai_client):
        """User missing the required permission receives 403 Forbidden."""
        dsai_token = create_access_token(
            data={
                "sub": "regular-user",
                "tenant_id": "tenant-alpha",
                "roles": ["viewer"],
                "permissions": ["cameras:read"],
            }
        )
        dsai_resp = dsai_client.get(
            "/admin-only",
            headers={"Authorization": f"Bearer {dsai_token}"},
        )
        assert dsai_resp.status_code == 403
        assert "Missing required permission" in dsai_resp.json()["detail"]

    def test_rbac_admin_role_bypasses_permission(self, dsai_client):
        """User with admin role is granted access to all scoped endpoints."""
        dsai_token = create_access_token(
            data={
                "sub": "admin-user",
                "tenant_id": "tenant-alpha",
                "roles": ["admin"],
            }
        )
        dsai_resp = dsai_client.get(
            "/admin-only",
            headers={"Authorization": f"Bearer {dsai_token}"},
        )
        assert dsai_resp.status_code == 200
        assert dsai_resp.json()["message"] == "admin-action-permitted"

    def test_rbac_explicit_permission_granted(self, dsai_client):
        """User with exact permission granted is permitted."""
        dsai_token = create_access_token(
            data={
                "sub": "operator-user",
                "tenant_id": "tenant-alpha",
                "roles": ["operator"],
                "permissions": ["cameras:write"],
            }
        )
        dsai_resp = dsai_client.get(
            "/admin-only",
            headers={"Authorization": f"Bearer {dsai_token}"},
        )
        assert dsai_resp.status_code == 200

    def test_probes_bypass_authentication(self, dsai_client):
        """Health, readiness, and metrics endpoints must be unauthenticated."""
        assert dsai_client.get("/health").status_code == 200
        assert dsai_client.get("/ready").status_code == 200
        assert dsai_client.get("/metrics").status_code == 200

    def test_all_services_expose_health_probes(self):
        """All 6 core service apps respond to /health without authentication."""
        dsai_apps = [
            ("MainAPI", dsai_main_api_app),
            ("SearchService", dsai_search_app),
            ("VisionProcessing", dsai_vps_app),
            ("WatchlistMatcher", dsai_watchlist_app),
            ("AuthService", dsai_auth_app),
            ("AuditService", dsai_audit_app),
        ]
        for dsai_name, dsai_service_app in dsai_apps:
            dsai_svc_client = TestClient(dsai_service_app)
            dsai_resp = dsai_svc_client.get("/health")
            assert dsai_resp.status_code == 200, f"{dsai_name} /health returned {dsai_resp.status_code}"


# ---------------------------------------------------------------------------
# AUTH-50: Multi-Tenant Scoping across Postgres & Milvus
# ---------------------------------------------------------------------------

class TestTenantScopingContext:
    """Test tenant scoping and isolation across storage systems."""

    def test_auth_context_extracts_tenant_from_jwt(self):
        """dsai_get_auth_context correctly extracts tenant_id from bearer token."""
        dsai_token = create_access_token(
            data={"sub": "tenant-user", "tenant_id": "tenant_xyz"}
        )
        dsai_req = Request({
            "type": "http",
            "headers": [(b"authorization", f"Bearer {dsai_token}".encode("latin-1"))],
        })
        dsai_ctx = dsai_get_auth_context(dsai_req)
        assert dsai_ctx is not None
        assert dsai_ctx.get("tenant_id") == "tenant_xyz"

    def test_auth_context_extracts_tenant_from_header(self):
        """dsai_get_auth_context rejects unauthenticated X-Tenant-ID header alone (fail-closed, AUTH-50)."""
        dsai_req = Request({
            "type": "http",
            "headers": [(b"x-tenant-id", b"tenant_custom_42")],
        })
        dsai_ctx = dsai_get_auth_context(dsai_req)
        assert dsai_ctx == {}

    def test_auth_context_rejects_header_mismatch(self):
        """dsai_get_auth_context rejects request when X-Tenant-ID differs from token tenant."""
        dsai_token = create_access_token(
            data={"sub": "tenant-user", "tenant_id": "tenant_xyz", "roles": ["operator"]}
        )
        dsai_req = Request({
            "type": "http",
            "headers": [
                (b"authorization", f"Bearer {dsai_token}".encode("latin-1")),
                (b"x-tenant-id", b"tenant_other"),
            ],
        })
        with pytest.raises(HTTPException) as exc_info:
            dsai_get_auth_context(dsai_req)
        assert exc_info.value.status_code == 403

    def test_postgres_schema_isolation_discovery(self):
        """dsai_get_tenant_schemas returns schemas with tenant isolation."""
        dsai_mock_conn = MagicMock()
        dsai_mock_conn.execute.return_value = [("tenant_1",), ("tenant_2",)]
        dsai_schemas = dsai_get_tenant_schemas(dsai_mock_conn)
        assert "tenant_1" in dsai_schemas
        assert "tenant_2" in dsai_schemas
        assert "public" in dsai_schemas


# ---------------------------------------------------------------------------
# REL-52: Sanitized Error Handlers
# ---------------------------------------------------------------------------

class TestSanitizedErrorHandlers:
    """Test error handlers sanitize stack traces and inject request_id."""

    def test_unhandled_exception_sanitized(self, dsai_client):
        """Unhandled 500 error must not leak internal secrets or raw stack traces."""
        dsai_resp = dsai_client.get(
            "/unhandled-error",
            headers={"X-Request-ID": "test-req-sanitized-001"},
        )
        assert dsai_resp.status_code == 500
        dsai_body = dsai_resp.json()
        assert dsai_body["error"] in ("Internal Server Error", "InternalServerError")
        assert dsai_body["detail"] == "An internal server error occurred."
        assert dsai_body["request_id"] == "test-req-sanitized-001"
        # Verify no stack trace or leaked secret
        assert "password123" not in str(dsai_body)
        assert "Traceback" not in str(dsai_body)

    def test_http_exception_preserves_detail_and_request_id(self, dsai_client):
        """HTTPException retains detail message and includes request_id."""
        dsai_resp = dsai_client.get(
            "/http-error",
            headers={"X-Request-ID": "test-req-http-002"},
        )
        assert dsai_resp.status_code == 400
        dsai_body = dsai_resp.json()
        assert dsai_body["detail"] == "Invalid request parameters provided"
        assert dsai_body["request_id"] == "test-req-http-002"


# ---------------------------------------------------------------------------
# REL-54: X-Request-ID Propagation
# ---------------------------------------------------------------------------

class TestRequestIDPropagation:
    """Test end-to-end request ID generation and header propagation."""

    def test_request_id_generated_when_absent(self, dsai_client):
        """RequestIDMiddleware generates a valid UUID when client provides none."""
        dsai_resp = dsai_client.get("/health")
        assert dsai_resp.status_code == 200
        assert "x-request-id" in dsai_resp.headers
        dsai_req_id = dsai_resp.headers["x-request-id"]
        # Validate valid UUID
        assert uuid.UUID(dsai_req_id)

    def test_client_provided_request_id_preserved(self, dsai_client):
        """Client-provided X-Request-ID is echoed back in response header."""
        dsai_custom_id = "trinetra-custom-trace-999"
        dsai_resp = dsai_client.get(
            "/health",
            headers={"X-Request-ID": dsai_custom_id},
        )
        assert dsai_resp.headers.get("x-request-id") == dsai_custom_id

    def test_producer_propagates_request_id_to_event(self):
        """StreamProducer forwards x_request_id into published stream events."""
        dsai_mock_client = MagicMock()
        dsai_mock_client.xadd.return_value = "1720000000000-0"
        dsai_producer = StreamProducer(redis_client=dsai_mock_client)

        dsai_event = FrameReadyEvent(
            video_id="video-001",
            segment_id=0,
            frame_paths=["s3://bucket/frame.jpg"],
            timestamps=[0.0],
            sequence_numbers=[1],
            extractor_id="ext-01",
            bucket_name="frames",
            tenant_id="tenant-alpha",
            timestamp=datetime.now(timezone.utc),
        )
        dsai_producer.publish(
            "events:frame_ready",
            dsai_event,
            x_request_id="req-trace-propagation-888",
        )
        assert dsai_mock_client.xadd.called
        dsai_call_args = dsai_mock_client.xadd.call_args[0]
        dsai_fields = dsai_call_args[1]
        assert "correlation_id" in dsai_fields
        assert dsai_fields["correlation_id"] == "req-trace-propagation-888"


# ---------------------------------------------------------------------------
# REL-57, REL-58, REL-59: Resilient Consumer, Retries, DLQ & Idle Reclaim
# ---------------------------------------------------------------------------

class TestResilientConsumerRetryAndDLQ:
    """Test bounded retry logic, DLQ routing, and idle message recovery."""

    def test_resilient_consumer_successful_processing(self):
        """Message is processed and acknowledged on success."""
        dsai_mock_redis = MagicMock()
        dsai_consumer = ResilientStreamConsumer(
            redis_client=dsai_mock_redis,
            stream_name="test:stream",
            group_name="test-group",
            consumer_name="test-consumer",
            max_retries=3,
        )
        dsai_processed = []

        def dsai_handler(dsai_msg):
            dsai_processed.append(dsai_msg)

        dsai_msg = {
            "id": "1000-0",
            "stream": "test:stream",
            "data": {"payload": "valid-data"},
        }
        dsai_res = dsai_consumer.dsai_process_single_message(dsai_msg, dsai_handler)
        assert dsai_res is True
        assert len(dsai_processed) == 1
        dsai_mock_redis.xack.assert_called_once_with("test:stream", "test-group", "1000-0")

    def test_resilient_consumer_poison_pill_routed_to_dlq(self):
        """Message failing continuously is routed to DLQ after exhausting retries."""
        dsai_mock_redis = MagicMock()
        dsai_consumer = ResilientStreamConsumer(
            redis_client=dsai_mock_redis,
            stream_name="test:stream",
            group_name="test-group",
            consumer_name="test-consumer",
            max_retries=2,
            retry_backoff_base=0.01,
        )

        def dsai_failing_handler(dsai_msg):
            raise ValueError("Poison pill unparseable data corruption")

        dsai_msg = {
            "id": "1001-0",
            "stream": "test:stream",
            "data": {"corrupted": "bad-payload"},
        }
        # First failure: retry count reaches 1
        dsai_res1 = dsai_consumer.dsai_process_single_message(dsai_msg, dsai_failing_handler)
        assert dsai_res1 is False
        assert not dsai_mock_redis.xadd.called

        # Second failure: reaches max_retries (2) -> routed to DLQ and ACKed
        dsai_res2 = dsai_consumer.dsai_process_single_message(dsai_msg, dsai_failing_handler)
        assert dsai_res2 is False

        # Verify published to DLQ stream
        assert dsai_mock_redis.xadd.called
        dsai_xadd_stream = dsai_mock_redis.xadd.call_args[0][0]
        assert "dlq" in dsai_xadd_stream.lower()

        # Verify acknowledged to unblock consumer group
        dsai_mock_redis.xack.assert_called_once_with("test:stream", "test-group", "1001-0")

    def test_idle_message_reclaim_sweep(self):
        """Stuck messages in XPENDING are reclaimed via XCLAIM."""
        dsai_mock_redis = MagicMock()
        # Mock xpending_range to return 1 stuck message
        dsai_mock_redis.xpending_range.return_value = [
            {
                "message_id": "1002-0",
                "consumer": "crashed-worker-1",
                "time_since_delivered": 120000,  # 2 minutes idle
                "times_delivered": 1,
            }
        ]
        dsai_mock_redis.xclaim.return_value = [
            ("1002-0", {"event_type": "FrameReadyEvent", "tenant_id": "tenant-1"})
        ]

        dsai_consumer = ResilientStreamConsumer(
            redis_client=dsai_mock_redis,
            stream_name="test:stream",
            group_name="test-group",
            consumer_name="active-worker-2",
        )
        dsai_reclaimed = dsai_consumer.dsai_reclaim_idle_messages(
            dsai_min_idle_ms=60000,
            dsai_count=10,
        )
        assert len(dsai_reclaimed) == 1
        dsai_mock_redis.xclaim.assert_called_once()


# ---------------------------------------------------------------------------
# REL-60: Connection Retry Wrappers for Milvus & Postgres
# ---------------------------------------------------------------------------

class TestConnectionRetryWrappers:
    """Test connection retry wrappers for database and vector store."""

    def test_postgres_retry_recovers_after_transient_failure(self):
        """dsai_connect_db_with_retry succeeds after initial connection failures."""
        dsai_attempts = 0

        def dsai_failing_factory(url, **kwargs):
            nonlocal dsai_attempts
            dsai_attempts += 1
            if dsai_attempts < 3:
                raise OperationalError("Connection refused", {}, None)
            dsai_mock_engine = MagicMock()
            dsai_mock_conn = MagicMock()
            dsai_mock_conn.execute.return_value = MagicMock()
            dsai_mock_engine.connect.return_value.__enter__.return_value = dsai_mock_conn
            return dsai_mock_engine

        dsai_engine = dsai_connect_db_with_retry(
            "postgresql://user:pass@localhost:5432/test",
            dsai_max_attempts=4,
            dsai_initial_wait=0.01,
            dsai_engine_factory=dsai_failing_factory,
        )
        assert dsai_engine is not None
        assert dsai_attempts == 3

    def test_postgres_retry_exhausts_and_raises(self):
        """dsai_connect_db_with_retry raises OperationalError after exhausting attempts."""
        def dsai_always_fails(url, **kwargs):
            raise OperationalError("Host unreachable", {}, None)

        with pytest.raises(OperationalError):
            dsai_connect_db_with_retry(
                "postgresql://user:pass@localhost:5432/test",
                dsai_max_attempts=2,
                dsai_initial_wait=0.01,
                dsai_engine_factory=dsai_always_fails,
            )

    def test_milvus_retry_recovers_after_transient_failure(self):
        """dsai_connect_milvus_with_retry retries and succeeds."""
        dsai_attempts = 0

        def dsai_connect_mock(*args, **kwargs):
            nonlocal dsai_attempts
            dsai_attempts += 1
            if dsai_attempts < 2:
                raise RuntimeError("Milvus coordinator starting up")
            return True

        with patch("pymilvus.connections.connect", side_effect=dsai_connect_mock):
            dsai_ok = dsai_connect_milvus_with_retry(
                dsai_max_attempts=3,
                dsai_initial_wait=0.01,
            )
            assert dsai_ok is True
            assert dsai_attempts == 2


# ---------------------------------------------------------------------------
# REL-63 & REL-64: Health, Readiness & Prometheus Metrics
# ---------------------------------------------------------------------------

class TestHealthReadinessAndMetrics:
    """Test health/ready probes and Prometheus metrics generation."""

    def test_metrics_endpoint_exposition_format(self, dsai_client):
        """GET /metrics returns standard Prometheus text format."""
        dsai_record_detection(dsai_tenant_id="tenant_alpha", dsai_object_class="car")
        dsai_record_processing_latency(dsai_service="VPS", dsai_operation="detection", dsai_seconds=0.045)
        dsai_record_query_latency(dsai_endpoint="/search", dsai_tenant_id="tenant_alpha", dsai_seconds=0.012)
        dsai_record_alert_match(dsai_tenant_id="tenant_alpha", dsai_entry_type="plate", dsai_priority="high")
        dsai_set_dlq_depth(dsai_stream="trinetra:stream:dlq", dsai_depth=3)

        dsai_resp = dsai_client.get("/metrics")
        assert dsai_resp.status_code == 200
        assert "text/plain" in dsai_resp.headers["content-type"]
        dsai_text = dsai_resp.text

        assert "trinetra_processing_latency_seconds" in dsai_text
        assert "trinetra_detection_counts_total" in dsai_text
        assert "trinetra_dlq_depth" in dsai_text
        assert "trinetra_alert_matches_total" in dsai_text
        assert "trinetra_query_latency_seconds" in dsai_text

    def test_readiness_probe_contract(self, dsai_client):
        """/ready probe indicates service is ready to receive traffic."""
        dsai_resp = dsai_client.get("/ready")
        assert dsai_resp.status_code == 200
        assert dsai_resp.json()["status"] == "ready"


# ---------------------------------------------------------------------------
# Fault Injection Tests
# ---------------------------------------------------------------------------

class TestFaultInjectionResilience:
    """Test resilience under simulated transient infrastructure failures."""

    def test_transient_minio_download_failure_recovers(self):
        """Consumer gracefully retries and succeeds when MinIO recovers."""
        dsai_download_attempts = 0

        def dsai_mock_failing_download():
            nonlocal dsai_download_attempts
            dsai_download_attempts += 1
            if dsai_download_attempts == 1:
                raise ConnectionResetError("MinIO connection reset by peer")
            return "/tmp/mock_frame.jpg"

        # Simulate consumer execution with transient failure handled by retry loop
        dsai_mock_redis = MagicMock()
        dsai_consumer = ResilientStreamConsumer(
            redis_client=dsai_mock_redis,
            stream_name="events:frame_ready",
            group_name="vps-group",
            max_retries=3,
            retry_backoff_base=0.01,
        )

        def dsai_frame_handler(dsai_msg):
            dsai_path = dsai_mock_failing_download()
            return dsai_path

        dsai_msg = {
            "id": "2001-0",
            "stream": "events:frame_ready",
            "data": {"storage_path": "s3://bucket/f.jpg"},
        }
        # First attempt fails due to transient connection reset
        dsai_attempt1 = dsai_consumer.dsai_process_single_message(dsai_msg, dsai_frame_handler)
        assert dsai_attempt1 is False

        # Second attempt succeeds when MinIO connection recovers
        dsai_attempt2 = dsai_consumer.dsai_process_single_message(dsai_msg, dsai_frame_handler)
        assert dsai_attempt2 is True
        assert dsai_download_attempts == 2
        dsai_mock_redis.xack.assert_called_once()

    def test_corrupt_payload_does_not_crash_consumer_thread(self):
        """Unparseable or non-dict payloads are routed to DLQ without crashing process."""
        dsai_mock_redis = MagicMock()
        dsai_consumer = ResilientStreamConsumer(
            redis_client=dsai_mock_redis,
            stream_name="events:frame_ready",
            group_name="vps-group",
            max_retries=1,
            retry_backoff_base=0.01,
        )

        def dsai_crash_handler(dsai_msg):
            raise KeyError("Missing required field 'video_id' in malformed event")

        dsai_msg = {
            "id": "2002-0",
            "stream": "events:frame_ready",
            "data": {"completely": "broken"},
        }
        # Should not raise uncaught exception
        dsai_ok = dsai_consumer.dsai_process_single_message(dsai_msg, dsai_crash_handler)
        assert dsai_ok is False
        # Acknowledged so poison pill is cleared
        dsai_mock_redis.xack.assert_called_once()


# ---------------------------------------------------------------------------
# DEP-71: Alembic Multi-Tenant Migration Tool
# ---------------------------------------------------------------------------

class TestAlembicMigrationTool:
    """Test Alembic deployment script schema discovery and dry-run."""

    def test_discover_schemas_default(self):
        """dsai_discover_schemas discovers schemas correctly."""
        dsai_schemas = dsai_migrate_tool.dsai_discover_schemas("sqlite:///:memory:")
        assert "public" in dsai_schemas
        assert "tenant_default" in dsai_schemas

    def test_discover_schemas_targeted_tenant(self):
        """Targeting specific tenant restricts schemas list."""
        dsai_schemas = dsai_migrate_tool.dsai_discover_schemas(
            "sqlite:///:memory:",
            dsai_target_tenant="acme_corp",
        )
        assert dsai_schemas == ["tenant_acme_corp"]

    def test_migration_dry_run(self):
        """Dry-run returns success code 0 without executing schema changes."""
        dsai_code = dsai_migrate_tool.dsai_run_migrations(
            dsai_database_url="sqlite:///:memory:",
            dsai_revision="head",
            dsai_dry_run=True,
        )
        assert dsai_code == 0


# ---------------------------------------------------------------------------
# Defect Fix Verifications: Cross-Tenant Isolation, PEL Retries, Idle Sweeps
# ---------------------------------------------------------------------------

class TestCrossTenantDataIsolationDefect:
    """Verify cross-tenant data injection is rejected (Defect 1 & Defect 2)."""

    def test_dsai_validate_request_tenant_rejects_mismatch(self):
        """Cross-tenant job request is rejected with 403 Forbidden for non-admin users."""
        from deepSightAI.Trinetra.ServerAndExtractor.main_api import dsai_validate_request_tenant
        dsai_req = Request({"type": "http"})
        dsai_req.state.tenant_id = "tenant_alpha"
        dsai_req.state.user = {"tenant_id": "tenant_alpha", "roles": ["operator"]}

        with pytest.raises(HTTPException) as exc_info:
            dsai_validate_request_tenant(dsai_req, "tenant_beta")
        assert exc_info.value.status_code == 403

    def test_dsai_validate_request_tenant_allows_same_tenant(self):
        """Matching tenant claim returns the authenticated tenant ID."""
        from deepSightAI.Trinetra.ServerAndExtractor.main_api import dsai_validate_request_tenant
        dsai_req = Request({"type": "http"})
        dsai_req.state.tenant_id = "tenant_alpha"
        dsai_req.state.user = {"tenant_id": "tenant_alpha", "roles": ["operator"]}

        dsai_tenant = dsai_validate_request_tenant(dsai_req, "tenant_alpha")
        assert dsai_tenant == "tenant_alpha"

    def test_dsai_validate_request_tenant_allows_admin_override(self):
        """Admin user can dispatch cross-tenant jobs."""
        from deepSightAI.Trinetra.ServerAndExtractor.main_api import dsai_validate_request_tenant
        dsai_req = Request({"type": "http"})
        dsai_req.state.tenant_id = "system_tenant"
        dsai_req.state.user = {"tenant_id": "system_tenant", "roles": ["admin"]}

        dsai_tenant = dsai_validate_request_tenant(dsai_req, "tenant_target")
        assert dsai_tenant == "tenant_target"

    def test_dsai_validate_extractor_tenant_rejects_mismatch(self):
        """Extractor endpoint rejects forwarded job if tenant claim mismatches."""
        from deepSightAI.Trinetra.ServerAndExtractor.extractor import dsai_validate_extractor_tenant
        dsai_req = Request({"type": "http"})
        dsai_req.state.tenant_id = "tenant_alpha"
        dsai_req.state.user = {"tenant_id": "tenant_alpha", "roles": ["operator"]}

        with pytest.raises(HTTPException) as exc_info:
            dsai_validate_extractor_tenant(dsai_req, "tenant_beta")
        assert exc_info.value.status_code == 403


class TestVPSPELRetryAndDLQDefect:
    """Verify VPS consumer reads from PEL ('0') and routes poison pills to DLQ (Defect 3)."""

    def test_dsai_vps_reads_pel_first(self):
        """dsai_read_messages checks PEL '0' before reading new stream messages '>'."""
        from deepSightAI.Trinetra.VisionProcessingService.dsai_consumer import VisionProcessingConsumer
        dsai_mock_redis = MagicMock()
        dsai_mock_redis.xreadgroup.return_value = [
            ("frames", [("pel-msg-1", {"event": json.dumps({"video_id": "vid1", "segment_id": 0, "frame_paths": [], "timestamps": [], "sequence_numbers": []})})])
        ]
        dsai_mock_consumer = MagicMock()
        dsai_mock_consumer.client = dsai_mock_redis
        dsai_mock_consumer.group_name = "test-group"
        dsai_mock_consumer.consumer_id = "test-consumer"

        dsai_vps = VisionProcessingConsumer(
            dsai_stream_name="frames",
            dsai_group_name="test-group",
            dsai_consumer_id="test-consumer",
        )
        dsai_vps.consumer = dsai_mock_consumer

        dsai_msgs = dsai_vps.dsai_read_messages(dsai_count=5)
        assert len(dsai_msgs) == 1
        assert dsai_msgs[0].id == "pel-msg-1"
        dsai_mock_redis.xreadgroup.assert_called_with(
            groupname="test-group",
            consumername="test-consumer",
            streams={"frames": "0"},
            count=5,
        )

    def test_dsai_vps_poison_pill_routes_to_dlq(self):
        """Poison pill failing repeatedly in VPS loop increments retry count and routes to DLQ."""
        from deepSightAI.Trinetra.VisionProcessingService.dsai_consumer import VisionProcessingConsumer
        dsai_mock_consumer = MagicMock()
        dsai_mock_producer = MagicMock()

        dsai_vps = VisionProcessingConsumer(
            dsai_producer=dsai_mock_producer,
            dsai_stream_name="frames",
        )
        dsai_vps.consumer = dsai_mock_consumer
        dsai_vps.max_message_retries = 2

        dsai_poison_msg = Message(
            stream="frames",
            msg_id="poison-100",
            data={"event": "invalid-json-poison-pill"}
        )
        dsai_mock_consumer.read.return_value = [dsai_poison_msg]

        # Iteration 1: fails, retry count -> 1
        dsai_stop1 = MagicMock()
        dsai_stop1.is_set.side_effect = [False, True]
        dsai_vps.dsai_run_loop(dsai_stop_flag=dsai_stop1, dsai_max_iterations=1)
        assert dsai_vps.message_retry_counts.get("poison-100") == 1
        assert not dsai_mock_producer.publish.called

        # Iteration 2: fails, retry count -> 2 >= max_retries -> routed to DLQ & acked
        dsai_stop2 = MagicMock()
        dsai_stop2.is_set.side_effect = [False, True]
        dsai_vps.dsai_run_loop(dsai_stop_flag=dsai_stop2, dsai_max_iterations=1)

        assert dsai_mock_producer.publish.called
        assert dsai_mock_producer.publish.call_args[0][0] == "events:dlq"
        dsai_mock_consumer.ack.assert_called_with("frames", "poison-100")


class TestConsumerPeriodicIdleReclaimDefect:
    """Verify consumers trigger periodic idle message reclaim sweep (Defect 5/6)."""

    def test_dsai_vps_periodic_reclaim_sweep(self):
        """VPS loop triggers dsai_reclaim_idle_messages periodically."""
        from deepSightAI.Trinetra.VisionProcessingService.dsai_consumer import VisionProcessingConsumer
        dsai_vps = VisionProcessingConsumer()
        dsai_vps.consumer = MagicMock()
        dsai_vps.consumer.read.return_value = []
        dsai_reclaim_called = False

        def dsai_mock_reclaim(*args, **kwargs):
            nonlocal dsai_reclaim_called
            dsai_reclaim_called = True
            return []

        dsai_vps.dsai_reclaim_idle_messages = dsai_mock_reclaim
        dsai_stop = MagicMock()
        dsai_stop.is_set.side_effect = [False, True]

        with patch("time.time", side_effect=[0.0, 100.0, 100.0, 100.0, 100.0]):
            dsai_vps.dsai_run_loop(dsai_stop_flag=dsai_stop, dsai_max_iterations=1)

        assert dsai_reclaim_called is True
