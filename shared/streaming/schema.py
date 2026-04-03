"""
Event schemas for streaming video ingestion pipeline.

Uses Pydantic for validation and (de)serialization.
"""

from datetime import datetime
from typing import List, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class IngestJobStarted(BaseModel):
    """Event emitted when an ingest job is initiated."""
    event_type: Literal["ingest.started"] = "ingest.started"
    job_id: str
    source_type: str  # "file", "rtsp", "hls", etc.
    source_identifier: str  # e.g., MinIO key for files, RTSP URL for streams
    tenant_id: str = Field(default="default")  # optional, for multi-tenancy
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
