"""
Phase 3 Test Suite: Live Watchlist & Real-Time Alerting Engine (WL-26 to WL-34, DM-7b, UI-89, UI-90).
"""

import os
import re
import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from deepSightAI.Trinetra.Shared.DB import Base
from deepSightAI.Trinetra.Shared.Streaming.Schema import (
    ObjectDetectedEvent,
    WatchlistAlertEvent,
)
from deepSightAI.Trinetra.Shared.Repositories.WatchlistRepository import (
    WatchlistRepository,
    AlertRepository,
    WatchlistEntry,
    Alert,
)
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_matcher import (
    dsai_normalize_plate,
    dsai_match_plate,
    dsai_cosine_similarity,
    dsai_match_reid,
    AlertFloodSafeguard,
)
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_cache import (
    WatchlistCache,
    WatchlistEntryCacheItem,
)
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_consumer import (
    WatchlistMatcherConsumer,
)
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_service import app as dsai_matcher_app
from deepSightAI.Trinetra.Shared.Errors import StorageError


@pytest.fixture
def test_db_session():
    """Create an isolated in-memory SQLite session with Base metadata and StaticPool."""
    dsai_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    Base.metadata.create_all(bind=dsai_engine)
    dsai_session_factory = sessionmaker(bind=dsai_engine, autocommit=False, autoflush=False)
    WatchlistRepository.Session = dsai_session_factory
    AlertRepository.Session = dsai_session_factory
    yield dsai_session_factory
    WatchlistRepository.Session = None
    AlertRepository.Session = None



# =====================================================================
# 1. DM-7b: DATABASE SCHEMA & REPOSITORIES
# =====================================================================

