"""
Unified Milvus record normalization across ingestion paths (Issue #81, S1).

Maps records from both the pull path (video files, central RTSP extraction)
and the push path (edge device embedding submissions) into a canonical record format
prior to insertion into Milvus collections. Routes any malformed record to DLQ.
"""

import uuid
import logging
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from deepSightAI.Trinetra.Shared.Streaming.Schema import EdgeEmbeddingEventV1
from deepSightAI.Trinetra.Shared.Streaming.Producer import StreamProducer

logger = logging.getLogger("deepSightAI.Trinetra.Shared.Normalization")


class NormalizationError(ValueError):
    """Raised when record normalization fails due to invalid schema or missing tenant."""
    pass


class MilvusCanonicalRecord(BaseModel):
    """Canonical record shape for all downstream vector insertions in Milvus."""
    pk: str = Field(..., description="Unique primary key in Milvus")
    video_id: str = Field(..., description="Canonical video/stream identifier")
    camera_id: str = Field(..., description="Camera identifier")
    frame_path: str = Field(..., description="Object store path or push event identifier")
    frame_timestamp: float = Field(..., description="Timestamp of frame in seconds")
    embedding: List[float] = Field(..., min_length=1, description="Embedding vector")
    tenant_id: str = Field(..., min_length=1, description="Tenant partition identifier")
    ingestion_path: str = Field(..., description="'pull' or 'push'")
    correlation_id: Optional[str] = None
    model_id: str = "ViT-B-32"
    model_version: str = "1.0"


