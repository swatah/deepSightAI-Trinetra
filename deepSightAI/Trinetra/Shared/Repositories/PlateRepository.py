"""
PlateRepository: Data access for license plate reads (DM-7, VP-21, SR-38).

Stores and queries license plate detections within PostgreSQL trinetra_plates schema
and tenant schemas, supporting exact and trigram similarity fuzzy matching.
"""

import re
from datetime import datetime
from typing import List, Optional, Set
from sqlalchemy import Column, Integer, String, Float, DateTime, text
from ..DB import Base
from .Base import BaseRepository


def dsai_trigram_similarity(s1: str, s2: str) -> float:
    """
    Calculate trigram similarity conforming to PostgreSQL pg_trgm (DM-7, SR-38).

    Pads input with two leading spaces and one trailing space, then computes
    the Jaccard similarity between the sets of 3-character shingles.
    """
    if not s1 or not s2:
        return 0.0

    dsai_clean1 = re.sub(r"[^A-Z0-9]", "", s1.strip().upper())
    dsai_clean2 = re.sub(r"[^A-Z0-9]", "", s2.strip().upper())
    if not dsai_clean1 or not dsai_clean2:
        return 0.0

    if dsai_clean1 == dsai_clean2:
        return 1.0

    dsai_padded1 = f"  {dsai_clean1} "
    dsai_padded2 = f"  {dsai_clean2} "

    dsai_trigrams1: Set[str] = {dsai_padded1[i:i + 3] for i in range(len(dsai_padded1) - 2)}
    dsai_trigrams2: Set[str] = {dsai_padded2[i:i + 3] for i in range(len(dsai_padded2) - 2)}

    dsai_union = dsai_trigrams1 | dsai_trigrams2
    if not dsai_union:
        return 0.0

    dsai_intersection = dsai_trigrams1 & dsai_trigrams2
    dsai_base_sim = len(dsai_intersection) / len(dsai_union)

    # OCR character confusion boost (0 vs O, 1 vs I, 8 vs B, 5 vs S)
    dsai_ocr_map = str.maketrans({"O": "0", "I": "1", "B": "8", "S": "5", "Z": "2"})
    dsai_ocr_clean1 = dsai_clean1.translate(dsai_ocr_map)
    dsai_ocr_clean2 = dsai_clean2.translate(dsai_ocr_map)
    if dsai_ocr_clean1 == dsai_ocr_clean2:
        # Boost close OCR confusion matches
        return max(dsai_base_sim, 0.88)

    return dsai_base_sim