class TestDM7bPostgresSchemaAndRepository:
    """DM-7b: Migration script and repository persistence for watchlist entries and alerts."""

    def test_dsai_migration_script_structure(self):
        """Verify 0003 migration defines watchlist_entries and alerts tables."""
        dsai_mig_path = "migrations/versions/0003_trinetra_watchlist_alerts.py"
        assert os.path.exists(dsai_mig_path), "Migration 0003 must exist"
        with open(dsai_mig_path, "r") as dsai_f:
            dsai_content = dsai_f.read()

        assert "watchlist_entries" in dsai_content
        assert "alerts" in dsai_content
        assert "ix_watchlist_entries_tenant_id" in dsai_content
        assert "ix_alerts_watchlist_entry_id" in dsai_content
        assert "reid_embedding_json" in dsai_content
        assert "down_revision" in dsai_content and "'0002'" in dsai_content

    def test_dsai_watchlist_repository_crud_and_tenant_isolation(self, test_db_session, monkeypatch):
        """Verify WatchlistRepository full CRUD and strict multi-tenant isolation (WL-27)."""
        dsai_repo_a = WatchlistRepository("tenant_alpha")
        dsai_repo_b = WatchlistRepository("tenant_bravo")
        monkeypatch.setattr(dsai_repo_a, "Session", test_db_session)
        monkeypatch.setattr(dsai_repo_b, "Session", test_db_session)

        # 1. Create entry for Tenant Alpha
        dsai_entry_a = dsai_repo_a.dsai_create(
            entry_type="plate",
            label="Stolen Black SUV",
            created_by="officer_alice",
            plate_text_norm="KA01MJ5000",
            priority="critical"
        )
        assert dsai_entry_a.id is not None
        assert dsai_entry_a.plate_text_norm == "KA01MJ5000"
        assert dsai_entry_a.active is True

        # 2. Verify Tenant Bravo CANNOT see Tenant Alpha's entry (cross-tenant isolation)
        dsai_entries_b = dsai_repo_b.dsai_list_entries()
        assert len(dsai_entries_b) == 0
        assert dsai_repo_b.dsai_get_by_id(dsai_entry_a.id) is None

        # 3. Fetch by ID and update for Tenant Alpha
        dsai_fetched = dsai_repo_a.dsai_get_by_id(dsai_entry_a.id)
        assert dsai_fetched is not None
        assert dsai_fetched.label == "Stolen Black SUV"

        dsai_updated = dsai_repo_a.dsai_update(
            entry_id=dsai_entry_a.id,
            label="Recovered SUV",
            priority="low"
        )
        assert dsai_updated.label == "Recovered SUV"
        assert dsai_updated.priority == "low"

        # 4. Set active = False
        dsai_repo_a.dsai_set_active(dsai_entry_a.id, False)
        dsai_active = dsai_repo_a.dsai_get_active_entries()
        assert len(dsai_active) == 0

        # 5. Delete entry
        assert dsai_repo_a.dsai_delete(dsai_entry_a.id) is True
        assert dsai_repo_a.dsai_get_by_id(dsai_entry_a.id) is None

    def test_dsai_alert_repository_crud_acknowledgment_and_audit(self, test_db_session, monkeypatch):
        """Verify AlertRepository CRUD, unacknowledged filtering, acknowledgment, and audit trail (WL-31, WL-33)."""
        dsai_alert_repo_a = AlertRepository("tenant_alpha")
        dsai_alert_repo_b = AlertRepository("tenant_bravo")
        monkeypatch.setattr(dsai_alert_repo_a, "Session", test_db_session)
        monkeypatch.setattr(dsai_alert_repo_b, "Session", test_db_session)

        # 1. Create alert for Tenant Alpha
        dsai_alert = dsai_alert_repo_a.dsai_create(
            watchlist_entry_id=101,
            video_object_pk="obj_test_001",
            camera_id="cam_north_gate",
            match_score=0.98,
            crop_path="crops/tenant_alpha/cam_north/obj_test_001.jpg"
        )
        assert dsai_alert.id is not None
        assert dsai_alert.acknowledged is False
        assert dsai_alert.acknowledged_by is None
        assert dsai_alert.acknowledged_at is None

        # 2. Cross-tenant isolation: Tenant Bravo cannot see it
        assert len(dsai_alert_repo_b.dsai_poll_alerts(since_id=0)) == 0
        assert dsai_alert_repo_b.dsai_get_by_id(dsai_alert.id) is None
        assert dsai_alert_repo_b.dsai_acknowledge(dsai_alert.id, "hacker") is None

        # 3. Poll alerts for Tenant Alpha
        dsai_polled = dsai_alert_repo_a.dsai_poll_alerts(since_id=0)
        assert len(dsai_polled) == 1
        assert dsai_polled[0].id == dsai_alert.id

        # Polling with since_id equal to or greater than alert id returns empty
        assert len(dsai_alert_repo_a.dsai_poll_alerts(since_id=dsai_alert.id)) == 0

        # 4. Acknowledge alert with audit trail (WL-33)
        dsai_ack_time_before = datetime.utcnow() - timedelta(seconds=1)
        dsai_acked = dsai_alert_repo_a.dsai_acknowledge(
            alert_id=dsai_alert.id,
            acknowledged_by="operator_bob"
        )
        assert dsai_acked is not None
        assert dsai_acked.acknowledged is True
        assert dsai_acked.acknowledged_by == "operator_bob"
        assert dsai_acked.acknowledged_at is not None
        assert dsai_acked.acknowledged_at >= dsai_ack_time_before

        # 5. List unacknowledged is now empty
        assert len(dsai_alert_repo_a.dsai_list_unacknowledged()) == 0

    def test_dsai_alert_repository_idempotent_deduplication(self, test_db_session, monkeypatch):
        """Verify AlertRepository deduplicates alerts for the same (tenant, entry_id, video_object_pk)."""
        dsai_alert_repo = AlertRepository("tenant_dedup")
        monkeypatch.setattr(dsai_alert_repo, "Session", test_db_session)

        # 1. First alert insertion
        dsai_alert_1 = dsai_alert_repo.dsai_create(
            watchlist_entry_id=42,
            video_object_pk="obj_dup_999",
            camera_id="cam_gate_1",
            match_score=0.85,
            crop_path="crops/tenant_dedup/crop_1.jpg"
        )
        assert dsai_alert_1.id is not None
        assert dsai_alert_1.match_score == 0.85

        # 2. Duplicate alert insertion on consumer retry / redelivery
        dsai_alert_2 = dsai_alert_repo.dsai_create(
            watchlist_entry_id=42,
            video_object_pk="obj_dup_999",
            camera_id="cam_gate_1",
            match_score=0.95,
            crop_path="crops/tenant_dedup/crop_1.jpg"
        )
        # Should return the same record ID without inserting a second row
        assert dsai_alert_2.id == dsai_alert_1.id
        assert dsai_alert_2.match_score == 0.95

        # Verify only 1 row exists in database for this tenant
        dsai_all = dsai_alert_repo.dsai_poll_alerts(since_id=0)
        assert len(dsai_all) == 1


# =====================================================================
# 2. WL-28: PLATE MATCH LOGIC (EXACT & FUZZY)
# =====================================================================

class TestWL28PlateMatchLogic:
    """WL-28: Normalized exact match and fuzzy trigram comparison."""

    def test_dsai_normalize_plate(self):
        """Verify plate text normalization strips non-alphanumeric and capitalizes."""
        assert dsai_normalize_plate("mh-12 ab 1234") == "MH12AB1234"
        assert dsai_normalize_plate("  DL  01-C 9999. ") == "DL01C9999"
        assert dsai_normalize_plate(None) == ""
        assert dsai_normalize_plate("") == ""

    def test_dsai_match_plate_exact(self):
        """Exact match yields score 1.0 regardless of punctuation differences."""
        dsai_match, dsai_score = dsai_match_plate("MH12 AB 1234", "mh-12ab1234")
        assert dsai_match is True
        assert dsai_score == 1.0

    def test_dsai_match_plate_fuzzy_ocr_confusion(self):
        """Fuzzy matching recognizes OCR confusion (O vs 0, 8 vs B, I vs 1)."""
        # Character 'O' vs '0'
        dsai_match_ocr, dsai_score_ocr = dsai_match_plate("KA01AB1234", "KAO1AB1234", dsai_threshold=0.85)
        assert dsai_match_ocr is True
        assert dsai_score_ocr >= 0.88

        # 1-char difference in long plate satisfies threshold >= 0.65
        dsai_match_fuzzy, dsai_score_fuzzy = dsai_match_plate("MH12AB1234", "MH12AB1235", dsai_threshold=0.65)
        assert dsai_match_fuzzy is True
        assert dsai_score_fuzzy >= 0.65

    def test_dsai_match_plate_non_matching(self):
        """Completely different plates are rejected."""
        dsai_match, dsai_score = dsai_match_plate("MH12AB1234", "DL08XY9999", dsai_threshold=0.85)
        assert dsai_match is False
        assert dsai_score < 0.5


