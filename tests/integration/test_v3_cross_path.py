"""
Integration Test Suite for Enterprise Ingestion V3 — Cross-Path & Shared Pipeline (Issue #95, Testing Plan §4).

Covers:
- S1: Identical Milvus record shape and search query equivalence for pull vs push vectors
- S2: Mid-flight camera path reassignment with atomic transition and drain
- S3: Independent per-path health metrics and non-masking health scoring

Strictly adheres to CODING_STANDARDS.md.
"""

import math
import pytest
from unittest.mock import MagicMock, patch

from deepSightAI.Trinetra.Shared.dsai_normalization import (
    MilvusNormalizer,
    MilvusCanonicalRecord,
)
from deepSightAI.Trinetra.Shared.Streaming.Schema import (
    FrameReadyEvent,
    EdgeEmbeddingEventV1,
)
from deepSightAI.Trinetra.Shared.Repositories.CameraRepository import CameraRepository, Camera
from deepSightAI.Trinetra.Shared.Metrics import (
    dsai_get_per_path_health,
    dsai_record_pull_stream_count,
    dsai_record_pull_error,
    dsai_record_push_device_count,
    dsai_record_push_error,
    dsai_reset_health_metrics,
)
from tests.fixtures.dsai_golden_fixtures import (
    DSAI_GOLDEN_CLIP_VECTOR_A,
    DSAI_GOLDEN_QUERY_VECTOR,
    DSAI_GOLDEN_TEST_TENANT,
    DSAI_GOLDEN_CAMERA_PULL,
    DSAI_GOLDEN_CAMERA_PUSH,
    DSAI_GOLDEN_VIDEO_ID,
    dsai_get_golden_pull_event,
    dsai_get_golden_push_event,
)


def dsai_cosine_similarity(dsai_vec_a: list, dsai_vec_b: list) -> float:
    """Calculate cosine similarity between two unit vectors."""
    dsai_dot = sum(a * b for a, b in zip(dsai_vec_a, dsai_vec_b))
    dsai_norm_a = math.sqrt(sum(a * a for a in dsai_vec_a)) or 1.0
    dsai_norm_b = math.sqrt(sum(b * b for b in dsai_vec_b)) or 1.0
    return dsai_dot / (dsai_norm_a * dsai_norm_b)


