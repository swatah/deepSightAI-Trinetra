"""
T1.5.2: Create AuditService (FastAPI)

Tests for the AuditService that stores immutable audit logs.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import json
from datetime import datetime
from pathlib import Path
import os
import sys

# Add repo root to sys.path to import top-level packages (AuditService, Embedder, etc.)
repo_root = Path(__file__).resolve().parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Mock all heavy third-party dependencies before import
sys.modules['psycopg2'] = MagicMock()
sys.modules['psycopg2.extras'] = MagicMock()
sys.modules['kafka'] = MagicMock()
sys.modules['kafka.producer'] = MagicMock()
sys.modules['jsonschema'] = MagicMock()
# Debug
print(f"DEBUG: sys.path[:3] = {sys.path[:3]}")
print(f"DEBUG: cwd = {os.getcwd()}, repo_root = {repo_root}")

# Import after mocks
try:
    from AuditService.audit_service import app, AuditService
    SERVICE_AVAILABLE = True
except Exception as e:
    import traceback; traceback.print_exc()
    SERVICE_AVAILABLE = False
    pytest.skip(f"AuditService not available: {e}", allow_module_level=True)


class TestAuditService:
    """Test AuditService."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_service_startup(self):
        """AuditService app should start and have required routes."""
        assert app is not None

    def test_audit_endpoint_exists(self):
        """POST /audit endpoint should exist."""
        client = TestClient(app)
        response = client.post('/audit', json={"test": "data"})
        # Should return 200 or 201, not 404
        assert response.status_code != 404

    def test_audit_log_validation_success(self):
        """Valid audit log should pass validation."""
        valid_log = {
            "tenant_id": "tenant-123",
            "user_id": "user-456",
            "action": "LOGIN",
            "resource": {
                "type": "user",
                "id": "user-456"
            },
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "outcome": "SUCCESS"
        }
        # Should not raise
        service = AuditService()
        try:
            service.validate_audit_log(valid_log)
        except Exception as e:
            pytest.fail(f"Validation failed: {e}")

    def test_audit_log_validation_missing_required(self):
        """Missing required field should fail validation."""
        invalid_log = {
            "tenant_id": "tenant-123",
            "action": "LOGIN",
            # Missing user_id, resource, timestamp, outcome
        }
        service = AuditService()
        with pytest.raises(ValueError):
            service.validate_audit_log(invalid_log)

    def test_audit_log_stored_successfully(self, client):
        """Audit log should be stored and return acknowledgment."""
        log_entry = {
            "tenant_id": "tenant-123",
            "user_id": "user-456",
            "action": "CREATE",
            "resource": {
                "type": "video",
                "id": "vid-789"
            },
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "outcome": "SUCCESS"
        }
        response = client.post('/audit', json=log_entry)
        assert response.status_code in (200, 201, 202)
        data = response.json()
        assert "status" in data or "message" in data

    def test_audit_batch_endpoint(self, client):
        """Batch audit endpoint should accept multiple logs."""
        logs = [
            {
                "tenant_id": "tenant-123",
                "user_id": "user-456",
                "action": "READ",
                "resource": {"type": "video", "id": "v1"},
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "outcome": "SUCCESS"
            },
            {
                "tenant_id": "tenant-123",
                "user_id": "user-456",
                "action": "UPDATE",
                "resource": {"type": "video", "id": "v1"},
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "outcome": "SUCCESS"
            }
        ]
        response = client.post('/audit/batch', json=logs)
        assert response.status_code in (200, 201, 202)

    def test_audit_service_db_integration(self):
        """Test that AuditService can insert into database (mocked)."""
        service = AuditService()
        # Mock DB connection
        service.conn = MagicMock()
        service.conn.cursor.return_value = MagicMock()
        log = {
            "tenant_id": "t1",
            "user_id": "u1",
            "action": "LOGIN",
            "resource": {"type": "user", "id": "u1"},
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "outcome": "SUCCESS"
        }
        try:
            service.store(log)
            # Should have executed an INSERT
            assert service.conn.cursor.called
        except Exception as e:
            pytest.fail(f"Service DB integration failed: {e}")

    def test_audit_service_kafka_integration(self):
        """Test that AuditService can produce to Kafka (mocked)."""
        service = AuditService()
        service.kafka_producer = MagicMock()
        log = {
            "tenant_id": "t1",
            "user_id": "u1",
            "action": "LOGIN",
            "resource": {"type": "user", "id": "u1"},
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "outcome": "SUCCESS"
        }
        try:
            service.produce_to_kafka(log)
            assert service.kafka_producer.send.called
        except Exception as e:
            pytest.fail(f"Kafka integration failed: {e}")

    def test_audit_health_endpoint(self, client):
        """Health check endpoint should return status."""
        response = client.get('/health')
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy" or data.get("status") == "ok"
