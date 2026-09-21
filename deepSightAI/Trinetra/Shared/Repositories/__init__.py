"""
Shared repository classes for data access under deepSightAI.Trinetra.Shared.Repositories.
"""

from .Base import BaseRepository
from .VideoRepository import VideoRepository, Video
from .CameraRepository import CameraRepository, Camera
from .PlateRepository import PlateRepository, PlateRead
from .WatchlistRepository import (
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
