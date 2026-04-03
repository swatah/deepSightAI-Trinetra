"""
VideoRepository: Data access for video metadata.

Stores and retrieves video records within a tenant's schema.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from shared.db import Base
from .base import BaseRepository


class Video(Base):
    """
    Video metadata table, stored in each tenant's schema.

    Columns:
        id: Primary key (auto-increment)
        title: Video title or filename
        duration: Duration in seconds
        source_type: 'upload' or 'rtsp'
        source_path: Path in MinIO or RTSP URL
        created_at: When record was created
        processed_at: When video processing completed (nullable)
    """
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    duration = Column(Integer, nullable=False)  # seconds
    source_type = Column(String(50), nullable=False)  # 'upload' | 'rtsp'
    source_path = Column(String, nullable=False)  # MinIO object key or RTSP URL
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)


class VideoRepository(BaseRepository):
    """Repository for Video entities, tenant-scoped."""

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id)

    def create(self, title: str, duration: int, source_type: str, source_path: str) -> Video:
        """
        Create a new video record.

        Args:
            title: Video title/filename
            duration: Duration in seconds
            source_type: 'upload' or 'rtsp'
            source_path: Storage location or stream URL

        Returns:
            The created Video object with ID.
        """
        video = Video(
            title=title,
            duration=duration,
            source_type=source_type,
            source_path=source_path
        )
        return self._add(video)

    def get(self, video_id: int) -> Video | None:
        """Find video by ID within this tenant."""
        return self._get(Video, id=video_id)

    def list_all(self) -> List[Video]:
        """List all videos for this tenant."""
        return self._list(Video)

    def mark_processed(self, video: Video) -> Video:
        """Mark video as processed."""
        with self.Session() as session:
            # Need to attach video to session
            db_video = session.query(Video).get(video.id)
            if db_video:
                db_video.processed_at = datetime.utcnow()
                session.commit()
                session.refresh(db_video)
                return db_video
        return video

    def delete(self, video: Video) -> None:
        """Delete video record."""
        self._delete(video)
