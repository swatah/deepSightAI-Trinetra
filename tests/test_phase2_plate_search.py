"""
Phase 2 Verification Tests (VP-18, VP-19, DM-7, VP-21, SR-38, UI-86, TEST-81).

Comprehensive test suite verifying Phase 2 License Plate Recognition (LPR) & Relational Search:
- VP-18: PP-Vehicle plate model as law_enforcement/lpr.py plugin
- VP-19 & TEST-81: Real plate-read accuracy regression test harness
- DM-7: PostgreSQL trinetra_plates schema and plate_reads table with pg_trgm GIN index
- VP-21: Vehicle detection with plate inserts plate_reads with unique video_object_pk, sets plate_candidate_id and has_plate_read in Milvus
- SR-38: POST /search/plate supporting exact and trigram similarity fuzzy search with OCR-confusion ranking
- UI-86: Plate Search tab with exact/fuzzy toggle
"""

import os
import sys
import json
import re
import numpy as np
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, ANY
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# --- CANONICAL IMPORTS ---
from deepSightAI.Trinetra.Shared.DB import Base
from deepSightAI.Trinetra.Shared.Errors import (
    TrinetraError,
    ValidationError,
    MilvusError,
    AuthenticationError,
    PermissionDeniedError,
    StorageError,
)
from deepSightAI.Trinetra.Shared.Milvus import (
    ensure_vehicle_collection,
    get_vehicle_collection_name,
)
from deepSightAI.Trinetra.Shared.Streaming.Schema import FrameReadyEvent, ObjectDetectedEvent
from deepSightAI.Trinetra.Shared.Repositories.PlateRepository import (
    PlateRead,
    PlateRepository,
    dsai_trigram_similarity,
)
from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_lpr import (
    LPRPlugin,
    dsai_create_sample_plate_image,
)
from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_plugin_loader import PluginLoader
from deepSightAI.Trinetra.VisionProcessingService.dsai_consumer import VisionProcessingConsumer
from deepSightAI.Trinetra.Embedder.models.plugins.law_enforcement.lpr import LPRPlugin as LegacyLPRPlugin
from deepSightAI.Trinetra.SearchService.main import (
    app as dsai_search_app,
    PlateSearchRequest,
    SearchResult,
    dsai_require_search_read,
    require_auth,
)


from sqlalchemy.pool import StaticPool

@pytest.fixture
def dsai_test_db_session():
    """Create an isolated in-memory SQLite session with Base metadata and StaticPool."""
    dsai_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    Base.metadata.create_all(bind=dsai_engine)
    dsai_session_factory = sessionmaker(bind=dsai_engine, autocommit=False, autoflush=False)
    PlateRepository.Session = dsai_session_factory
    yield dsai_session_factory
    PlateRepository.Session = None


@pytest.fixture
def dsai_search_client():
    """Create FastAPI test client for SearchService."""
    return TestClient(dsai_search_app)


# =====================================================================
# 1. VP-18: LPR PLUGIN AND OPENVINO ARCHITECTURE
# =====================================================================