# =====================================================================
# 3. WL-29: RE-ID EMBEDDING COSINE SIMILARITY MATCHER
# =====================================================================

class TestWL29ReIDCosineSimilarityMatcher:
    """WL-29: Re-ID cosine similarity matcher against reference vectors."""

    def test_dsai_cosine_similarity_edge_cases(self):
        """Verify cosine similarity mathematical correctness."""
        # Identical vectors
        assert pytest.approx(dsai_cosine_similarity([1.0, 0.0], [1.0, 0.0]), 0.0001) == 1.0
        # Orthogonal vectors
        assert pytest.approx(dsai_cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0001) == 0.0
        # Opposite vectors
        assert pytest.approx(dsai_cosine_similarity([1.0, 0.0], [-1.0, 0.0]), 0.0001) == -1.0
        # Zero or None vectors
        assert dsai_cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
        assert dsai_cosine_similarity(None, [1.0, 1.0]) == 0.0
        assert dsai_cosine_similarity([1.0], [1.0, 2.0]) == 0.0  # length mismatch

    def test_dsai_match_reid_vectors(self):
        """Verify match_reid evaluates similarity against threshold."""
        dsai_ref_vec = [0.1] * 256
        # Highly similar vector
        dsai_det_close = [0.1 + (0.005 if i % 2 == 0 else -0.005) for i in range(256)]
        dsai_match, dsai_score = dsai_match_reid(dsai_det_close, dsai_ref_vec, dsai_threshold=0.75)
        assert dsai_match is True
        assert dsai_score > 0.95

        # Orthogonal / distant vector
        dsai_det_distant = [1.0 if i == 0 else 0.0 for i in range(256)]
        dsai_match_dist, dsai_score_dist = dsai_match_reid(dsai_det_distant, dsai_ref_vec, dsai_threshold=0.75)
        assert dsai_match_dist is False
        assert dsai_score_dist < 0.75


# =====================================================================
# 4. WL-30: IN-MEMORY REFERENCE CACHE & REFRESH
# =====================================================================

class TestWL30WatchlistReferenceCache:
    """WL-30: In-memory cache with expiration filtering and change-triggered refresh."""

    def test_dsai_cache_expiration_and_invalidation(self, test_db_session, monkeypatch):
        """Verify cache filters expired entries and refreshes on invalidation."""
        dsai_repo = WatchlistRepository("tenant_cache_test")
        monkeypatch.setattr(dsai_repo, "Session", test_db_session)

        # Create active unexpired entry
        dsai_e1 = dsai_repo.dsai_create(
            entry_type="plate",
            label="Active Target",
            created_by="admin",
            plate_text_norm="HR26DK8392",
            expires_at=datetime.utcnow() + timedelta(days=7)
        )
        # Create already expired entry
        dsai_e2 = dsai_repo.dsai_create(
            entry_type="plate",
            label="Expired Target",
            created_by="admin",
            plate_text_norm="DL01AA0000",
            expires_at=datetime.utcnow() - timedelta(hours=1)
        )

        dsai_cache = WatchlistCache(dsai_ttl_seconds=60.0)
        # Mock repository instantiation in cache
        monkeypatch.setattr(
            "deepSightAI.Trinetra.WatchlistMatcherService.dsai_cache.WatchlistRepository",
            lambda t: dsai_repo
        )

        dsai_entries = dsai_cache.dsai_get_active_entries("tenant_cache_test")
        assert len(dsai_entries) == 1
        assert dsai_entries[0].dsai_id == dsai_e1.id
        assert dsai_entries[0].dsai_plate_text_norm == "HR26DK8392"

        # Change-triggered invalidation
        dsai_e3 = dsai_repo.dsai_create(
            entry_type="plate",
            label="New Target",
            created_by="admin",
            plate_text_norm="UP16ZZ1111"
        )
        dsai_cache.dsai_invalidate("tenant_cache_test")
        dsai_refreshed = dsai_cache.dsai_get_active_entries("tenant_cache_test")
        assert len(dsai_refreshed) == 2


# =====================================================================
# 5. WL-34: ALERT FLOOD SAFEGUARD & AUTO-DISABLE
# =====================================================================

