"""
WatchlistRepository: Data access for watchlists and live alerts (DM-7b, WL-27, WL-31, WL-33).

Stores watchlist targets (plates and reference embeddings) and alert detections
with strict multi-tenant isolation and audit trail support.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
import json
import re
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, and_, desc, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from ..DB import Base
from .Base import BaseRepository


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
    __table_args__ = (
        UniqueConstraint("tenant_id", "watchlist_entry_id", "video_object_pk", name="uq_alerts_tenant_wl_pk"),
    )

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
    """Repository for WatchlistEntry entities, tenant-scoped (WL-27)."""

    Session = None

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id)
        if WatchlistRepository.Session is not None:
            self.Session = WatchlistRepository.Session

    def dsai_create(
        self,
        entry_type: str,
        label: str,
        created_by: str,
        plate_text_norm: Optional[str] = None,
        reid_reference_pk: Optional[str] = None,
        reid_embedding: Optional[List[float]] = None,
        priority: str = "medium",
        expires_at: Optional[datetime] = None,
        active: bool = True
    ) -> WatchlistEntry:
        """Create a new watchlist entry with tenant scoping."""
        dsai_clean_plate = None
        if plate_text_norm is not None:
            dsai_clean_plate = re.sub(r"[^A-Z0-9]", "", str(plate_text_norm).strip().upper())

        dsai_embedding_json = json.dumps(reid_embedding) if reid_embedding is not None else None
        dsai_entry = WatchlistEntry(
            tenant_id=self.tenant_id,
            entry_type=entry_type,
            plate_text_norm=dsai_clean_plate,
            reid_reference_pk=reid_reference_pk,
            reid_embedding_json=dsai_embedding_json,
            label=label,
            priority=priority,
            active=active,
            created_by=created_by,
            expires_at=expires_at
        )
        return self._add(dsai_entry)

    create = dsai_create

    def dsai_get_by_id(self, entry_id: int) -> Optional[WatchlistEntry]:
        """Fetch a single watchlist entry strictly scoped to the tenant."""
        with self.Session() as dsai_session:
            return dsai_session.query(WatchlistEntry).filter(
                and_(
                    WatchlistEntry.id == entry_id,
                    WatchlistEntry.tenant_id == self.tenant_id
                )
            ).first()

    get_by_id = dsai_get_by_id
    get = dsai_get_by_id

    def dsai_get_active_entries(self) -> List[WatchlistEntry]:
        """Get all currently active, unexpired watchlist entries strictly for tenant."""
        dsai_now = datetime.utcnow()
        with self.Session() as dsai_session:
            dsai_query = dsai_session.query(WatchlistEntry).filter(
                and_(
                    WatchlistEntry.tenant_id == self.tenant_id,
                    WatchlistEntry.active == True
                )
            )
            dsai_entries = dsai_query.all()
            return [
                dsai_e for dsai_e in dsai_entries
                if dsai_e.expires_at is None or dsai_e.expires_at > dsai_now
            ]

    get_active_entries = dsai_get_active_entries

    def dsai_list_entries(
        self,
        active_only: bool = False,
        entry_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[WatchlistEntry]:
        """List watchlist entries for this tenant with optional filtering."""
        with self.Session() as dsai_session:
            dsai_filters = [WatchlistEntry.tenant_id == self.tenant_id]
            if active_only:
                dsai_filters.append(WatchlistEntry.active == True)
            if entry_type:
                dsai_filters.append(WatchlistEntry.entry_type == entry_type)

            return (
                dsai_session.query(WatchlistEntry)
                .filter(and_(*dsai_filters))
                .order_by(desc(WatchlistEntry.created_at))
                .offset(offset)
                .limit(limit)
                .all()
            )

    list_entries = dsai_list_entries

    def dsai_set_active(self, entry_id: int, active: bool) -> Optional[WatchlistEntry]:
        """Enable or disable a watchlist entry for this tenant."""
        with self.Session() as dsai_session:
            dsai_entry = dsai_session.query(WatchlistEntry).filter(
                and_(
                    WatchlistEntry.id == entry_id,
                    WatchlistEntry.tenant_id == self.tenant_id
                )
            ).first()
            if dsai_entry:
                dsai_entry.active = active
                dsai_session.commit()
                dsai_session.refresh(dsai_entry)
                return dsai_entry
        return None

    set_active = dsai_set_active

    def dsai_update(
        self,
        entry_id: int,
        label: Optional[str] = None,
        priority: Optional[str] = None,
        active: Optional[bool] = None,
        expires_at: Optional[datetime] = None,
        plate_text_norm: Optional[str] = None,
        reid_embedding: Optional[List[float]] = None,
    ) -> Optional[WatchlistEntry]:
        """Update a watchlist entry for this tenant."""
        with self.Session() as dsai_session:
            dsai_entry = dsai_session.query(WatchlistEntry).filter(
                and_(
                    WatchlistEntry.id == entry_id,
                    WatchlistEntry.tenant_id == self.tenant_id
                )
            ).first()
            if not dsai_entry:
                return None

            if label is not None:
                dsai_entry.label = label
            if priority is not None:
                dsai_entry.priority = priority
            if active is not None:
                dsai_entry.active = active
            if expires_at is not None:
                dsai_entry.expires_at = expires_at
            if plate_text_norm is not None:
                dsai_entry.plate_text_norm = re.sub(r"[^A-Z0-9]", "", plate_text_norm.strip().upper())
            if reid_embedding is not None:
                dsai_entry.reid_embedding_json = json.dumps(reid_embedding)

            dsai_session.commit()
            dsai_session.refresh(dsai_entry)
            return dsai_entry

    update = dsai_update

    def dsai_delete(self, entry_id: int) -> bool:
        """Permanently delete a watchlist entry for this tenant."""
        with self.Session() as dsai_session:
            dsai_entry = dsai_session.query(WatchlistEntry).filter(
                and_(
                    WatchlistEntry.id == entry_id,
                    WatchlistEntry.tenant_id == self.tenant_id
                )
            ).first()
            if dsai_entry:
                dsai_session.delete(dsai_entry)
                dsai_session.commit()
                return True
        return False

    delete = dsai_delete


class AlertRepository(BaseRepository[Alert]):
    """Repository for Alert entities, tenant-scoped (WL-31, WL-32, WL-33)."""

    Session = None

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id)
        if AlertRepository.Session is not None:
            self.Session = AlertRepository.Session

    def dsai_create(
        self,
        watchlist_entry_id: int,
        video_object_pk: str,
        camera_id: str,
        match_score: float,
        crop_path: Optional[str] = None
    ) -> Alert:
        """
        Record a newly detected watchlist alert scoped to tenant.
        Idempotent: deduplicates alerts for the same (tenant_id, watchlist_entry_id, video_object_pk).
        """
        with self.Session() as dsai_session:
            # Check for existing alert for this detection and watchlist entry
            dsai_existing = dsai_session.query(Alert).filter(
                and_(
                    Alert.tenant_id == self.tenant_id,
                    Alert.watchlist_entry_id == watchlist_entry_id,
                    Alert.video_object_pk == video_object_pk
                )
            ).first()
            if dsai_existing:
                # Update match_score if newer score is higher
                if float(match_score) > dsai_existing.match_score:
                    dsai_existing.match_score = float(match_score)
                    dsai_session.commit()
                    dsai_session.refresh(dsai_existing)
                return dsai_existing

            dsai_alert = Alert(
                tenant_id=self.tenant_id,
                watchlist_entry_id=watchlist_entry_id,
                video_object_pk=video_object_pk,
                camera_id=camera_id,
                match_score=float(match_score),
                crop_path=crop_path,
                acknowledged=False
            )
            try:
                dsai_session.add(dsai_alert)
                dsai_session.commit()
                dsai_session.refresh(dsai_alert)
                return dsai_alert
            except IntegrityError:
                dsai_session.rollback()
                dsai_conflict = dsai_session.query(Alert).filter(
                    and_(
                        Alert.tenant_id == self.tenant_id,
                        Alert.watchlist_entry_id == watchlist_entry_id,
                        Alert.video_object_pk == video_object_pk
                    )
                ).first()
                if dsai_conflict:
                    return dsai_conflict
                raise

    create = dsai_create

    def dsai_poll_alerts(
        self,
        since_id: int = 0,
        limit: int = 50,
        unacknowledged_only: bool = False
    ) -> List[Alert]:
        """Poll alerts with ID strictly greater than since_id for this tenant (WL-32)."""
        with self.Session() as dsai_session:
            dsai_filters = [
                Alert.tenant_id == self.tenant_id,
                Alert.id > since_id
            ]
            if unacknowledged_only:
                dsai_filters.append(Alert.acknowledged == False)

            return (
                dsai_session.query(Alert)
                .filter(and_(*dsai_filters))
                .order_by(Alert.id.asc())
                .limit(limit)
                .all()
            )

    poll_alerts = dsai_poll_alerts

    def dsai_list_unacknowledged(self, limit: int = 50) -> List[Alert]:
        """List unacknowledged alerts for operators scoped to tenant."""
        with self.Session() as dsai_session:
            return (
                dsai_session.query(Alert)
                .filter(
                    and_(
                        Alert.tenant_id == self.tenant_id,
                        Alert.acknowledged == False
                    )
                )
                .order_by(Alert.id.desc())
                .limit(limit)
                .all()
            )

    list_unacknowledged = dsai_list_unacknowledged

    def dsai_acknowledge(self, alert_id: int, acknowledged_by: str) -> Optional[Alert]:
        """
        Acknowledge an alert and record audit trail (WL-32, WL-33).
        Records acknowledged_by and acknowledged_at.
        """
        with self.Session() as dsai_session:
            dsai_alert = dsai_session.query(Alert).filter(
                and_(
                    Alert.id == alert_id,
                    Alert.tenant_id == self.tenant_id
                )
            ).first()
            if dsai_alert:
                dsai_alert.acknowledged = True
                dsai_alert.acknowledged_by = str(acknowledged_by)
                dsai_alert.acknowledged_at = datetime.utcnow()
                dsai_session.commit()
                dsai_session.refresh(dsai_alert)
                return dsai_alert
        return None

    acknowledge = dsai_acknowledge

    def dsai_get_by_id(self, alert_id: int) -> Optional[Alert]:
        """Get an alert by ID strictly scoped to this tenant."""
        with self.Session() as dsai_session:
            return dsai_session.query(Alert).filter(
                and_(
                    Alert.id == alert_id,
                    Alert.tenant_id == self.tenant_id
                )
            ).first()

    get_by_id = dsai_get_by_id

    def dsai_list_alerts(
        self,
        limit: int = 50,
        offset: int = 0,
        camera_id: Optional[str] = None,
        acknowledged: Optional[bool] = None
    ) -> List[Alert]:
        """List alerts with pagination and optional filters."""
        with self.Session() as dsai_session:
            dsai_filters = [Alert.tenant_id == self.tenant_id]
            if camera_id:
                dsai_filters.append(Alert.camera_id == camera_id)
            if acknowledged is not None:
                dsai_filters.append(Alert.acknowledged == acknowledged)

            return (
                dsai_session.query(Alert)
                .filter(and_(*dsai_filters))
                .order_by(desc(Alert.id))
                .offset(offset)
                .limit(limit)
                .all()
            )

    list_alerts = dsai_list_alerts
