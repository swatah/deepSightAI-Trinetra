"""
PlateRepository: Data access for license plate reads.

Stores and queries license plate detections within a tenant's schema.
"""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import Column, Integer, String, Float, DateTime, text
from ..db import Base
from .base import BaseRepository


class PlateRead(Base):
    """
    License plate read records.

    Columns:
        id: Auto-increment primary key
        tenant_id: Tenant identifier
        video_object_pk: Unique ID referencing the detection in Milvus
        video_id: Source video / stream session
        camera_id: Registered camera identifier
        frame_timestamp: Capture timestamp (epoch seconds / millis)
        plate_text_raw: Unprocessed OCR text output
        plate_text_norm: Cleaned/normalized alphanumeric plate text
        ocr_confidence: Confidence score from OCR model
        ocr_engine: OCR model/engine identifier (e.g. "pp-ocrv3")
        crop_path: MinIO path to plate/vehicle crop image
        created_at: Record insertion timestamp
    """
    __tablename__ = "plate_reads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    video_object_pk = Column(String(255), unique=True, nullable=False, index=True)
    video_id = Column(String(255), nullable=False)
    camera_id = Column(String(255), nullable=False, index=True)
    frame_timestamp = Column(Float, nullable=False, index=True)
    plate_text_raw = Column(String(64), nullable=False)
    plate_text_norm = Column(String(64), nullable=False, index=True)
    ocr_confidence = Column(Float, nullable=False)
    ocr_engine = Column(String(64), nullable=False, default="pp-ocrv3")
    crop_path = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PlateRepository(BaseRepository[PlateRead]):
    """Repository for PlateRead entities, tenant-scoped."""

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id)

    def create(
        self,
        video_object_pk: str,
        video_id: str,
        camera_id: str,
        frame_timestamp: float,
        plate_text_raw: str,
        plate_text_norm: str,
        ocr_confidence: float,
        ocr_engine: str = "pp-ocrv3",
        crop_path: Optional[str] = None
    ) -> PlateRead:
        """Insert or upsert plate read record."""
        # Check if already exists for idempotency on retries
        existing = self.get_by_object_pk(video_object_pk)
        if existing:
            return existing

        read = PlateRead(
            tenant_id=self.tenant_id,
            video_object_pk=video_object_pk,
            video_id=video_id,
            camera_id=camera_id,
            frame_timestamp=frame_timestamp,
            plate_text_raw=plate_text_raw,
            plate_text_norm=plate_text_norm,
            ocr_confidence=ocr_confidence,
            ocr_engine=ocr_engine,
            crop_path=crop_path
        )
        return self._add(read)

    def get_by_object_pk(self, video_object_pk: str) -> Optional[PlateRead]:
        """Find plate read by detection pk."""
        return self._get(PlateRead, video_object_pk=video_object_pk)

    def search_exact(
        self,
        plate_text_norm: str,
        camera_ids: Optional[List[str]] = None,
        time_start: Optional[float] = None,
        time_end: Optional[float] = None,
        limit: int = 50
    ) -> List[PlateRead]:
        """Exact match plate query with optional filters."""
        with self.Session() as session:
            query = session.query(PlateRead).filter(
                PlateRead.plate_text_norm == plate_text_norm
            )
            if camera_ids:
                query = query.filter(PlateRead.camera_id.in_(camera_ids))
            if time_start is not None:
                query = query.filter(PlateRead.frame_timestamp >= time_start)
            if time_end is not None:
                query = query.filter(PlateRead.frame_timestamp <= time_end)
            return query.order_by(PlateRead.frame_timestamp.desc()).limit(limit).all()

    def search_fuzzy(
        self,
        plate_query: str,
        camera_ids: Optional[List[str]] = None,
        time_start: Optional[float] = None,
        time_end: Optional[float] = None,
        limit: int = 50
    ) -> List[PlateRead]:
        """Fuzzy plate query using substring/LIKE match fallback."""
        with self.Session() as session:
            query = session.query(PlateRead).filter(
                PlateRead.plate_text_norm.ilike(f"%{plate_query}%")
            )
            if camera_ids:
                query = query.filter(PlateRead.camera_id.in_(camera_ids))
            if time_start is not None:
                query = query.filter(PlateRead.frame_timestamp >= time_start)
            if time_end is not None:
                query = query.filter(PlateRead.frame_timestamp <= time_end)
            return query.order_by(PlateRead.frame_timestamp.desc()).limit(limit).all()