class TestWL34AlertFloodSafeguard:
    """WL-34: Rate-limiting duplicate camera alerts and auto-disabling flood spam."""

    def test_dsai_camera_cooldown_rate_limiting(self):
        """Duplicate alerts on the same camera within cooldown are suppressed."""
        dsai_safeguard = AlertFloodSafeguard(
            dsai_cooldown_seconds=30.0,
            dsai_flood_threshold=10,
            dsai_window_seconds=60.0
        )
        dsai_now = time.time()

        # First alert: not suppressed
        dsai_sup1, _ = dsai_safeguard.dsai_should_suppress("t1", 1, "cam_01", dsai_now=dsai_now)
        assert dsai_sup1 is False
        dsai_safeguard.dsai_record_alert("t1", 1, "cam_01", dsai_now=dsai_now)

        # 5 seconds later on SAME camera: suppressed by cooldown
        dsai_sup2, dsai_reason2 = dsai_safeguard.dsai_should_suppress("t1", 1, "cam_01", dsai_now=dsai_now + 5.0)
        assert dsai_sup2 is True
        assert dsai_reason2 == "cooldown_rate_limit"

        # 5 seconds later on DIFFERENT camera: allowed
        dsai_sup3, _ = dsai_safeguard.dsai_should_suppress("t1", 1, "cam_02", dsai_now=dsai_now + 5.0)
        assert dsai_sup3 is False

        # 35 seconds later on original camera: cooldown expired, allowed
        dsai_sup4, _ = dsai_safeguard.dsai_should_suppress("t1", 1, "cam_01", dsai_now=dsai_now + 35.0)
        assert dsai_sup4 is False

    def test_dsai_alert_flood_auto_disable(self):
        """Exceeding flood threshold triggers auto-disable safeguard (WL-34)."""
        dsai_safeguard = AlertFloodSafeguard(
            dsai_cooldown_seconds=0.1,
            dsai_flood_threshold=5,
            dsai_window_seconds=60.0,
            dsai_auto_disable=True
        )
        dsai_now = time.time()

        # Generate 5 alerts
        for i in range(5):
            dsai_safeguard.dsai_record_alert("t1", 42, f"cam_{i}", dsai_now=dsai_now + i)

        # 6th alert checks flood threshold -> auto-disabled
        dsai_sup, dsai_reason = dsai_safeguard.dsai_should_suppress("t1", 42, "cam_99", dsai_now=dsai_now + 6)
        assert dsai_sup is True
        assert dsai_reason == "auto_disabled_flood"

        # Re-enabling entry allows subsequent alerts
        dsai_safeguard.dsai_enable_entry("t1", 42)
        dsai_sup_after, _ = dsai_safeguard.dsai_should_suppress("t1", 42, "cam_new", dsai_now=dsai_now + 65)
        assert dsai_sup_after is False


# =====================================================================
# 6. WL-26 & WL-31: WATCHLIST MATCHER CONSUMER INTEGRATION
# =====================================================================