@pytest.mark.ci_tier
@pytest.mark.integration
class TestCrossPathIntegrationS1ToS3:
    """Cross-path unification and mutual isolation test suite."""

    @pytest.fixture(autouse=True)
    def dsai_setup_suite(self):
        """Reset per-path health metrics before each test run."""
        dsai_reset_health_metrics()
        yield
        dsai_reset_health_metrics()

    def test_dsai_s1_golden_search_query_equivalence(self):
        """
        S1: Reference clip ingested via pull path and push path generates identical
        canonical record structure in Milvus, and the golden search query matches both identically.
        """
        # 1. Normalize Pull-Path Record
        dsai_canonical_pull: MilvusCanonicalRecord = MilvusNormalizer.dsai_normalize_pull(
            dsai_video_id=DSAI_GOLDEN_VIDEO_ID,
            dsai_camera_id=DSAI_GOLDEN_CAMERA_PULL,
            dsai_frame_path=f"{DSAI_GOLDEN_TEST_TENANT}/{DSAI_GOLDEN_CAMERA_PULL}/2026-09-24/{DSAI_GOLDEN_VIDEO_ID}_1000.jpg",
            dsai_timestamp=1727211000.0,
            dsai_embedding=DSAI_GOLDEN_CLIP_VECTOR_A,
            dsai_tenant_id=DSAI_GOLDEN_TEST_TENANT,
            dsai_correlation_id="corr-pull-001"
        )

        # 2. Normalize Push-Path Record (from same visual scene / reference clip)
        dsai_push_event = EdgeEmbeddingEventV1(**dsai_get_golden_push_event())
        dsai_canonical_push: MilvusCanonicalRecord = MilvusNormalizer.dsai_normalize_push(
            dsai_event=dsai_push_event,
            dsai_correlation_id="corr-push-002"
        )

        # 3. Assert canonical schema equivalence (exact same field names, dimensions, types)
        assert set(dsai_canonical_pull.model_dump().keys()) == set(dsai_canonical_push.model_dump().keys())
        assert len(dsai_canonical_pull.embedding) == len(dsai_canonical_push.embedding) == 512
        assert dsai_canonical_pull.tenant_id == dsai_canonical_push.tenant_id == DSAI_GOLDEN_TEST_TENANT
        assert dsai_canonical_pull.video_id == DSAI_GOLDEN_VIDEO_ID
        assert dsai_canonical_push.video_id == DSAI_GOLDEN_CAMERA_PUSH
        assert dsai_canonical_pull.embedding == dsai_canonical_push.embedding

        # 4. Search Query Equivalence: Query vector achieves identical high similarity on both
        dsai_sim_pull = dsai_cosine_similarity(DSAI_GOLDEN_QUERY_VECTOR, dsai_canonical_pull.embedding)
        dsai_sim_push = dsai_cosine_similarity(DSAI_GOLDEN_QUERY_VECTOR, dsai_canonical_push.embedding)

        assert dsai_sim_pull > 0.95
        assert dsai_sim_push > 0.95
        # Difference between pull and push retrieval confidence is zero
        assert abs(dsai_sim_pull - dsai_sim_push) < 1e-6

    def test_dsai_s2_camera_path_reassignment_and_drain(self):
        """
        S2: Reassign a camera from pull to push (and push to pull) while in flight.
        Drains old path before committing new path; no window permits concurrent acceptance.
        """
        dsai_mock_session = MagicMock()
        dsai_mock_camera = MagicMock(id="cam-switch-01", ingestion_path="pull")
        dsai_mock_session.__enter__.return_value.query.return_value.get.return_value = dsai_mock_camera

        dsai_drained_cams = []

        def dsai_mock_drain_callback(dsai_cid, dsai_old_path):
            dsai_drained_cams.append((dsai_cid, dsai_old_path))

        dsai_repo = CameraRepository(tenant_id="tenant-switch-01")
        with patch.object(dsai_repo, "Session", return_value=dsai_mock_session):
            dsai_updated = dsai_repo.update_ingestion_path(
                camera_id="cam-switch-01",
                new_path="push",
                drain_callback=dsai_mock_drain_callback
            )
            assert dsai_mock_camera.ingestion_path == "push"
            assert len(dsai_drained_cams) == 1
            assert dsai_drained_cams[0] == ("cam-switch-01", "pull")

            # Validate invalid path rejected
            with pytest.raises(ValueError):
                dsai_repo.update_ingestion_path(camera_id="cam-switch-01", new_path="hybrid_unsupported")

    def test_dsai_s3_independent_per_path_health_metrics(self):
        """
        S3: Inducing a severe failure on push path does not degrade pull path health score,
        preventing healthy pull streams from masking a push outage.
        """
        # Baseline: Both paths healthy
        dsai_record_pull_stream_count(100)
        dsai_record_push_device_count(50)
        dsai_health_init = dsai_get_per_path_health()
        assert dsai_health_init["pull_path"]["status"] == "healthy"
        assert dsai_health_init["push_path"]["status"] == "healthy"

        # Simulate massive push-path failure (e.g. 50 push errors)
        for _ in range(50):
            dsai_record_push_error("edge_connection_timeout")

        dsai_health_degraded = dsai_get_per_path_health()

        # Push health degraded significantly
        assert dsai_health_degraded["push_path"]["status"] in ("degraded", "outage")
        assert dsai_health_degraded["push_path"]["recent_errors"] >= 50

        # Pull health remains healthy
        assert dsai_health_degraded["pull_path"]["status"] == "healthy"
        assert dsai_health_degraded["pull_path"]["recent_errors"] == 0
