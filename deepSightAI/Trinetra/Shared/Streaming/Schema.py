"""
Event schemas for streaming video ingestion pipeline.

Uses Pydantic for validation and (de)serialization.
"""

from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class IngestJobStarted(BaseModel):
    """Event emitted when an ingest job is initiated."""
    event_type: Literal["ingest.started"] = "ingest.started"
    job_id: str
    source_type: str  # "file", "rtsp", "hls", etc.
    source_identifier: str  # e.g., MinIO key for files, RTSP URL for streams
    tenant_id: str = Field(default="default")  # optional, for multi-tenancy
    correlation_id: Optional[str] = None
    timestamp: datetime

    @field_validator('source_type')
    def validate_source_type(cls, v):
        allowed = {"file", "rtsp", "hls", "dash", "mjpeg"}
        if v not in allowed:
            raise ValueError(f"source_type must be one of {allowed}")
        return v


class IngestJobCompleted(BaseModel):
    """Event emitted when all frames for a job have been extracted and queued."""
    event_type: Literal["ingest.completed"] = "ingest.completed"
    job_id: str
    source_type: str
    video_id: str  # The canonical ID for this video/stream
    frame_count: int = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    correlation_id: Optional[str] = None
    timestamp: datetime


class FrameReadyEvent(BaseModel):
    """Event emitted by extractor after uploading a batch of frames."""
    event_type: Literal["frame.ready"] = "frame.ready"
    video_id: str
    segment_id: int = Field(ge=0)  # segment number within video (0 for RTSP)
    frame_paths: List[str] = Field(..., min_length=1)  # MinIO object paths
    timestamps: List[float] = Field(..., min_length=1)  # timestamps in seconds from video start
    sequence_numbers: List[int] = Field(..., min_length=1)  # increasing per frame within segment
    extractor_id: str
    bucket_name: str  # usually 'frames' or 'frames-rtsp-...'
    tenant_id: str = Field(default="default")
    camera_id: Optional[str] = None
    correlation_id: Optional[str] = None
    timestamp: datetime

    @field_validator('timestamps')
    def timestamps_monotonic(cls, v):
        if len(v) >= 2 and not all(v[i] <= v[i+1] for i in range(len(v)-1)):
            raise ValueError("timestamps must be non-decreasing")
        return v

    @field_validator('sequence_numbers')
    def sequences_monotonic(cls, v):
        if len(v) >= 2 and not all(v[i] < v[i+1] for i in range(len(v)-1)):
            raise ValueError("sequence_numbers must be strictly increasing")
        return v

    @model_validator(mode='after')
    def check_lengths_consistency(self):
        fps = len(self.frame_paths)
        ts = len(self.timestamps)
        ss = len(self.sequence_numbers)
        if not (fps == ts == ss):
            raise ValueError(f"Mismatched lengths: frame_paths={fps}, timestamps={ts}, sequence_numbers={ss}")
        return self


class EmbedderProcessingStarted(BaseModel):
    event_type: Literal["embedder.started"] = "embedder.started"
    video_id: str
    consumer_id: str  # embedder instance identifier
    timestamp: datetime


class EmbedderProcessingCompleted(BaseModel):
    event_type: Literal["embedder.completed"] = "embedder.completed"
    video_id: str
    frames_processed: int = Field(ge=0)
    embeddings_inserted: int = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    timestamp: datetime


class ObjectDetectedEvent(BaseModel):
    """
    Event emitted when an object (person/vehicle) is detected and written to Milvus (DM-6, VP-22).
    Published to 'events:object_detected'.
    """
    event_type: Literal["object.detected"] = "object.detected"
    video_object_pk: str
    tenant_id: str = Field(default="default")
    camera_id: str
    video_id: str
    frame_timestamp: float
    frame_path: str
    crop_path: Optional[str] = None
    object_class: str  # "person" or "vehicle"
    confidence: float
    bbox: List[float] = Field(default_factory=list)  # [x1, y1, x2, y2]
    attributes: Optional[dict] = Field(default_factory=dict)
    has_plate_read: bool = False
    plate_number: Optional[str] = None
    plate_candidate_id: Optional[str] = None
    reid_embedding: Optional[List[float]] = None
    correlation_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class WatchlistAlertEvent(BaseModel):
    """
    Event emitted when an object matches a watchlist entry (WL-31).
    Published to 'events:watchlist_alerts'.
    """
    event_type: Literal["watchlist.alert"] = "watchlist.alert"
    alert_id: int
    tenant_id: str = Field(default="default")
    watchlist_entry_id: int
    video_object_pk: str
    camera_id: str
    matched_at: datetime = Field(default_factory=datetime.utcnow)
    match_score: float
    crop_path: Optional[str] = None
    label: Optional[str] = None
    priority: str = "medium"
    entry_type: Optional[str] = None
    matched_entity: Optional[str] = None
    correlation_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DeadLetterQueueEvent(BaseModel):
    """
    Event emitted when a message fails processing and exceeds max retries (REL-57).
    Published to dead-letter queue stream (e.g. 'events:dlq').
    """
    event_type: Literal["events.dlq"] = "events.dlq"
    source_stream: str
    message_id: str
    event_payload: Optional[dict] = None
    error: str
    retry_count: int = Field(default=0, ge=0)
    correlation_id: Optional[str] = None
    tenant_id: Optional[str] = Field(default="default")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# --- EDGE INGESTION SCHEMAS (Issues #76, #78, E1, E2, E8) ---