class TestWL26andWL31WatchlistMatcherConsumer:
    """WL-26 & WL-31: Consumer matching, durable alert insertion, and event emission."""

    def test_dsai_consumer_processes_plate_match_and_emits_event(self, test_db_session, monkeypatch):
        """On plate match, alert is inserted into PostgreSQL and WatchlistAlertEvent emitted."""
        dsai_repo = WatchlistRepository("tenant_stream_test")
        monkeypatch.setattr(dsai_repo, "Session", test_db_session)
        dsai_entry = dsai_repo.dsai_create(
            entry_type="plate",
            label="BOLO Stolen Truck",
            created_by="officer_dan",
            plate_text_norm="DL01XY1234",
            priority="high"
        )

        # Setup mock producer and cache
        dsai_mock_producer = MagicMock()
        dsai_cache = WatchlistCache()
        monkeypatch.setattr(
            "deepSightAI.Trinetra.WatchlistMatcherService.dsai_cache.WatchlistRepository",
            lambda t: dsai_repo
        )
        monkeypatch.setattr(
            "deepSightAI.Trinetra.WatchlistMatcherService.dsai_consumer.AlertRepository",
            lambda t: AlertRepository(t)
        )
        monkeypatch.setattr(AlertRepository, "Session", test_db_session)

        dsai_consumer = WatchlistMatcherConsumer(
            dsai_config={"alerts_stream": "events:watchlist_alerts"},
            dsai_cache=dsai_cache,
            dsai_producer=dsai_mock_producer
        )

        # Matching event
        dsai_event = ObjectDetectedEvent(
            video_object_pk="obj_vps_1001",
            tenant_id="tenant_stream_test",
            camera_id="cam_toll_01",
            video_id="vid_live_feed",
            frame_timestamp=14.5,
            frame_path="frames/test/14.5.jpg",
            crop_path="crops/test/1001.jpg",
            object_class="vehicle",
            confidence=0.92,
            has_plate_read=True,
            plate_number="DL01XY1234"
        )

        dsai_alerts = dsai_consumer.dsai_process_event(dsai_event)
        assert len(dsai_alerts) == 1
        assert dsai_alerts[0].watchlist_entry_id == dsai_entry.id
        assert dsai_alerts[0].match_score == 1.0
        assert dsai_alerts[0].camera_id == "cam_toll_01"

        # Verify producer published WatchlistAlertEvent (WL-31)
        dsai_mock_producer.publish.assert_called_once()
        dsai_call_stream, dsai_call_event = dsai_mock_producer.publish.call_args[0]
        assert dsai_call_stream == "events:watchlist_alerts"
        assert isinstance(dsai_call_event, WatchlistAlertEvent)
        assert dsai_call_event.video_object_pk == "obj_vps_1001"

        # Verify database alert row committed durably
        dsai_alert_repo = AlertRepository("tenant_stream_test")
        dsai_db_alerts = dsai_alert_repo.dsai_poll_alerts(since_id=0)
        assert len(dsai_db_alerts) == 1
        assert dsai_db_alerts[0].video_object_pk == "obj_vps_1001"
        assert dsai_db_alerts[0].acknowledged is False

    def test_dsai_consumer_processes_reid_match(self, test_db_session, monkeypatch):
        """On person Re-ID cosine similarity match, alert is generated."""
        dsai_target_emb = [0.05] * 256
        dsai_repo = WatchlistRepository("tenant_reid_test")
        monkeypatch.setattr(dsai_repo, "Session", test_db_session)
        dsai_entry = dsai_repo.dsai_create(
            entry_type="person_reid",
            label="Suspect Re-ID BOLO",
            created_by="officer_dan",
            reid_embedding=dsai_target_emb,
            priority="critical"
        )

        dsai_mock_producer = MagicMock()
        dsai_cache = WatchlistCache()
        monkeypatch.setattr(
            "deepSightAI.Trinetra.WatchlistMatcherService.dsai_cache.WatchlistRepository",
            lambda t: dsai_repo
        )
        monkeypatch.setattr(
            "deepSightAI.Trinetra.WatchlistMatcherService.dsai_consumer.AlertRepository",
            lambda t: AlertRepository(t)
        )
        monkeypatch.setattr(AlertRepository, "Session", test_db_session)

        dsai_consumer = WatchlistMatcherConsumer(
            dsai_cache=dsai_cache,
            dsai_producer=dsai_mock_producer
        )

        # Detection event with similar embedding
        dsai_det_emb = [0.05 + (0.001 if i % 2 == 0 else -0.001) for i in range(256)]
        dsai_event = ObjectDetectedEvent(
            video_object_pk="obj_person_2002",
            tenant_id="tenant_reid_test",
            camera_id="cam_lobby",
            video_id="vid_lobby_01",
            frame_timestamp=82.0,
            frame_path="frames/test/82.0.jpg",
            object_class="person",
            confidence=0.89,
            reid_embedding=dsai_det_emb
        )

        dsai_alerts = dsai_consumer.dsai_process_event(dsai_event)
        assert len(dsai_alerts) == 1
        assert dsai_alerts[0].watchlist_entry_id == dsai_entry.id
        assert dsai_alerts[0].match_score > 0.90

    def test_dsai_consumer_db_failure_raises_storage_error_preventing_ack(self, monkeypatch):
        """Database commit failure raises StorageError so message is NOT acknowledged."""
        dsai_cache = MagicMock()
        dsai_cache.dsai_get_active_entries.return_value = [
            WatchlistEntryCacheItem(
                dsai_id=99,
                dsai_tenant_id="t1",
                dsai_entry_type="plate",
                dsai_plate_text_norm="MH12AB1234",
                dsai_reid_reference_pk=None,
                dsai_reid_embedding=None,
                dsai_label="Test BOLO",
                dsai_priority="medium",
                dsai_expires_at=None,
                dsai_created_at=datetime.utcnow()
            )
        ]

        # Mock AlertRepository to raise database error
        dsai_mock_alert_repo = MagicMock()
        dsai_mock_alert_repo.dsai_create.side_effect = Exception("DB Connection Lost")
        monkeypatch.setattr(
            "deepSightAI.Trinetra.WatchlistMatcherService.dsai_consumer.AlertRepository",
            lambda t: dsai_mock_alert_repo
        )

        dsai_consumer = WatchlistMatcherConsumer(dsai_cache=dsai_cache)
        dsai_event = ObjectDetectedEvent(
            video_object_pk="obj_fail_1",
            tenant_id="t1",
            camera_id="cam_01",
            video_id="vid_1",
            frame_timestamp=1.0,
            frame_path="f.jpg",
            object_class="vehicle",
            confidence=0.9,
            has_plate_read=True,
            plate_number="MH12AB1234"
        )

        with pytest.raises(StorageError):
            dsai_consumer.dsai_process_event(dsai_event)

    def test_dsai_consumer_bounded_retry_and_dlq(self):
        """Consumer tracks retry counts per message and routes to DLQ upon reaching max_retries (REL-57)."""
        dsai_mock_consumer = MagicMock()
        dsai_mock_producer = MagicMock()

        dsai_msg = MagicMock()
        dsai_msg.id = "1690000000002-0"
        dsai_msg.data = {
            "video_object_pk": "obj_bad_poison",
            "tenant_id": "tenant_retry_test",
            "camera_id": "cam_retry",
            "video_id": "vid_retry",
            "frame_timestamp": 5.0,
            "frame_path": "f.jpg",
            "object_class": "vehicle",
            "confidence": 0.9,
            "has_plate_read": True,
            "plate_number": "MH12AB1234"
        }
        dsai_mock_consumer.read.return_value = [dsai_msg]

        dsai_consumer = WatchlistMatcherConsumer(
            dsai_config={"max_retries": 2, "dlq_stream": "events:dlq"},
            dsai_producer=dsai_mock_producer,
            dsai_consumer=dsai_mock_consumer
        )

        # Mock process_event to fail
        dsai_consumer.dsai_process_event = MagicMock(side_effect=Exception("Database lock timeout"))

        # Batch 1: attempt 1 / 2
        dsai_consumer.dsai_consume_batch(dsai_count=1)
        assert dsai_consumer.dsai_retry_counts.get("1690000000002-0") == 1
        assert not dsai_mock_producer.publish.called
        assert not dsai_mock_consumer.ack.called

        # Batch 2: attempt 2 / 2 (reaches max_retries -> DLQ + ack)
        dsai_consumer.dsai_consume_batch(dsai_count=1)
        assert "1690000000002-0" not in dsai_consumer.dsai_retry_counts
        assert dsai_mock_producer.publish.called
        dsai_pub_stream, dsai_pub_payload = dsai_mock_producer.publish.call_args[0]
        assert dsai_pub_stream == "events:dlq"
        assert dsai_pub_payload["message_id"] == "1690000000002-0"
        assert "Database lock timeout" in dsai_pub_payload["error"]
        assert dsai_mock_consumer.ack.called

    def test_dsai_consumer_retry_under_threshold_leaves_unacked(self):
        """Failures under max_retries are not sent to DLQ and remain unacknowledged (REL-57)."""
        dsai_mock_consumer = MagicMock()
        dsai_mock_producer = MagicMock()

        dsai_msg = MagicMock()
        dsai_msg.id = "1690000000003-0"
        dsai_msg.data = {
            "video_object_pk": "obj_transient_err",
            "tenant_id": "tenant_retry_test",
            "camera_id": "cam_transient",
            "video_id": "vid_transient",
            "frame_timestamp": 2.0,
            "frame_path": "f.jpg",
            "object_class": "person",
            "confidence": 0.8
        }
        dsai_mock_consumer.read.return_value = [dsai_msg]

        dsai_consumer = WatchlistMatcherConsumer(
            dsai_config={"max_retries": 3, "dlq_stream": "events:dlq"},
            dsai_producer=dsai_mock_producer,
            dsai_consumer=dsai_mock_consumer
        )
        dsai_consumer.dsai_process_event = MagicMock(side_effect=Exception("Transient error"))

        dsai_consumer.dsai_consume_batch(dsai_count=1)
        assert dsai_consumer.dsai_retry_counts.get("1690000000003-0") == 1
        assert not dsai_mock_producer.publish.called
        assert not dsai_mock_consumer.ack.called


