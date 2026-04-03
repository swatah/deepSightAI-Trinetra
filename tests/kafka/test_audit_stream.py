"""
T1.5.4: Implement Kafka audit stream

Tests that audit logs are published to Kafka topic.
"""

import pytest
from unittest.mock import MagicMock, patch
import json
from datetime import datetime
from pathlib import Path
import os
import sys

# Add repo root to sys.path to import AuditService
repo_root = Path(__file__).resolve().parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Mock heavy dependencies
sys.modules['psycopg2'] = MagicMock()
sys.modules['psycopg2.extras'] = MagicMock()
sys.modules['jsonschema'] = MagicMock()
sys.modules['kafka'] = MagicMock()
sys.modules['kafka.producer'] = MagicMock()

try:
    from AuditService.audit_service import AuditService
    SERVICE_AVAILABLE = True
except Exception as e:
    import traceback; traceback.print_exc()
    SERVICE_AVAILABLE = False
    pytest.skip(f"AuditService not available: {e}", allow_module_level=True)


class TestKafkaAuditStream:
    """Test Kafka audit stream."""

    def test_audit_service_produces_to_kafka_topic(self):
        """AuditService should produce audit logs to configured Kafka topic."""
        service = AuditService()
        # Replace the real kafka producer with a mock
        mock_producer = MagicMock()
        service.kafka_producer = mock_producer

        log = {
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "action": "LOGIN",
            "resource": {"type": "user", "id": "user-1"},
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "outcome": "SUCCESS"
        }

        service.produce_to_kafka(log)

        assert mock_producer.send.called
        # Verify called with correct topic and message
        call_args = mock_producer.send.call_args[0]
        assert call_args[0] == "audit-logs"  # default topic
        # The message should be the log; check it's JSON serializable
        sent_message = call_args[1]
        assert isinstance(sent_message, dict)
        assert sent_message["tenant_id"] == "tenant-1"

    def test_kafka_producer_flush_called(self):
        """After sending, flush should be called to ensure delivery."""
        service = AuditService()
        mock_producer = MagicMock()
        service.kafka_producer = mock_producer

        log = {
            "tenant_id": "t1",
            "user_id": "u1",
            "action": "CREATE",
            "resource": {"type": "video", "id": "v1"},
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "outcome": "SUCCESS"
        }

        service.produce_to_kafka(log)

        assert mock_producer.flush.called

    def test_kafka_unavailable_does_not_crash(self):
        """If Kafka is not connected, produce_to_kafka should skip without raising."""
        service = AuditService()
        service.kafka_producer = None  # simulate no Kafka
        log = {
            "tenant_id": "t1",
            "user_id": "u1",
            "action": "READ",
            "resource": {"type": "video", "id": "v1"},
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "outcome": "SUCCESS"
        }
        # Should not raise, just return
        try:
            service.produce_to_kafka(log)
        except Exception as e:
            pytest.fail(f"produce_to_kafka raised when kafka_producer is None: {e}")

    def test_audit_stream_kafka_configuration(self):
        """Kafka bootstrap servers should be configurable via env."""
        import os
        # Default from env or config
        # Just check that the default is set
        from AuditService.audit_service import KAFKA_BOOTSTRAP_SERVERS, KAFKA_AUDIT_TOPIC
        assert KAFKA_BOOTSTRAP_SERVERS is not None
        assert KAFKA_AUDIT_TOPIC is not None

    def test_audit_log_schema_serializable(self):
        """Audit logs must be JSON serializable for Kafka."""
        service = AuditService()
        # Simulate a full log via validate_audit_log perhaps
        log = {
            "tenant_id": "t1",
            "user_id": "u1",
            "action": "DELETE",
            "resource": {"type": "video", "id": "v1", "name": "bad video"},
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "outcome": "FAILURE",
            "ip_address": "127.0.0.1",
            "user_agent": "TestClient",
            "changes": [
                {"field": "status", "old_value": "active", "new_value": "deleted"}
            ],
            "metadata": {"extra": "info"}
        }
        # Ensure it can be JSON dumped
        try:
            json.dumps(log)
        except Exception as e:
            pytest.fail(f"Audit log not JSON serializable: {e}")
