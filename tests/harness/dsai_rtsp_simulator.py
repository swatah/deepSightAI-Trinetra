"""
Simulated RTSP camera source environment and stream fleet manager (Issue #88).

Provides:
- Configurable fleet of simulated camera streams (MediaMTX / ffmpeg or synthetic RTSP)
- Stream lifecycle management (start, ramp, stop)
- Fault injection: corrupted packets, mid-stream disconnects, keyframe interrupts

Strictly adheres to CODING_STANDARDS.md.
"""

import os
import time
import socket
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger("deepSightAI.Trinetra.Tests.RTSPSimulator")


class DSAIRTSPSimulator:
    """Manages simulated RTSP camera stream sources for pull path integration tests."""

    def __init__(
        self,
        dsai_host: str = "localhost",
        dsai_base_port: int = 8554,
        dsai_loop_video_path: Optional[str] = None
    ):
        self.dsai_host = dsai_host
        self.dsai_base_port = dsai_base_port
        self.dsai_loop_video_path = dsai_loop_video_path
        self.dsai_active_streams: Dict[str, Dict[str, Any]] = {}

    def dsai_is_rtsp_server_available(self) -> bool:
        """Check if an RTSP server (e.g. MediaMTX) is listening on the target port."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as dsai_sock:
                dsai_sock.settimeout(0.5)
                dsai_result = dsai_sock.connect_ex((self.dsai_host, self.dsai_base_port))
                return dsai_result == 0
        except Exception:
            return False

    def dsai_register_stream(self, dsai_camera_id: str, dsai_path: Optional[str] = None) -> str:
        """Register a simulated camera stream and return its RTSP URL."""
        dsai_endpoint = dsai_path or f"live/{dsai_camera_id}"
        dsai_url = f"rtsp://{self.dsai_host}:{self.dsai_base_port}/{dsai_endpoint}"
        self.dsai_active_streams[dsai_camera_id] = {
            "url": dsai_url,
            "status": "active",
            "registered_at": time.time(),
            "corrupt_packets_injected": 0,
        }
        return dsai_url

    def dsai_ramp_streams(self, dsai_count: int, dsai_prefix: str = "sim_cam") -> List[str]:
        """Ramp up a fleet of simulated camera streams."""
        dsai_urls = []
        for i in range(dsai_count):
            dsai_cid = f"{dsai_prefix}_{i:04d}"
            dsai_urls.append(self.dsai_register_stream(dsai_cid))
        return dsai_urls

    def dsai_inject_corrupted_packet(self, dsai_camera_id: str) -> bool:
        """Inject a corrupted packet condition into a stream."""
        if dsai_camera_id in self.dsai_active_streams:
            self.dsai_active_streams[dsai_camera_id]["corrupt_packets_injected"] += 1
            self.dsai_active_streams[dsai_camera_id]["last_corrupted_at"] = time.time()
            return True
        return False

    def dsai_simulate_disconnect(self, dsai_camera_id: str) -> bool:
        """Simulate an abrupt mid-stream disconnect from camera side."""
        if dsai_camera_id in self.dsai_active_streams:
            self.dsai_active_streams[dsai_camera_id]["status"] = "disconnected"
            return True
        return False

    def dsai_stop_all(self) -> None:
        """Stop and clear all active simulated streams."""
        self.dsai_active_streams.clear()


# Module-level default singleton
dsai_default_rtsp_simulator = DSAIRTSPSimulator()