# =====================================================================
# 7. WL-27, WL-32, WL-33: WATCHLIST & ALERTS REST API
# =====================================================================

class TestWL27andWL32WatchlistAPI:
    """WL-27, WL-32, WL-33: FastAPI endpoints for Watchlist CRUD, Alerts polling/SSE, and acknowledgment."""

    @pytest.fixture
    def dsai_client(self, test_db_session, monkeypatch):
        monkeypatch.setattr(WatchlistRepository, "Session", test_db_session)
        monkeypatch.setattr(AlertRepository, "Session", test_db_session)
        return TestClient(dsai_matcher_app)

    def test_dsai_watchlist_unauthenticated_returns_401(self, dsai_client):
        """Unauthenticated requests return 401."""
        dsai_resp = dsai_client.post("/watchlist", json={"entry_type": "plate", "label": "test"})
        assert dsai_resp.status_code == 401

    def test_dsai_watchlist_permission_gated_returns_403(self, dsai_client):
        """User missing 'watchlist:write' permission receives 403."""
        from deepSightAI.Trinetra.Shared.Middleware import require_auth
        # User has only 'watchlist:read' permission
        dsai_matcher_app.dependency_overrides[require_auth] = lambda: {
            "sub": "viewer_user",
            "tenant_id": "tenant_api_test",
            "roles": [],
            "permissions": ["watchlist:read"]
        }

        dsai_resp = dsai_client.post("/watchlist", json={
            "entry_type": "plate",
            "label": "Unauthorized target",
            "plate_text": "DL01AA1111"
        })
        assert dsai_resp.status_code == 403
        dsai_matcher_app.dependency_overrides.clear()

    def test_dsai_watchlist_crud_lifecycle_with_permission(self, dsai_client):
        """Authorized user with 'watchlist:write' performs complete CRUD lifecycle (WL-27)."""
        from deepSightAI.Trinetra.Shared.Middleware import require_auth
        dsai_matcher_app.dependency_overrides[require_auth] = lambda: {
            "sub": "analyst_carol",
            "tenant_id": "tenant_api_crud",
            "roles": [],
            "permissions": ["watchlist:write"]
        }

        # 1. Create Plate Entry
        dsai_create_resp = dsai_client.post("/watchlist", json={
            "entry_type": "plate",
            "label": "Stolen Gold Honda",
            "plate_text": "MH 12 AB 9876",
            "priority": "critical"
        })
        assert dsai_create_resp.status_code == 201
        dsai_data = dsai_create_resp.json()
        assert dsai_data["id"] > 0
        assert dsai_data["plate_text_norm"] == "MH12AB9876"
        assert dsai_data["priority"] == "critical"
        dsai_entry_id = dsai_data["id"]

        # 2. Get Single Entry
        dsai_get_resp = dsai_client.get(f"/watchlist/{dsai_entry_id}")
        assert dsai_get_resp.status_code == 200
        assert dsai_get_resp.json()["label"] == "Stolen Gold Honda"

        # 3. List Entries
        dsai_list_resp = dsai_client.get("/watchlist")
        assert dsai_list_resp.status_code == 200
        assert len(dsai_list_resp.json()) == 1

        # 4. Update Entry
        dsai_patch_resp = dsai_client.patch(f"/watchlist/{dsai_entry_id}", json={
            "label": "Recovered Honda",
            "priority": "low"
        })
        assert dsai_patch_resp.status_code == 200
        assert dsai_patch_resp.json()["label"] == "Recovered Honda"
        assert dsai_patch_resp.json()["priority"] == "low"

        # 5. Delete Entry
        dsai_del_resp = dsai_client.delete(f"/watchlist/{dsai_entry_id}")
        assert dsai_del_resp.status_code == 200
        assert dsai_del_resp.json()["status"] == "deleted"

        # 6. Verify 404 after delete
        assert dsai_client.get(f"/watchlist/{dsai_entry_id}").status_code == 404

        dsai_matcher_app.dependency_overrides.clear()

    def test_dsai_alerts_poll_and_acknowledge_audit_trail(self, dsai_client):
        """Verify GET /alerts/poll and PATCH /alerts/{id}/acknowledge recording operator audit trail (WL-32, WL-33)."""
        from deepSightAI.Trinetra.Shared.Middleware import require_auth
        dsai_matcher_app.dependency_overrides[require_auth] = lambda: {
            "sub": "operator_sarah",
            "tenant_id": "tenant_alert_test",
            "roles": [],
            "permissions": ["alerts:read", "alerts:acknowledge"]
        }

        # Seed an alert via AlertRepository
        dsai_repo = AlertRepository("tenant_alert_test")
        dsai_seeded_alert = dsai_repo.dsai_create(
            watchlist_entry_id=88,
            video_object_pk="pk_alert_555",
            camera_id="cam_junction_4",
            match_score=0.96,
            crop_path="crops/tenant_alert_test/crop_555.jpg"
        )

        # 1. Poll alerts
        dsai_poll_resp = dsai_client.get("/alerts/poll?since_id=0")
        assert dsai_poll_resp.status_code == 200
        dsai_alerts = dsai_poll_resp.json()
        assert len(dsai_alerts) == 1
        assert dsai_alerts[0]["id"] == dsai_seeded_alert.id
        assert dsai_alerts[0]["acknowledged"] is False

        # 2. Acknowledge alert (WL-32, WL-33)
        dsai_ack_resp = dsai_client.patch(f"/alerts/{dsai_seeded_alert.id}/acknowledge")
        assert dsai_ack_resp.status_code == 200
        dsai_ack_data = dsai_ack_resp.json()
        assert dsai_ack_data["acknowledged"] is True
        assert dsai_ack_data["acknowledged_by"] == "operator_sarah"
        assert dsai_ack_data["acknowledged_at"] is not None

        # 3. Verify polling unacknowledged_only now excludes this alert
        dsai_unack_resp = dsai_client.get("/alerts/poll?since_id=0&unacknowledged_only=true")
        assert dsai_unack_resp.status_code == 200
        assert len(dsai_unack_resp.json()) == 0

        dsai_matcher_app.dependency_overrides.clear()

    def test_dsai_alerts_sse_stream(self, dsai_client):
        """Verify GET /alerts/stream establishes SSE text/event-stream connection (WL-32)."""
        from deepSightAI.Trinetra.Shared.Middleware import require_auth
        dsai_matcher_app.dependency_overrides[require_auth] = lambda: {
            "sub": "operator_stream",
            "tenant_id": "tenant_sse_test",
            "roles": [],
            "permissions": ["alerts:read"]
        }

        dsai_stream_resp = dsai_client.get("/alerts/stream?max_events=1")
        assert dsai_stream_resp.status_code == 200
        assert "text/event-stream" in dsai_stream_resp.headers["content-type"]
        assert ": connected" in dsai_stream_resp.text

        dsai_matcher_app.dependency_overrides.clear()

    def test_dsai_watchlist_read_without_permission_returns_403(self, dsai_client):
        """User missing 'watchlist:read' permission receives 403 on GET /watchlist (Plan item 47)."""
        from deepSightAI.Trinetra.Shared.Middleware import require_auth
        dsai_matcher_app.dependency_overrides[require_auth] = lambda: {
            "sub": "alert_only_user",
            "tenant_id": "tenant_rbac_test",
            "roles": [],
            "permissions": ["alerts:read"]
        }

        dsai_resp = dsai_client.get("/watchlist")
        assert dsai_resp.status_code == 403
        assert "watchlist:read" in dsai_resp.json()["detail"]

        dsai_get_resp = dsai_client.get("/watchlist/1")
        assert dsai_get_resp.status_code == 403

        dsai_matcher_app.dependency_overrides.clear()

    def test_dsai_alerts_read_without_permission_returns_403(self, dsai_client):
        """User missing 'alerts:read' permission receives 403 on alerts polling and stream (Plan item 47)."""
        from deepSightAI.Trinetra.Shared.Middleware import require_auth
        dsai_matcher_app.dependency_overrides[require_auth] = lambda: {
            "sub": "watchlist_only_user",
            "tenant_id": "tenant_rbac_test",
            "roles": [],
            "permissions": ["watchlist:read"]
        }

        dsai_poll_resp = dsai_client.get("/alerts/poll")
        assert dsai_poll_resp.status_code == 403
        assert "alerts:read" in dsai_poll_resp.json()["detail"]

        dsai_stream_resp = dsai_client.get("/alerts/stream")
        assert dsai_stream_resp.status_code == 403
        assert "alerts:read" in dsai_stream_resp.json()["detail"]

        dsai_matcher_app.dependency_overrides.clear()

    def test_dsai_alerts_acknowledge_without_permission_returns_403(self, dsai_client):
        """User missing 'alerts:acknowledge' permission receives 403 on acknowledge (Plan item 47)."""
        from deepSightAI.Trinetra.Shared.Middleware import require_auth
        dsai_matcher_app.dependency_overrides[require_auth] = lambda: {
            "sub": "viewer_user",
            "tenant_id": "tenant_rbac_test",
            "roles": [],
            "permissions": ["alerts:read"]
        }

        dsai_ack_resp = dsai_client.patch("/alerts/1/acknowledge")
        assert dsai_ack_resp.status_code == 403
        assert "alerts:acknowledge" in dsai_ack_resp.json()["detail"]

        dsai_matcher_app.dependency_overrides.clear()

    def test_dsai_sse_redis_pubsub_broadcast(self, monkeypatch):
        """Verify dsai_broadcast_alert_sse publishes to Redis Pub/Sub channels (WL-32 cross-process)."""
        from deepSightAI.Trinetra.WatchlistMatcherService.dsai_consumer import dsai_broadcast_alert_sse

        dsai_mock_redis = MagicMock()
        monkeypatch.setattr(
            "deepSightAI.Trinetra.WatchlistMatcherService.dsai_consumer.create_redis_client",
            lambda: dsai_mock_redis
        )

        dsai_alert_payload = {
            "alert_id": 77,
            "tenant_id": "tenant_redis_sse",
            "watchlist_entry_id": 10,
            "video_object_pk": "pk_cross_proc_1",
            "camera_id": "cam_cross_1",
            "match_score": 0.99
        }

        dsai_broadcast_alert_sse(dsai_alert_payload)

        # Verified Redis Pub/Sub publish calls
        assert dsai_mock_redis.publish.call_count == 2
        dsai_calls = [c[0] for c in dsai_mock_redis.publish.call_args_list]
        assert ("channel:alerts:tenant_redis_sse", json.dumps(dsai_alert_payload)) in dsai_calls
        assert ("channel:alerts:broadcast", json.dumps(dsai_alert_payload)) in dsai_calls




# =====================================================================
# 8. UI-89 & UI-90: STREAMLIT UI CONTRACT
# =====================================================================

class TestUI89andUI90UIIntegration:
    """UI-89 & UI-90: Streamlit UI Watchlist Management and Live Alerts contracts."""

    def test_dsai_ui_watchlist_and_alerts_tabs_contract(self):
        """Verify ui.py defines Watchlist Management and Live Alerts tabs with required controls."""
        with open("deepSightAI/Trinetra/UI/ui.py", "r") as dsai_f:
            dsai_ui_code = dsai_f.read()

        # UI-89 Watchlist Management
        assert "tab_watchlist" in dsai_ui_code
        assert "Watchlists" in dsai_ui_code
        assert "watchlist:write" in dsai_ui_code
        assert "/watchlist" in dsai_ui_code
        assert "form_add_watchlist" in dsai_ui_code

        # UI-90 Live Alerts Panel
        assert "tab_alerts" in dsai_ui_code
        assert "Live Alerts" in dsai_ui_code
        assert "/alerts/poll" in dsai_ui_code
        assert "/alerts/" in dsai_ui_code and "/acknowledge" in dsai_ui_code
        assert "Auto-poll" in dsai_ui_code
        assert "Acknowledge" in dsai_ui_code