class TestVP18LPRPlugin:
    """VP-18: PP-Vehicle plate model as law_enforcement/lpr.py plugin."""

    def test_dsai_plugin_interface_and_attributes(self):
        """LPR plugin must inherit DetectionPlugin and define mandatory metadata."""
        dsai_plugin = LPRPlugin()
        assert dsai_plugin.name == "lpr"
        assert dsai_plugin.version == "1.0.0"
        assert "law_enf" in dsai_plugin.supported_sectors
        assert "default" in dsai_plugin.supported_sectors

    def test_dsai_legacy_lpr_reexport(self):
        """Verify law_enforcement/lpr.py re-exports canonical LPRPlugin."""
        assert LegacyLPRPlugin is LPRPlugin

    def test_dsai_plugin_loader_discovery(self):
        """PluginLoader must discover and load LPRPlugin for sector law_enf."""
        dsai_loader = PluginLoader({"plugins": {"lpr": {"enabled": True}}})
        dsai_discovered = dsai_loader.discover_plugins()
        assert "lpr" in dsai_discovered

        dsai_loaded = dsai_loader.load_plugins(tenant_sector="law_enf", tenant_id="tenant_alpha")
        dsai_lpr_instances = [p for p in dsai_loaded if getattr(p, "name", "") == "lpr"]
        assert len(dsai_lpr_instances) >= 1

    def test_dsai_openvino_ctc_decoder(self):
        """Verify _dsai_ctc_decode collapses consecutive duplicates and removes blank tokens."""
        dsai_plugin = LPRPlugin()
        # Vocab: index 0 is blank; index 1 is '0', 2 is '1', ..., 11 is 'A', etc.
        # Construct logits sequence for "CA7XYZ123":
        # Introduce repeat tokens: C, C, blank, A, 7, 7, X, Y, Z, 1, 2, 3, 3
        dsai_vocab = dsai_plugin.dsai_vocab
        dsai_target = "CA7XYZ123"
        dsai_seq_tokens = []
        for ch in dsai_target:
            idx = dsai_vocab.index(ch) + 1  # 1-based offset (0 is blank)
            dsai_seq_tokens.append(idx)
            # randomly repeat some tokens to test CTC repeat collapsing
            if ch in ("C", "7", "3"):
                dsai_seq_tokens.append(idx)
            # insert blank tokens
            dsai_seq_tokens.append(0)

        dsai_T = len(dsai_seq_tokens)
        dsai_C = len(dsai_vocab) + 1
        dsai_logits = np.zeros((1, dsai_T, dsai_C), dtype=np.float32)

        for t, tok in enumerate(dsai_seq_tokens):
            dsai_logits[0, t, tok] = 10.0  # high probability for target token

        dsai_decoded_text, dsai_conf = dsai_plugin._dsai_ctc_decode(dsai_logits)
        assert dsai_decoded_text == dsai_target
        assert dsai_conf >= 0.95

    def test_dsai_detect_rejects_synthetic_first_row_pixel_fallback(self):
        """LPR plugin must reject fake pixel-value ASCII frames and require real visual plate images."""
        dsai_plugin = LPRPlugin()
        dsai_frame = np.zeros((100, 200, 3), dtype=np.uint8)
        dsai_expected_plate = "DL03CC9876"
        for dsai_i, dsai_char in enumerate(dsai_expected_plate):
            dsai_frame[0, dsai_i, 0] = ord(dsai_char)

        # Since fake ASCII decoding was removed, this blank frame with pixel values returns []
        dsai_dets = dsai_plugin.detect(dsai_frame)
        assert dsai_dets == []

    def test_dsai_detect_blank_or_none_frame(self):
        """LPR plugin gracefully returns empty list for blank or None frames."""
        dsai_plugin = LPRPlugin()
        assert dsai_plugin.detect(None) == []
        assert dsai_plugin.detect(np.zeros((0, 0, 3), dtype=np.uint8)) == []

    def test_dsai_detect_visual_plate_image(self):
        """LPR plugin detects and recognizes license plates on rendered image frames."""
        dsai_plugin = LPRPlugin()
        dsai_plate_text = "MH12DE1432"
        dsai_plate_img = dsai_create_sample_plate_image(dsai_plate_text)

        dsai_dets = dsai_plugin.detect(dsai_plate_img)
        assert len(dsai_dets) >= 1
        dsai_read = dsai_dets[0]
        assert dsai_read["label"] == "plate"
        assert dsai_read["plate_number"] == dsai_plate_text
        assert dsai_read["confidence"] >= 0.85
        assert len(dsai_read["bbox"]) == 4


# =====================================================================
# 2. VP-19 & TEST-81: REAL PLATE ACCURACY REGRESSION TEST HARNESS
# =====================================================================

class TestVP19AndTEST81PlateAccuracyHarness:
    """VP-19 & TEST-81: Regression test harness for plate reading accuracy."""

    def test_dsai_real_plate_accuracy_measurement(self):
        """Measure real plate-read accuracy against sample license plates (VP-19, TEST-81)."""
        dsai_plugin = LPRPlugin()
        dsai_sample_plates = [
            "DL03CC9876",
            "MH12DE1432",
            "KA05MH2020",
            "CA7XYZ123",
            "NY8ABC456",
            "WB02K7788",
            "TN09AZ5544",
            "TX4DEF789",
        ]

        dsai_dataset = []
        for dsai_plate in dsai_sample_plates:
            dsai_img = dsai_create_sample_plate_image(dsai_plate)
            dsai_dataset.append((dsai_img, dsai_plate))

        dsai_metrics = dsai_plugin.dsai_measure_accuracy(dsai_dataset)

        assert dsai_metrics["total_samples"] == len(dsai_sample_plates)
        assert dsai_metrics["character_accuracy"] >= 0.90, (
            f"Character accuracy {dsai_metrics['character_accuracy']:.2%} is below 90% threshold"
        )
        assert dsai_metrics["exact_accuracy"] >= 0.75, (
            f"Exact accuracy {dsai_metrics['exact_accuracy']:.2%} is below 75% threshold"
        )
        assert dsai_metrics["is_passing"] is True


