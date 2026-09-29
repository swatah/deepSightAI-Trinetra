"""
Golden dataset fixtures and reference vectors for Enterprise Ingestion V3 (Issue #91).

Provides pre-computed reference vectors, golden test clips, and query sets
so tests can assert on actual vector output and search equivalence (S1).
Strictly adheres to CODING_STANDARDS.md.
"""

import math
from typing import List, Dict, Any


def dsai_generate_deterministic_vector(dsai_seed: int, dsai_dim: int = 512) -> List[float]:
    """Generate a deterministic unit-normalized embedding vector."""
    dsai_raw = [math.sin(dsai_seed * (i + 1)) for i in range(dsai_dim)]
    dsai_norm = math.sqrt(sum(x * x for x in dsai_raw)) or 1.0
    return [round(x / dsai_norm, 6) for x in dsai_raw]


# Deterministic golden vectors for known reference clips
DSAI_GOLDEN_CLIP_VECTOR_A = dsai_generate_deterministic_vector(dsai_seed=42, dsai_dim=512)
DSAI_GOLDEN_CLIP_VECTOR_B = dsai_generate_deterministic_vector(dsai_seed=99, dsai_dim=512)

# Golden search query vector closely aligned with Vector A (similarity ~0.98)
DSAI_GOLDEN_QUERY_VECTOR = [
    round(x * 0.98 + (0.002 if idx % 2 == 0 else -0.002), 6)
    for idx, x in enumerate(DSAI_GOLDEN_CLIP_VECTOR_A)
]
dsai_q_norm = math.sqrt(sum(x * x for x in DSAI_GOLDEN_QUERY_VECTOR)) or 1.0
DSAI_GOLDEN_QUERY_VECTOR = [round(x / dsai_q_norm, 6) for x in DSAI_GOLDEN_QUERY_VECTOR]

DSAI_GOLDEN_TEST_TENANT = "tenant-enterprise-gold"
DSAI_GOLDEN_CAMERA_PULL = "cam-pull-ref-001"
DSAI_GOLDEN_CAMERA_PUSH = "cam-push-ref-002"
DSAI_GOLDEN_VIDEO_ID = "video-ref-clip-20260924"


def dsai_get_golden_pull_event() -> Dict[str, Any]:
    """Return synthetic pull-path FrameReadyEvent payload."""
    return {
        "event_id": "evt-pull-gold-001",
        "tenant_id": DSAI_GOLDEN_TEST_TENANT,
        "camera_id": DSAI_GOLDEN_CAMERA_PULL,
        "video_id": DSAI_GOLDEN_VIDEO_ID,
        "frame_path": f"{DSAI_GOLDEN_TEST_TENANT}/{DSAI_GOLDEN_CAMERA_PULL}/2026-09-24/{DSAI_GOLDEN_VIDEO_ID}_1000.jpg",
        "timestamp": 1727211000.0,
        "embedding": DSAI_GOLDEN_CLIP_VECTOR_A,
    }


def dsai_get_golden_push_event() -> Dict[str, Any]:
    """Return matching push-path EdgeEmbeddingEventV1 payload for same visual content."""
    return {
        "event_id": "evt-push-gold-002",
        "tenant_id": DSAI_GOLDEN_TEST_TENANT,
        "camera_id": DSAI_GOLDEN_CAMERA_PUSH,
        "captured_at": 1727211000.0,
        "embedding_vector": DSAI_GOLDEN_CLIP_VECTOR_A,
        "embedding_dim": 512,
        "model_id": "ViT-B-32",
        "model_version": "1.0",
        "video_id": DSAI_GOLDEN_VIDEO_ID,
        "frame_path": f"{DSAI_GOLDEN_TEST_TENANT}/{DSAI_GOLDEN_CAMERA_PUSH}/2026-09-24/{DSAI_GOLDEN_VIDEO_ID}_1000.jpg",
    }
