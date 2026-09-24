"""
Backing services test environment and management fixtures (Issue #90).

Provides configuration, isolation, and reset helpers for:
- Redis Streams (frames queue, embedder-group, dedup store)
- Milvus collections
- MinIO buckets
- AuthService test tenants and edge device credentials

Adheres strictly to CODING_STANDARDS.md.
"""

import os
from typing import Generator, Any
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from deepSightAI.Trinetra.AuthService.auth_service import (
    Base,
    EdgeDevice,
    EdgeDeviceOnboardRequest,
    dsai_onboard_edge_device,
    dsai_revoke_edge_device,
    _dsai_edge_lockout_tracker,
)
from deepSightAI.Trinetra.Shared.dsai_circuit_breaker import dsai_reset_circuit_breakers
from deepSightAI.Trinetra.Shared.LoggingSetup import dsai_set_correlation_id


class DSAIBackingServicesManager:
    """Manages test lifecycle and state resets for backing services."""

    def __init__(self, dsai_redis_client=None, dsai_db_session: Session = None):
        self.dsai_redis_client = dsai_redis_client
        self.dsai_db_session = dsai_db_session

    def dsai_reset_all(self) -> None:
        """Reset all in-memory, mock, and distributed service states."""
        dsai_reset_circuit_breakers()
        dsai_set_correlation_id(None)
        with _dsai_edge_lockout_tracker as _:
            pass
        if self.dsai_redis_client is not None:
            try:
                self.dsai_redis_client.flushall()
            except Exception:
                pass


from sqlalchemy.pool import StaticPool

def dsai_setup_in_memory_auth_db() -> Session:
    """Create an isolated SQLite in-memory database initialized with AuthService models."""
    dsai_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    Base.metadata.create_all(bind=dsai_engine)
    dsai_session_cls = sessionmaker(autocommit=False, autoflush=False, bind=dsai_engine)
    return dsai_session_cls()


def dsai_provision_test_edge_device(
    dsai_db: Session,
    dsai_device_id: str,
    dsai_tenant_id: str,
    dsai_assigned_cameras: list,
    dsai_is_active: bool = True
) -> str:
    """Register a new edge device and return its raw API key token."""
    dsai_req = EdgeDeviceOnboardRequest(
        device_id=dsai_device_id,
        tenant_id=dsai_tenant_id,
        name=f"Test device {dsai_device_id}",
        assigned_cameras=dsai_assigned_cameras
    )
    dsai_res = dsai_onboard_edge_device(dsai_req=dsai_req, dsai_db=dsai_db)
    if not dsai_is_active:
        dsai_revoke_edge_device(dsai_device_id=dsai_device_id, dsai_db=dsai_db)
    return dsai_res.api_key