# =====================================================================
# 3. DM-7: POSTGRESQL TRINETRA_PLATES SCHEMA AND PG_TRGM GIN INDEX
# =====================================================================

class TestDM7PostgresSchemaAndRepository:
    """DM-7: PostgreSQL trinetra_plates schema, plate_reads table, and pg_trgm GIN index."""

    def test_dsai_migration_script_structure(self):
        """Verify 0002_trinetra_plates_pg_trgm.py defines schema and pg_trgm GIN index."""
        import importlib.util
        dsai_spec = importlib.util.spec_from_file_location(
            "dsai_mig_0002",
            "migrations/versions/0002_trinetra_plates_pg_trgm.py"
        )
        assert dsai_spec is not None
        assert dsai_spec.loader is not None
        dsai_mig = importlib.util.module_from_spec(dsai_spec)
        dsai_spec.loader.exec_module(dsai_mig)

        assert dsai_mig.revision == "0002"
        assert dsai_mig.down_revision == "0001"
        assert hasattr(dsai_mig, "upgrade")
        assert hasattr(dsai_mig, "downgrade")

    def test_dsai_trigram_similarity_metric(self):
        """Verify trigram similarity behaves identically to pg_trgm (DM-7, SR-38)."""
        # Exact match
        assert dsai_trigram_similarity("KA01AB1234", "KA01AB1234") == 1.0

        # OCR Confusion (0 vs O, 1 vs I)
        dsai_ocr_sim = dsai_trigram_similarity("KA01AB1234", "KAOIAB1234")
        assert dsai_ocr_sim >= 0.45, f"OCR confused similarity {dsai_ocr_sim} should be >= 0.45"

        # Completely different plate
        dsai_diff_sim = dsai_trigram_similarity("KA01AB1234", "MH12DE1432")
        assert dsai_diff_sim == 0.0

    def test_dsai_plate_repository_crud_and_idempotent_upsert(self, dsai_test_db_session, monkeypatch):
        """Duplicate processing upserts without duplicating plate read rows (DM-7, VP-21)."""
        dsai_repo = PlateRepository("tenant_gamma")
        monkeypatch.setattr(dsai_repo, "Session", dsai_test_db_session)

        dsai_read1 = dsai_repo.create(
            video_object_pk="obj-pk-unique-101",
            video_id="video-stream-01",
            camera_id="cam-north",
            frame_timestamp=1700000100.0,
            plate_text_raw="KA 01 AB 1234",
            plate_text_norm="KA01AB1234",
            ocr_confidence=0.92,
            crop_path="crops/p1.jpg"
        )
        assert dsai_read1.plate_text_norm == "KA01AB1234"
        assert dsai_read1.ocr_confidence == 0.92

        # Idempotent re-process with higher confidence: updates existing, does NOT create new row
        dsai_read2 = dsai_repo.create(
            video_object_pk="obj-pk-unique-101",
            video_id="video-stream-01",
            camera_id="cam-north",
            frame_timestamp=1700000100.0,
            plate_text_raw="KA 01 AB 1234",
            plate_text_norm="KA01AB1234",
            ocr_confidence=0.98,
            crop_path="crops/p1_updated.jpg"
        )
        assert dsai_read2.id == dsai_read1.id
        assert dsai_read2.ocr_confidence == 0.98
        assert dsai_read2.crop_path == "crops/p1_updated.jpg"

        # Verify only 1 row exists
        with dsai_test_db_session() as dsai_s:
            dsai_total_rows = dsai_s.query(PlateRead).count()
            assert dsai_total_rows == 1

    def test_dsai_plate_repository_cross_tenant_isolation_exact(self, dsai_test_db_session, monkeypatch):
        """Verify search_exact strictly isolates plate data by tenant_id."""
        dsai_repo_a = PlateRepository("tenant_alpha")
        dsai_repo_b = PlateRepository("tenant_beta")
        monkeypatch.setattr(dsai_repo_a, "Session", dsai_test_db_session)
        monkeypatch.setattr(dsai_repo_b, "Session", dsai_test_db_session)

        # Both tenants create a plate read with identical plate text
        dsai_repo_a.create(
            video_object_pk="pk-tenant-a-1",
            video_id="vid-a",
            camera_id="cam-a",
            frame_timestamp=100.0,
            plate_text_raw="KA 01 AB 1234",
            plate_text_norm="KA01AB1234",
            ocr_confidence=0.95
        )
        dsai_repo_b.create(
            video_object_pk="pk-tenant-b-1",
            video_id="vid-b",
            camera_id="cam-b",
            frame_timestamp=105.0,
            plate_text_raw="KA 01 AB 1234",
            plate_text_norm="KA01AB1234",
            ocr_confidence=0.91
        )
        # Tenant B creates an exclusive plate
        dsai_repo_b.create(
            video_object_pk="pk-tenant-b-2",
            video_id="vid-b2",
            camera_id="cam-b2",
            frame_timestamp=110.0,
            plate_text_raw="MH 12 DE 1432",
            plate_text_norm="MH12DE1432",
            ocr_confidence=0.93
        )

        # Querying tenant_alpha MUST return ONLY tenant_alpha's records
        dsai_results_a = dsai_repo_a.search_exact("KA01AB1234")
        assert len(dsai_results_a) == 1
        assert dsai_results_a[0].tenant_id == "tenant_alpha"
        assert dsai_results_a[0].video_object_pk == "pk-tenant-a-1"

        # Querying tenant_alpha for tenant_beta's exclusive plate MUST return empty list
        dsai_results_a_exclusive = dsai_repo_a.search_exact("MH12DE1432")
        assert len(dsai_results_a_exclusive) == 0

        # Querying tenant_beta MUST return ONLY tenant_beta's records
        dsai_results_b = dsai_repo_b.search_exact("KA01AB1234")
        assert len(dsai_results_b) == 1
        assert dsai_results_b[0].tenant_id == "tenant_beta"
        assert dsai_results_b[0].video_object_pk == "pk-tenant-b-1"

    def test_dsai_plate_repository_cross_tenant_isolation_fuzzy(self, dsai_test_db_session, monkeypatch):
        """Verify search_fuzzy strictly isolates fuzzy plate matches by tenant_id."""
        dsai_repo_a = PlateRepository("tenant_alpha")
        dsai_repo_b = PlateRepository("tenant_beta")
        monkeypatch.setattr(dsai_repo_a, "Session", dsai_test_db_session)
        monkeypatch.setattr(dsai_repo_b, "Session", dsai_test_db_session)

        # Tenant Alpha plate
        dsai_repo_a.create(
            video_object_pk="pk-a-fuzzy",
            video_id="vid-a",
            camera_id="cam-a",
            frame_timestamp=200.0,
            plate_text_raw="CA 7 XYZ 123",
            plate_text_norm="CA7XYZ123",
            ocr_confidence=0.94
        )
        # Tenant Beta plate with OCR-confused plate text
        dsai_repo_b.create(
            video_object_pk="pk-b-fuzzy",
            video_id="vid-b",
            camera_id="cam-b",
            frame_timestamp=205.0,
            plate_text_raw="CA 7 XYZ I23",
            plate_text_norm="CA7XYZI23",
            ocr_confidence=0.88
        )

        # Fuzzy search from Alpha MUST NOT return Beta's plate read
        dsai_results_a = dsai_repo_a.search_fuzzy("CA7XYZ123", similarity_threshold=0.3)
        assert len(dsai_results_a) == 1
        assert dsai_results_a[0].tenant_id == "tenant_alpha"
        assert dsai_results_a[0].video_object_pk == "pk-a-fuzzy"