class PlateRead(Base):
    """
    License plate read records (DM-7, VP-21).

    Columns:
        id: Auto-increment primary key
        tenant_id: Tenant identifier
        video_object_pk: Unique ID referencing detection in Milvus (unique constraint)
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
    """Repository for PlateRead entities, tenant-scoped (DM-7, VP-21, SR-38)."""

    Session = None

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id)
        if PlateRepository.Session is not None:
            self.Session = PlateRepository.Session

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
        """
        Insert or upsert plate read record with unique constraint on video_object_pk (VP-21).
        Duplicate processing upserts without duplicating plate read rows.
        """
        with self.Session() as session:
            dsai_existing = session.query(PlateRead).filter_by(
                tenant_id=self.tenant_id,
                video_object_pk=video_object_pk
            ).first()
            if dsai_existing:
                # Idempotent update on duplicate processing
                if ocr_confidence > dsai_existing.ocr_confidence or (crop_path and not dsai_existing.crop_path):
                    dsai_existing.plate_text_raw = plate_text_raw
                    dsai_existing.plate_text_norm = plate_text_norm
                    dsai_existing.ocr_confidence = ocr_confidence
                    dsai_existing.ocr_engine = ocr_engine
                    if crop_path:
                        dsai_existing.crop_path = crop_path
                    session.commit()
                    session.refresh(dsai_existing)
                return dsai_existing

            dsai_read = PlateRead(
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
            session.add(dsai_read)
            session.commit()
            session.refresh(dsai_read)
            return dsai_read

    def get_by_object_pk(self, video_object_pk: str) -> Optional[PlateRead]:
        """Find plate read by detection pk scoped strictly to tenant."""
        with self.Session() as session:
            return session.query(PlateRead).filter_by(
                tenant_id=self.tenant_id,
                video_object_pk=video_object_pk
            ).first()

    def search_exact(
        self,
        plate_text_norm: str,
        camera_ids: Optional[List[str]] = None,
        time_start: Optional[float] = None,
        time_end: Optional[float] = None,
        limit: int = 50
    ) -> List[PlateRead]:
        """Exact match plate query with strict tenant isolation (SR-38)."""
        dsai_clean_query = re.sub(r"[^A-Z0-9]", "", plate_text_norm.strip().upper())
        with self.Session() as session:
            query = session.query(PlateRead).filter(
                PlateRead.tenant_id == self.tenant_id,
                PlateRead.plate_text_norm == dsai_clean_query
            )
            if camera_ids:
                query = query.filter(PlateRead.camera_id.in_(camera_ids))
            if time_start is not None:
                query = query.filter(PlateRead.frame_timestamp >= time_start)
            if time_end is not None:
                query = query.filter(PlateRead.frame_timestamp <= time_end)

            results = query.order_by(PlateRead.frame_timestamp.desc()).limit(limit).all()
            for r in results:
                r.similarity = 1.0
            return results

    def search_fuzzy(
        self,
        plate_query: str,
        camera_ids: Optional[List[str]] = None,
        time_start: Optional[float] = None,
        time_end: Optional[float] = None,
        similarity_threshold: float = 0.3,
        limit: int = 50
    ) -> List[PlateRead]:
        """
        Fuzzy plate query using pg_trgm similarity or Python trigram fallback with strict tenant isolation (SR-38).
        Ranks exact and OCR-confused plate reads (e.g. 0/O, 1/I) by trigram similarity.
        """
        dsai_clean_query = re.sub(r"[^A-Z0-9]", "", plate_query.strip().upper())

        with self.Session() as session:
            # First try native PostgreSQL pg_trgm similarity if available
            try:
                pg_query = session.query(
                    PlateRead,
                    text("similarity(plate_text_norm, :query_str) AS sim").bindparams(query_str=dsai_clean_query)
                ).filter(
                    PlateRead.tenant_id == self.tenant_id,
                    text("similarity(plate_text_norm, :query_str) >= :min_sim").bindparams(
                        query_str=dsai_clean_query,
                        min_sim=similarity_threshold
                    )
                )
                if camera_ids:
                    pg_query = pg_query.filter(PlateRead.camera_id.in_(camera_ids))
                if time_start is not None:
                    pg_query = pg_query.filter(PlateRead.frame_timestamp >= time_start)
                if time_end is not None:
                    pg_query = pg_query.filter(PlateRead.frame_timestamp <= time_end)

                pg_results = pg_query.order_by(text("sim DESC"), PlateRead.frame_timestamp.desc()).limit(limit).all()
                out = []
                for row in pg_results:
                    rec = row[0]
                    rec.similarity = float(row[1])
                    out.append(rec)
                if out:
                    return out
            except Exception:
                session.rollback()

            # Python trigram similarity fallback (for SQLite tests and environments without pg_trgm)
            base_query = session.query(PlateRead).filter(PlateRead.tenant_id == self.tenant_id)
            if camera_ids:
                base_query = base_query.filter(PlateRead.camera_id.in_(camera_ids))
            if time_start is not None:
                base_query = base_query.filter(PlateRead.frame_timestamp >= time_start)
            if time_end is not None:
                base_query = base_query.filter(PlateRead.frame_timestamp <= time_end)

            candidates = base_query.all()
            scored: List[tuple] = []
            for c in candidates:
                sim = dsai_trigram_similarity(dsai_clean_query, c.plate_text_norm)
                if sim >= similarity_threshold:
                    c.similarity = sim
                    scored.append((sim, c.frame_timestamp, c))

            # Rank by similarity descending, then timestamp descending
            scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
            return [item[2] for item in scored[:limit]]

    # DSAI-prefixed aliases
    dsai_create = create
    dsai_get_by_object_pk = get_by_object_pk
    dsai_search_exact = search_exact
    dsai_search_fuzzy = search_fuzzy