class MilvusNormalizer:
    """Normalizes pull-path and push-path records into MilvusCanonicalRecord."""

    @classmethod
    def _dsai_route_to_dlq(cls, dsai_raw_data: Dict[str, Any], dsai_error_msg: str, dsai_producer: Optional[StreamProducer] = None) -> None:
        """Publish failed normalization event to dead-letter queue (events:dlq)."""
        try:
            dsai_prod = dsai_producer or StreamProducer()
            dsai_dlq_payload = {
                "event_type": "normalization.failure",
                "error": dsai_error_msg,
                "raw_data": str(dsai_raw_data),
            }
            dsai_prod.publish("events:dlq", dsai_dlq_payload)
            logger.error(f"Routed normalization failure to events:dlq: {dsai_error_msg}")
        except Exception as dsai_dlq_err:
            logger.error(f"Failed to route normalization error to DLQ: {dsai_dlq_err}")

    @classmethod
    def dsai_normalize_pull(
        cls,
        dsai_video_id: str,
        dsai_camera_id: str,
        dsai_frame_path: str,
        dsai_timestamp: float,
        dsai_embedding: List[float],
        dsai_tenant_id: str,
        dsai_correlation_id: Optional[str] = None,
        dsai_model_id: str = "ViT-B-32",
        dsai_model_version: str = "1.0",
        dsai_producer: Optional[StreamProducer] = None,
    ) -> MilvusCanonicalRecord:
        """
        Normalize a pull-path frame embedding into canonical format.
        Routes to DLQ and raises NormalizationError on failure.
        """
        dsai_raw = {
            "path": "pull",
            "video_id": dsai_video_id,
            "camera_id": dsai_camera_id,
            "frame_path": dsai_frame_path,
            "timestamp": dsai_timestamp,
            "tenant_id": dsai_tenant_id
        }

        if not dsai_tenant_id or not str(dsai_tenant_id).strip():
            dsai_err = "Normalization failed: missing tenant_id partition"
            cls._dsai_route_to_dlq(dsai_raw, dsai_err, dsai_producer)
            raise NormalizationError(dsai_err)

        if not dsai_camera_id or not str(dsai_camera_id).strip():
            dsai_err = "Normalization failed: missing camera_id"
            cls._dsai_route_to_dlq(dsai_raw, dsai_err, dsai_producer)
            raise NormalizationError(dsai_err)

        if not dsai_embedding or len(dsai_embedding) == 0:
            dsai_err = "Normalization failed: empty embedding vector"
            cls._dsai_route_to_dlq(dsai_raw, dsai_err, dsai_producer)
            raise NormalizationError(dsai_err)

        try:
            return MilvusCanonicalRecord(
                pk=uuid.uuid4().hex,
                video_id=dsai_video_id or dsai_camera_id,
                camera_id=dsai_camera_id,
                frame_path=dsai_frame_path,
                frame_timestamp=float(dsai_timestamp),
                embedding=list(dsai_embedding),
                tenant_id=str(dsai_tenant_id).strip(),
                ingestion_path="pull",
                correlation_id=dsai_correlation_id,
                model_id=dsai_model_id,
                model_version=dsai_model_version,
            )
        except Exception as dsai_e:
            dsai_err = f"Normalization failed on pull record: {dsai_e}"
            cls._dsai_route_to_dlq(dsai_raw, dsai_err, dsai_producer)
            raise NormalizationError(dsai_err)

    @classmethod
    def dsai_normalize_push(
        cls,
        dsai_event: EdgeEmbeddingEventV1,
        dsai_correlation_id: Optional[str] = None,
        dsai_producer: Optional[StreamProducer] = None,
    ) -> MilvusCanonicalRecord:
        """
        Normalize a push-path edge embedding event into canonical format.
        Routes to DLQ and raises NormalizationError on failure.
        """
        dsai_raw = {
            "path": "push",
            "event_id": getattr(dsai_event, "event_id", None),
            "camera_id": getattr(dsai_event, "camera_id", None),
            "tenant_id": getattr(dsai_event, "tenant_id", None)
        }

        if not getattr(dsai_event, "tenant_id", None) or not str(dsai_event.tenant_id).strip():
            dsai_err = "Normalization failed: missing tenant_id partition in push event"
            cls._dsai_route_to_dlq(dsai_raw, dsai_err, dsai_producer)
            raise NormalizationError(dsai_err)

        if not getattr(dsai_event, "camera_id", None) or not str(dsai_event.camera_id).strip():
            dsai_err = "Normalization failed: missing camera_id in push event"
            cls._dsai_route_to_dlq(dsai_raw, dsai_err, dsai_producer)
            raise NormalizationError(dsai_err)

        if not getattr(dsai_event, "embedding_vector", None) or len(dsai_event.embedding_vector) == 0:
            dsai_err = "Normalization failed: empty embedding vector in push event"
            cls._dsai_route_to_dlq(dsai_raw, dsai_err, dsai_producer)
            raise NormalizationError(dsai_err)

        try:
            return MilvusCanonicalRecord(
                pk=uuid.uuid4().hex,
                video_id=dsai_event.camera_id,
                camera_id=dsai_event.camera_id,
                frame_path=f"edge://{dsai_event.tenant_id}/{dsai_event.camera_id}/{dsai_event.event_id}",
                frame_timestamp=float(dsai_event.captured_at),
                embedding=list(dsai_event.embedding_vector),
                tenant_id=str(dsai_event.tenant_id).strip(),
                ingestion_path="push",
                correlation_id=dsai_correlation_id or dsai_event.correlation_id,
                model_id=dsai_event.model_id,
                model_version=dsai_event.model_version,
            )
        except Exception as dsai_e:
            dsai_err = f"Normalization failed on push record: {dsai_e}"
            cls._dsai_route_to_dlq(dsai_raw, dsai_err, dsai_producer)
            raise NormalizationError(dsai_err)


def dsai_normalize_pull_record(
    dsai_video_id: str,
    dsai_camera_id: str,
    dsai_frame_path: str,
    dsai_timestamp: float,
    dsai_embedding: List[float],
    dsai_tenant_id: str,
    dsai_correlation_id: Optional[str] = None,
    dsai_model_id: str = "ViT-B-32",
    dsai_model_version: str = "1.0",
    dsai_producer: Optional[StreamProducer] = None,
) -> MilvusCanonicalRecord:
    return MilvusNormalizer.dsai_normalize_pull(
        dsai_video_id=dsai_video_id,
        dsai_camera_id=dsai_camera_id,
        dsai_frame_path=dsai_frame_path,
        dsai_timestamp=dsai_timestamp,
        dsai_embedding=dsai_embedding,
        dsai_tenant_id=dsai_tenant_id,
        dsai_correlation_id=dsai_correlation_id,
        dsai_model_id=dsai_model_id,
        dsai_model_version=dsai_model_version,
        dsai_producer=dsai_producer,
    )


def dsai_normalize_push_record(
    dsai_event: EdgeEmbeddingEventV1,
    dsai_correlation_id: Optional[str] = None,
    dsai_producer: Optional[StreamProducer] = None,
) -> MilvusCanonicalRecord:
    return MilvusNormalizer.dsai_normalize_push(
        dsai_event=dsai_event,
        dsai_correlation_id=dsai_correlation_id,
        dsai_producer=dsai_producer,
    )