# =====================================================================
# 4. VP-21: CONSUMER INTEGRATION AND MILVUS PLATE ATTRIBUTES
# =====================================================================

class TestVP21ConsumerMilvusAndRelationalPersistence:
    """VP-21: Vehicle detection with plate sets Milvus attributes and inserts plate_reads."""

    def test_dsai_ensure_vehicle_collection_includes_plate_candidate_id(self):
        """Milvus vehicle collection schema must include plate_candidate_id and scalar index."""
        dsai_mock_cls = MagicMock()
        dsai_mock_instance = MagicMock()
        dsai_mock_cls.return_value = dsai_mock_instance

        with patch("deepSightAI.Trinetra.Shared.Milvus.connections.has_connection", return_value=True), \
             patch("deepSightAI.Trinetra.Shared.Milvus.utility.has_collection", return_value=False), \
             patch("deepSightAI.Trinetra.Shared.Milvus.Collection", dsai_mock_cls):

            dsai_coll = ensure_vehicle_collection(tenant_id="tenant_delta")
            dsai_call_kwargs = dsai_mock_cls.call_args[1]
            dsai_schema = dsai_call_kwargs["schema"]
            dsai_field_names = [f.name for f in dsai_schema.fields]

            assert "has_plate_read" in dsai_field_names
            assert "plate_number" in dsai_field_names
            assert "plate_candidate_id" in dsai_field_names

            # Verify scalar index on plate_candidate_id
            dsai_index_calls = dsai_mock_instance.create_index.call_args_list
            dsai_indexed_scalars = [c[1].get("field_name") for c in dsai_index_calls if c[1].get("field_name") != "embedding"]
            assert "plate_candidate_id" in dsai_indexed_scalars
            assert "has_plate_read" in dsai_indexed_scalars

    def test_dsai_vps_consumer_persists_plate_and_milvus_fields(self, dsai_test_db_session, monkeypatch):
        """On vehicle detection with plate: insert plate_reads and set plate_candidate_id in Milvus (VP-21)."""
        dsai_mock_minio = MagicMock()
        dsai_mock_producer = MagicMock()
        dsai_consumer = VisionProcessingConsumer(
            dsai_minio_client=dsai_mock_minio,
            dsai_producer=dsai_mock_producer,
            dsai_config={"tenants": {"t_lpr": {"sector": "law_enf"}}}
        )

        dsai_mock_vehicle_coll = MagicMock()

        # Mock detection returning vehicle with a detected plate
        dsai_mock_vehicle_plugin = MagicMock()
        dsai_mock_vehicle_plugin.detect.return_value = [{
            "label": "vehicle",
            "object_class": "vehicle",
            "confidence": 0.96,
            "bbox": [10.0, 20.0, 300.0, 200.0],
            "embedding": [0.1] * 256,
            "color": "blue",
            "vehicle_type": "sedan",
            "has_plate_read": True,
            "plate_number": "KA01AB1234",
            "plate_candidate_id": "plate_cand_custom_101",
        }]
        dsai_consumer.plugin_loader.load_plugins = MagicMock(return_value=[dsai_mock_vehicle_plugin])

        # Patch PlateRepository session to in-memory db
        monkeypatch.setattr(PlateRepository, "Session", dsai_test_db_session)

        with patch("deepSightAI.Trinetra.VisionProcessingService.dsai_consumer.ensure_vehicle_collection", return_value=dsai_mock_vehicle_coll), \
             patch("deepSightAI.Trinetra.VisionProcessingService.dsai_consumer.ensure_person_collection", return_value=MagicMock()):

            dsai_event = FrameReadyEvent(
                video_id="vid_lpr_99",
                segment_id=0,
                frame_paths=["t_lpr/cam1/2026-09-21/f1.jpg"],
                timestamps=[45.0],
                sequence_numbers=[0],
                extractor_id="ext_1",
                bucket_name="frames",
                tenant_id="t_lpr",
                camera_id="cam_gate_1",
                timestamp=datetime.now(timezone.utc),
            )

            dsai_emitted = dsai_consumer.dsai_process_event(dsai_event)

            # Milvus insert called with plate_candidate_id and has_plate_read
            assert dsai_mock_vehicle_coll.insert.called
            dsai_insert_args = dsai_mock_vehicle_coll.insert.call_args[0][0]
            # Column 11: has_plate_read, Column 12: plate_number, Column 13: plate_candidate_id
            assert dsai_insert_args[11] == [True]
            assert dsai_insert_args[12] == ["KA01AB1234"]
            assert dsai_insert_args[13] == ["plate_cand_custom_101"]

            # Emitted ObjectDetectedEvent contains plate fields
            assert len(dsai_emitted) == 1
            dsai_obj = dsai_emitted[0]
            assert dsai_obj.has_plate_read is True
            assert dsai_obj.plate_number == "KA01AB1234"
            assert dsai_obj.plate_candidate_id == "plate_cand_custom_101"

            # Relational plate_reads table contains the persisted record
            with dsai_test_db_session() as dsai_s:
                dsai_stored_plate = dsai_s.query(PlateRead).filter_by(plate_text_norm="KA01AB1234").first()
                assert dsai_stored_plate is not None
                assert dsai_stored_plate.camera_id == "cam_gate_1"
                assert dsai_stored_plate.video_id == "vid_lpr_99"

    def test_dsai_consumer_plate_insert_failure_raises_storage_error(self, dsai_test_db_session, monkeypatch):
        """Plate persistence failures must raise StorageError, enforcing write durability discipline."""
        dsai_mock_minio = MagicMock()
        dsai_mock_producer = MagicMock()
        dsai_consumer = VisionProcessingConsumer(
            dsai_minio_client=dsai_mock_minio,
            dsai_producer=dsai_mock_producer,
            dsai_config={"tenants": {"t_lpr": {"sector": "law_enf"}}}
        )

        dsai_mock_vehicle_plugin = MagicMock()
        dsai_mock_vehicle_plugin.detect.return_value = [{
            "label": "vehicle",
            "object_class": "vehicle",
            "confidence": 0.96,
            "bbox": [10.0, 20.0, 300.0, 200.0],
            "embedding": [0.1] * 256,
            "color": "blue",
            "vehicle_type": "sedan",
            "has_plate_read": True,
            "plate_number": "KA01AB1234",
            "plate_candidate_id": "plate_cand_custom_101",
        }]
        dsai_consumer.plugin_loader.load_plugins = MagicMock(return_value=[dsai_mock_vehicle_plugin])

        # Mock PlateRepository.create to raise a database exception
        dsai_mock_repo = MagicMock()
        dsai_mock_repo.create.side_effect = Exception("Postgres connection dropped")
        monkeypatch.setattr(PlateRepository, "create", dsai_mock_repo.create)

        with patch("deepSightAI.Trinetra.VisionProcessingService.dsai_consumer.ensure_vehicle_collection", return_value=MagicMock()), \
             patch("deepSightAI.Trinetra.VisionProcessingService.dsai_consumer.ensure_person_collection", return_value=MagicMock()):

            dsai_event = FrameReadyEvent(
                video_id="vid_lpr_fail",
                segment_id=0,
                frame_paths=["t_lpr/cam1/2026-09-21/f1.jpg"],
                timestamps=[45.0],
                sequence_numbers=[0],
                extractor_id="ext_1",
                bucket_name="frames",
                tenant_id="t_lpr",
                camera_id="cam_gate_1",
                timestamp=datetime.now(timezone.utc),
            )

            with pytest.raises(StorageError):
                dsai_consumer.dsai_process_event(dsai_event)


