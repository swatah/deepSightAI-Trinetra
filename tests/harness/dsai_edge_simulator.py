"""
Simulated Edge Device Test Harness with Vendor Profiles (Issue #89).

Supports:
- Vendor Profile A (Hikvision-style: batch size 10, exponential backoff)
- Vendor Profile B (Axis-style: batch size 50, aggressive burst retry)
- Deliberate fault injection:
  - Malformed payload / non-JSON
  - Duplicate event_id (sequential & concurrent race)
  - Clock skew injection (positive and negative)
  - Credential tampering (invalid token, revoked device)
  - Parameter omission (missing required schema fields)
  - Dimension mismatch and unapproved model injection
  - Camera mismatch / unassigned camera submission
  - Abrupt connection drop / timeout simulation

Strictly adheres to CODING_STANDARDS.md.
"""

import copy
import time
import uuid
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass


@dataclass
class DSAIVendorProfile:
    """Hardware vendor operational profile."""
    name: str
    batch_size: int
    max_retries: int
    retry_delay_seconds: float
    backoff_factor: float
    timeout_seconds: float


DSAI_PROFILE_VENDOR_A = DSAIVendorProfile(
    name="Vendor_A_Hikvision_Style",
    batch_size=10,
    max_retries=3,
    retry_delay_seconds=0.1,
    backoff_factor=2.0,
    timeout_seconds=5.0,
)

DSAI_PROFILE_VENDOR_B = DSAIVendorProfile(
    name="Vendor_B_Axis_Style",
    batch_size=50,
    max_retries=5,
    retry_delay_seconds=0.02,
    backoff_factor=1.0,
    timeout_seconds=2.0,
)


class DSAIEdgeDeviceSimulator:
    """Standalone edge device simulator capable of deliberate fault injection and multi-profile operation."""

    def __init__(
        self,
        dsai_device_id: str,
        dsai_tenant_id: str,
        dsai_api_key: str,
        dsai_assigned_cameras: List[str],
        dsai_profile: DSAIVendorProfile = DSAI_PROFILE_VENDOR_A,
        dsai_http_client: Any = None,
        dsai_base_url: str = "http://localhost:8000"
    ):
        self.dsai_device_id = dsai_device_id
        self.dsai_tenant_id = dsai_tenant_id
        self.dsai_api_key = dsai_api_key
        self.dsai_assigned_cameras = dsai_assigned_cameras
        self.dsai_profile = dsai_profile
        self.dsai_http_client = dsai_http_client
        self.dsai_base_url = dsai_base_url
        self.dsai_simulate_network_partition = False
        self.dsai_tampered_token: Optional[str] = None

    def dsai_get_auth_headers(self) -> Dict[str, str]:
        """Generate HTTP headers for edge authentication."""
        dsai_token = self.dsai_tampered_token or self.dsai_api_key
        return {
            "Authorization": f"Bearer {dsai_token}",
            "X-Device-ID": self.dsai_device_id,
            "Content-Type": "application/json",
        }

    def dsai_build_valid_event(
        self,
        dsai_camera_id: Optional[str] = None,
        dsai_event_id: Optional[str] = None,
        dsai_captured_at: Optional[float] = None,
        dsai_vector: Optional[List[float]] = None,
        dsai_dim: int = 512,
        dsai_model_id: str = "ViT-B-32",
        dsai_model_version: str = "1.0"
    ) -> Dict[str, Any]:
        """Construct a schema-compliant edge embedding event."""
        dsai_cam = dsai_camera_id or (self.dsai_assigned_cameras[0] if self.dsai_assigned_cameras else "cam-01")
        dsai_eid = dsai_event_id or f"evt-{uuid.uuid4().hex[:12]}"
        dsai_ts = dsai_captured_at or time.time()
        dsai_emb = dsai_vector or [0.0] * dsai_dim
        return {
            "event_id": dsai_eid,
            "tenant_id": self.dsai_tenant_id,
            "camera_id": dsai_cam,
            "captured_at": dsai_ts,
            "embedding_vector": dsai_emb,
            "embedding_dim": dsai_dim,
            "model_id": dsai_model_id,
            "model_version": dsai_model_version,
            "video_id": f"vid-{dsai_cam}",
            "frame_path": f"{self.dsai_tenant_id}/{dsai_cam}/frame_{dsai_eid}.jpg"
        }

    def dsai_build_batch(self, dsai_count: Optional[int] = None) -> List[Dict[str, Any]]:
        """Construct a batch according to the vendor profile's batch size."""
        dsai_limit = dsai_count or self.dsai_profile.batch_size
        return [self.dsai_build_valid_event() for _ in range(dsai_limit)]

    # --- Fault Injection Helpers ---

    def dsai_inject_malformed_json_payload(self) -> str:
        """Return non-parsable malformed JSON payload."""
        return "{ 'tenant_id': broken json, missing closing brace"

    def dsai_inject_omitted_field(self, dsai_event: Dict[str, Any], dsai_field_to_omit: str) -> Dict[str, Any]:
        """Omit a mandatory schema field."""
        dsai_corrupt = copy.deepcopy(dsai_event)
        dsai_corrupt.pop(dsai_field_to_omit, None)
        return dsai_corrupt

    def dsai_inject_clock_skew(self, dsai_event: Dict[str, Any], dsai_skew_seconds: float) -> Dict[str, Any]:
        """Inject forward or backward clock skew into captured_at."""
        dsai_skewed = copy.deepcopy(dsai_event)
        dsai_skewed["captured_at"] = time.time() + dsai_skew_seconds
        return dsai_skewed

    def dsai_inject_dimension_mismatch(self, dsai_event: Dict[str, Any], dsai_wrong_dim: int = 256) -> Dict[str, Any]:
        """Inject vector dimension that conflicts with model definition."""
        dsai_mismatched = copy.deepcopy(dsai_event)
        dsai_mismatched["embedding_dim"] = dsai_wrong_dim
        dsai_mismatched["embedding_vector"] = [0.0] * dsai_wrong_dim
        return dsai_mismatched

    def dsai_inject_unapproved_model(self, dsai_event: Dict[str, Any]) -> Dict[str, Any]:
        """Inject an unknown or unapproved model ID."""
        dsai_unapproved = copy.deepcopy(dsai_event)
        dsai_unapproved["model_id"] = "unapproved-proprietary-model-x"
        return dsai_unapproved

    def dsai_inject_unassigned_camera(self, dsai_event: Dict[str, Any], dsai_rogue_cam: str = "cam-unauthorized-999") -> Dict[str, Any]:
        """Inject camera ID outside the device's onboarded assignment."""
        dsai_rogue = copy.deepcopy(dsai_event)
        dsai_rogue["camera_id"] = dsai_rogue_cam
        return dsai_rogue

    def dsai_set_revoked_credentials(self) -> None:
        """Simulate sending with an invalid/revoked API key."""
        self.dsai_tampered_token = "edg_revoked_or_invalid_secret_key"

    def dsai_restore_credentials(self) -> None:
        """Restore valid API key."""
        self.dsai_tampered_token = None
