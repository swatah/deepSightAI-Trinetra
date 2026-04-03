"""
T2.2.6: RtspSourceAdapter

Handles RTSP stream ingestion preparation.
"""

import uuid
from typing import Optional, Dict, Any


class RtspAdapter:
    """
    Adapter for RTSP stream ingestion.

    Prepares RTSP stream monitoring jobs by generating payloads for the extractor.
    The actual stream connection is handled by the extractor (GStreamer pipeline).

    Attributes:
        timeout: Connection timeout in seconds (optional)
        retries: Number of retry attempts for connection (optional)
    """

    def __init__(self, timeout: float = 30.0, retries: int = 3):
        """
        Initialize RtspAdapter.

        Args:
            timeout: Timeout in seconds for RTSP connection attempts
            retries: Number of retry attempts before failing
        """
        self.timeout = timeout
        self.retries = retries

    def prepare(self, rtsp_url: str, job_id: str, video_id: str, tenant_id: str) -> dict:
        """
        Prepare RTSP stream for ingestion.

        Args:
            rtsp_url: RTSP stream URL
            job_id: Unique job identifier
            video_id: Video identifier (stream session ID)
            tenant_id: Tenant identifier

        Returns:
            Dictionary payload for extractor service.
        """
        if not rtsp_url:
            raise ValueError("rtsp_url is required")

        # Basic URL validation - ensure it's a string
        if not isinstance(rtsp_url, str):
            raise TypeError("rtsp_url must be a string")

        # Build payload for extractor
        payload = {
            "job_id": job_id,
            "video_id": video_id,
            "source_type": "rtsp",
            "rtsp_url": rtsp_url,
            "tenant_id": tenant_id,
            "timeout": self.timeout,
            "retries": self.retries
        }

        return payload
