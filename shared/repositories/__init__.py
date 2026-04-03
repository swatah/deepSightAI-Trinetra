"""
Shared repository classes for data access.
All repositories must be tenant-aware.
"""

from .base import BaseRepository
from .video_repository import VideoRepository

__all__ = ["BaseRepository", "VideoRepository"]