# =====================================================================
# 5. SR-38: POST /search/plate ENDPOINT
# =====================================================================

class TestSR38PlateSearchAPI:
    """SR-38: POST /search/plate supporting exact and trigram similarity search."""

    def test_dsai_search_plate_exact_match(self, dsai_search_client, dsai_test_db_session, monkeypatch):
        """Exact plate search returns exact match with score 1.0 (SR-38)."""
        dsai_auth_user = {"sub": "u_test", "tenant_id": "tenant_search", "permissions": ["search:read"]}
        dsai_search_app.dependency_overrides[dsai_require_search_read] = lambda: dsai_auth_user
        monkeypatch.setattr(PlateRepository, "Session", dsai_test_db_session)

        # Seed records
        dsai_repo = PlateRepository("tenant_search")
        dsai_repo.create("pk1", "v1", "cam1", 10.0, "KA 01 AB 1234", "KA01AB1234", 0.95, crop_path="crops/c1.jpg")
        dsai_repo.create("pk2", "v2", "cam1", 20.0, "MH 12 DE 1432", "MH12DE1432", 0.90, crop_path="crops/c2.jpg")

        with patch("deepSightAI.Trinetra.SearchService.main.dsai_generate_presigned_url", return_value="http://minio/crop.jpg"):
            dsai_payload = {
                "plate_number": "KA01AB1234",
                "exact": True,
                "top_k": 10
            }
            dsai_res = dsai_search_client.post("/search/plate", json=dsai_payload)
            assert dsai_res.status_code == 200
            dsai_data = dsai_res.json()
            assert len(dsai_data) == 1
            assert dsai_data[0]["plate_number"] == "KA01AB1234"
            assert dsai_data[0]["score"] == 1.0
            assert dsai_data[0]["thumbnail_url"] == "http://minio/crop.jpg"

        dsai_search_app.dependency_overrides.pop(dsai_require_search_read, None)

    def test_dsai_search_plate_fuzzy_ocr_confusion_ranking(self, dsai_search_client, dsai_test_db_session, monkeypatch):
        """Fuzzy search ranks exact and OCR-confused plate reads (e.g. 0/O, 1/I) by trigram similarity (SR-38, Verification Criteria)."""
        dsai_auth_user = {"sub": "u_test", "tenant_id": "tenant_search", "permissions": ["search:read"]}
        dsai_search_app.dependency_overrides[dsai_require_search_read] = lambda: dsai_auth_user
        monkeypatch.setattr(PlateRepository, "Session", dsai_test_db_session)

        # Seed records: exact match, OCR-confused (0/O, 1/I), and a completely different plate
        dsai_repo = PlateRepository("tenant_search")
        dsai_repo.create("pk_exact", "v1", "cam1", 10.0, "KA01AB1234", "KA01AB1234", 0.98)
        dsai_repo.create("pk_confused", "v2", "cam1", 15.0, "KAOIAB1234", "KAOIAB1234", 0.88)
        dsai_repo.create("pk_diff", "v3", "cam1", 20.0, "DL03CC9876", "DL03CC9876", 0.95)

        with patch("deepSightAI.Trinetra.SearchService.main.dsai_generate_presigned_url", return_value="http://minio/crop.jpg"):
            dsai_payload = {
                "plate_number": "KA01AB1234",
                "exact": False,
                "mode": "fuzzy",
                "similarity_threshold": 0.3,
                "top_k": 10
            }
            dsai_res = dsai_search_client.post("/search/plate", json=dsai_payload)
            assert dsai_res.status_code == 200
            dsai_data = dsai_res.json()

            # Must return both exact and OCR-confused plate reads, ranked by similarity
            assert len(dsai_data) == 2
            assert dsai_data[0]["plate_number"] == "KA01AB1234"
            assert dsai_data[0]["score"] == 1.0
            assert dsai_data[1]["plate_number"] == "KAOIAB1234"
            assert dsai_data[1]["score"] >= 0.45
            assert dsai_data[0]["score"] > dsai_data[1]["score"]

        dsai_search_app.dependency_overrides.pop(dsai_require_search_read, None)

    def test_dsai_search_plate_camera_and_time_filters(self, dsai_search_client, dsai_test_db_session, monkeypatch):
        """Plate search correctly filters by camera_ids and timestamp range."""
        dsai_auth_user = {"sub": "u_test", "tenant_id": "tenant_search", "permissions": ["search:read"]}
        dsai_search_app.dependency_overrides[dsai_require_search_read] = lambda: dsai_auth_user
        monkeypatch.setattr(PlateRepository, "Session", dsai_test_db_session)

        dsai_repo = PlateRepository("tenant_search")
        dsai_repo.create("pk1", "v1", "cam_north", 100.0, "KA01AB1234", "KA01AB1234", 0.95)
        dsai_repo.create("pk2", "v2", "cam_south", 150.0, "KA01AB1234", "KA01AB1234", 0.95)
        dsai_repo.create("pk3", "v3", "cam_north", 250.0, "KA01AB1234", "KA01AB1234", 0.95)

        with patch("deepSightAI.Trinetra.SearchService.main.dsai_generate_presigned_url", return_value="http://minio/crop.jpg"):
            dsai_payload = {
                "plate_number": "KA01AB1234",
                "camera_ids": ["cam_north"],
                "time_start": 50.0,
                "time_end": 200.0,
                "top_k": 10
            }
            dsai_res = dsai_search_client.post("/search/plate", json=dsai_payload)
            assert dsai_res.status_code == 200
            dsai_data = dsai_res.json()
            assert len(dsai_data) == 1
            assert dsai_data[0]["camera_id"] == "cam_north"
            assert dsai_data[0]["frame_timestamp"] == 100.0

        dsai_search_app.dependency_overrides.pop(dsai_require_search_read, None)

    def test_dsai_search_plate_top_k_ceiling_validation(self, dsai_search_client):
        """Plate search enforces hard top_k ceiling of 100 (SR-44, structured 422)."""
        dsai_auth_user = {"sub": "u_test", "tenant_id": "tenant_search", "permissions": ["search:read"]}
        dsai_search_app.dependency_overrides[dsai_require_search_read] = lambda: dsai_auth_user

        dsai_payload = {
            "plate_number": "KA01AB1234",
            "top_k": 150  # Exceeds maximum 100
        }
        dsai_res = dsai_search_client.post("/search/plate", json=dsai_payload)
        assert dsai_res.status_code == 422
        dsai_data = dsai_res.json()
        assert dsai_data["error"] == "ValidationError"

        dsai_search_app.dependency_overrides.pop(dsai_require_search_read, None)

    def test_dsai_search_plate_unauthenticated_returns_401(self, dsai_search_client):
        """Unauthenticated plate search request returns 401 Unauthorized."""
        dsai_payload = {"plate_number": "KA01AB1234"}
        dsai_res = dsai_search_client.post("/search/plate", json=dsai_payload)
        assert dsai_res.status_code == 401

    def test_dsai_search_service_cross_tenant_isolation(self, dsai_search_client, dsai_test_db_session, monkeypatch):
        """Verify POST /search/plate never returns plate reads belonging to other tenants."""
        # Authenticated as tenant_alpha
        dsai_auth_user = {"sub": "u_alpha", "tenant_id": "tenant_alpha", "permissions": ["search:read"]}
        dsai_search_app.dependency_overrides[dsai_require_search_read] = lambda: dsai_auth_user
        monkeypatch.setattr(PlateRepository, "Session", dsai_test_db_session)

        # Seed plates for tenant_alpha and tenant_beta with identical plate numbers
        dsai_repo_alpha = PlateRepository("tenant_alpha")
        dsai_repo_beta = PlateRepository("tenant_beta")
        dsai_repo_alpha.create("pk_a", "vid_a", "cam_a", 100.0, "KA01AB1234", "KA01AB1234", 0.95, crop_path="crop_a.jpg")
        dsai_repo_beta.create("pk_b", "vid_b", "cam_b", 110.0, "KA01AB1234", "KA01AB1234", 0.95, crop_path="crop_b.jpg")

        with patch("deepSightAI.Trinetra.SearchService.main.dsai_generate_presigned_url", return_value="http://minio/crop.jpg"):
            dsai_payload = {
                "plate_number": "KA01AB1234",
                "exact": True,
                "top_k": 10
            }
            dsai_res = dsai_search_client.post("/search/plate", json=dsai_payload)
            assert dsai_res.status_code == 200
            dsai_data = dsai_res.json()

            # Must return ONLY tenant_alpha's record
            assert len(dsai_data) == 1
            assert dsai_data[0]["camera_id"] == "cam_a"
            assert dsai_data[0]["video_id"] == "vid_a"
            assert dsai_data[0]["attributes"]["video_object_pk"] == "pk_a"

        dsai_search_app.dependency_overrides.pop(dsai_require_search_read, None)


# =====================================================================
# 6. UI-86: STREAMLIT UI CONTRACT
# =====================================================================

class TestUI86PlateSearchIntegration:
    """UI-86: Streamlit UI Plate Search tab configuration."""

    def test_dsai_ui_plate_search_contract(self):
        """Verify UI defines Plate Search tab and handles exact/fuzzy parameters."""
        with open("deepSightAI/Trinetra/UI/ui.py", "r") as dsai_f:
            dsai_ui_code = dsai_f.read()

        assert "tab_plate" in dsai_ui_code
        assert "Plate Search" in dsai_ui_code
        assert "/search/plate" in dsai_ui_code
        assert "Exact Match" in dsai_ui_code
        assert "Fuzzy Search" in dsai_ui_code
        assert "Similarity Threshold" in dsai_ui_code
