"""
WatchlistRepository: Data access for watchlists and live alerts.

Stores watchlist targets (plates and reference embeddings) and alert detections.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
import json
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from shared.db import Base
from .base import BaseRepository


class WatchlistEntry(Base):
    """
    Watchlist entry (BOLO target).

    Columns:
        id: Auto-increment primary key
        tenant_id: Tenant identifier
        entry_type: 'plate' | 'person_reid' | 'vehicle_reid'
        plate_text_norm: Target normalized plate text (if entry_type == 'plate')
        reid_reference_pk: Reference object pk from prior detection (if reid)
        reid_embedding_json: Serialized reference embedding vector (if reid)
        label: Reason / description / case identifier
        priority: 'low' | 'medium' | 'high' | 'critical'
        active: Whether entry is actively watched
        created_by: User/analyst identifier
        created_at: Creation timestamp
        expires_at: Optional expiration timestamp
    """
    __tablename__ = "watchlist_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    entry_type = Column(String(32), nullable=False)  # 'plate' | 'person_reid' | 'vehicle_reid'
    plate_text_norm = Column(String(64), nullable=True, index=True)
    reid_reference_pk = Column(String(255), nullable=True)
    reid_embedding_json = Column(Text, nullable=True)
    label = Column(String(255), nullable=False)
    priority = Column(String(32), default="medium", nullable=False)
    active = Column(Boolean, default=True, nullable=False, index=True)
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)


class Alert(Base):
    """
    Live watchlist match alert record.

    Columns:
        id: Auto-increment primary key
        tenant_id: Tenant identifier
        watchlist_entry_id: ID of matched watchlist entry
        video_object_pk: Unique ID of detected object in Milvus/Postgres
        camera_id: Camera where match occurred
        matched_at: Match timestamp
        match_score: Confidence/similarity score (1.0 for exact plate, 0.0-1.0 for Re-ID)
        crop_path: MinIO path of the matching crop image
        acknowledged: Whether alert was reviewed by operator
        acknowledged_by: User identifier who acknowledged
        acknowledged_at: When alert was acknowledged
        created_at: Record creation timestamp
    """
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    watchlist_entry_id = Column(Integer, nullable=False, index=True)
    video_object_pk = Column(String(255), nullable=False, index=True)
    camera_id = Column(String(255), nullable=False, index=True)
    matched_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    match_score = Column(Float, nullable=False)
    crop_path = Column(String(1024), nullable=True)
    acknowledged = Column(Boolean, default=False, nullable=False, index=True)
    acknowledged_by = Column(String(255), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class WatchlistRepository(BaseRepository[WatchlistEntry]):
    """Repository for WatchlistEntry entities, tenant-scoped."""

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id)

    def create(
        self,
        entry_type: str,
        label: str,
        created_by: str,
        plate_text_norm: Optional[str] = None,
        reid_reference_pk: Optional[str] = None,
        reid_embedding: Optional[List[float]] = None,
        priority: str = "medium",
        expires_at: Optional[datetime] = None
    ) -> WatchlistEntry:
        """Create a new watchlist entry."""
        embedding_json = json.dumps(reid_embedding) if reid_embedding is not None else None
        entry = WatchlistEntry(
            tenant_id=self.tenant_id,
            entry_type=entry_type,
            plate_text_norm=plate_text_norm,
            reid_reference_pk=reid_reference_pk,
            reid_embedding_json=embedding_json,
            label=label,
            priority=priority,
            active=True,
            created_by=created_by,
            expires_at=expires_at
        )
        return self._add(entry)

    def get_active_entries(self) -> List[WatchlistEntry]:
        """Get all currently active, unexpired watchlist entries."""
        now = datetime.utcnow()
        with self.Session() as session:
            query = session.query(WatchlistEntry).filter(
                WatchlistEntry.active == True
            )
            entries = query.all()
            return [e for e in entries if e.expires_at is None or e.expires_at > now]

    def set_active(self, entry_id: int, active: bool) -> Optional[WatchlistEntry]:
        """Enable or disable a watchlist entry."""
        with self.Session() as session:
            entry = session.query(WatchlistEntry).get(entry_id)
            if entry:
                entry.active = active
                session.commit()
                session.refresh(entry)
                return entry
        return None


class AlertRepository(BaseRepository[Alert]):
    """Repository for Alert entities, tenant-scoped."""

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id)

    def create(
        self,
        watchlist_entry_id: int,
        video_object_pk: str,
        camera_id: str,
        match_score: float,
        crop_path: Optional[str] = None
    ) -> Alert:
        """Record a newly detected watchlist alert."""
        alert = Alert(
            tenant_id=self.tenant_id,
            watchlist_entry_id=watchlist_entry_id,
            video_object_pk=video_object_pk,
            camera_id=camera_id,
            match_score=match_score,
            crop_path=crop_path,
            acknowledged=False
        )
        return self._add(alert)

    def poll_alerts(self, since_id: int = 0, limit: int = 50) -> List[Alert]:
        """Poll alerts with ID strictly greater than since_id."""
        with self.Session() as session:
            return session.query(Alert).filter(
                Alert.id > since_id
            ).order_by(Alert.id.asc()).limit(limit).all()

    def list_unacknowledged(self, limit: int = 50) -> List[Alert]:
        """List unacknowledged alerts for operators."""
        with self.Session() as session:
            return session.query(Alert).filter(
                Alert.acknowledged == False
            ).order_by(Alert.id.desc()).limit(limit).all()

    def acknowledge(self, alert_id: int, acknowledged_by: str) -> Optional[Alert]:
        """Acknowledge an alert."""
        with self.Session() as session:
            alert = session.query(Alert).get(alert_id)
            if alert:
                alert.acknowledged = True
                alert.acknowledged_by = acknowledged_by
                alert.acknowledged_at = datetime.utcnow()
                session.commit()
                session.refresh(alert)
                return alert
        return None