DSAI_KNOWN_EMBEDDING_MODELS = {
    "ViT-B-32": {"1.0": 512, "default": 512},
    "ViT-B-16": {"1.0": 512, "default": 512},
    "ViT-L-14": {"1.0": 768, "default": 768},
    "open_clip_vit_b32": {"1.0": 512, "default": 512},
}


class EdgeEmbeddingEventV1(BaseModel):
    """
    Versioned edge embedding event schema (E2/§5.3, E8, Issue #78).
    Published for external integrators.
    """
    event_type: Literal["edge.embedding.v1"] = "edge.embedding.v1"
    event_id: str = Field(..., min_length=1, description="Unique event ID for deduplication")
    camera_id: str = Field(..., min_length=1, description="Camera identifier")
    tenant_id: str = Field(..., min_length=1, description="Tenant identifier")
    captured_at: float = Field(..., description="Epoch timestamp in seconds when frame was captured")
    embedding_vector: List[float] = Field(..., min_length=1, description="Embedding vector")
    embedding_dim: int = Field(..., gt=0, description="Embedding vector dimensionality")
    model_id: str = Field(..., min_length=1, description="Model identifier, e.g. ViT-B-32")
    model_version: str = Field(..., min_length=1, description="Model version, e.g. 1.0")
    correlation_id: Optional[str] = None
    device_id: Optional[str] = None

    @field_validator("event_id")
    def validate_event_id(cls, v):
        if not v or not str(v).strip():
            raise ValueError("event_id cannot be empty")
        return str(v).strip()

    @field_validator("camera_id")
    def validate_camera_id(cls, v):
        if not v or not str(v).strip():
            raise ValueError("camera_id cannot be empty")
        return str(v).strip()

    @field_validator("tenant_id")
    def validate_tenant_id(cls, v):
        if not v or not str(v).strip():
            raise ValueError("tenant_id cannot be empty")
        return str(v).strip()

    @model_validator(mode="after")
    def validate_model_and_dimensions(self):
        # Validate vector length vs declared embedding_dim
        actual_dim = len(self.embedding_vector)
        if actual_dim != self.embedding_dim:
            raise ValueError(
                f"dimension_mismatch: declared embedding_dim={self.embedding_dim} but vector has {actual_dim} elements"
            )

        # Validate model_id and model_version against known model registry
        known_versions = DSAI_KNOWN_EMBEDDING_MODELS.get(self.model_id)
        if not known_versions:
            raise ValueError(f"unknown_model: model_id '{self.model_id}' is unknown or retired")

        expected_dim = known_versions.get(self.model_version) or known_versions.get("default")
        if expected_dim is None:
            raise ValueError(
                f"unknown_model_version: model_version '{self.model_version}' is unknown or retired for model '{self.model_id}'"
            )

        if self.embedding_dim != expected_dim:
            raise ValueError(
                f"dimension_mismatch: model '{self.model_id}' version '{self.model_version}' expects {expected_dim} dimensions, got {self.embedding_dim}"
            )

        return self


class EdgeBatchRequestV1(BaseModel):
    """Batch payload wrapper for edge submissions (E2, Issue #76)."""
    events: List[EdgeEmbeddingEventV1] = Field(..., min_length=1, description="List of edge embedding events")


class EdgeEmbeddingEventV2(EdgeEmbeddingEventV1):
    """V2 schema with additional metadata support."""
    event_type: Literal["edge.embedding.v2"] = "edge.embedding.v2"
    metadata: Optional[dict] = Field(default_factory=dict)



