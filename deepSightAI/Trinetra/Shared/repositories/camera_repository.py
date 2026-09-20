"""
CameraRepository: Data access for camera registry.

Stores and retrieves camera records within a tenant's schema.
"""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import Column, String, DateTime, Boolean
from ..db import Base
from .base import BaseRepository


class Camera(Base):
    """
    Camera registry table, stored in each tenant's schema.

    Columns:
        id: Stable camera identifier (e.g. "cam-01")
        name: Human-readable camera label
        rtsp_url: RTSP streaming endpoint URL (if live feed)
        location: Physical or logical camera location
        is_active: Whether stream is actively monitored
        created_at: When camera was registered
    """
    __tablename__ = "cameras"

    id = Column(String(255), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    rtsp_url = Column(String(1024), nullable=True)
    location = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CameraRepository(BaseRepository[Camera]):
    """Repository for Camera entities, tenant-scoped."""

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id)

    def create(
        self,
        camera_id: str,
        name: str,
        rtsp_url: Optional[str] = None,
        location: Optional[str] = None,
        is_active: bool = True
    ) -> Camera:
        """Register a new camera."""
        camera = Camera(
            id=camera_id,
            name=name,
            rtsp_url=rtsp_url,
            location=location,
            is_active=is_active
        )
        return self._add(camera)

    def get(self, camera_id: str) -> Optional[Camera]:
        """Find camera by ID within this tenant."""
        return self._get(Camera, id=camera_id)

    def list_all(self, active_only: bool = False) -> List[Camera]:
        """List all cameras for this tenant."""
        if active_only:
            return self._list(Camera, is_active=True)
        return self._list(Camera)

    def update_status(self, camera_id: str, is_active: bool) -> Optional[Camera]:
        """Update active status of a camera."""
        with self.Session() as session:
            camera = session.query(Camera).get(camera_id)
            if camera:
                camera.is_active = is_active
                session.commit()
                session.refresh(camera)
                return camera
        return None
