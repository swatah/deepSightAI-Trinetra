"""
Shared repository classes for data access.
All repositories must be tenant-aware.
"""

from .base import BaseRepository
from .video_repository import VideoRepository, Video
from .camera_repository import CameraRepository, Camera
from .plate_repository import PlateRepository, PlateRead
from .watchlist_repository import (
    WatchlistRepository, WatchlistEntry,
    AlertRepository, Alert
)

__all__ = [
    "BaseRepository",
    "VideoRepository",
    "Video",
    "CameraRepository",
    "Camera",
    "PlateRepository",
    "PlateRead",
    "WatchlistRepository",
    "WatchlistEntry",
    "AlertRepository",
    "Alert",
]
