import uvicorn
import httpx
try:
    import ffmpeg
except ImportError:
    ffmpeg = None
import asyncio
import os
import tempfile
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel, field_validator
from minio import Minio
from datetime import datetime

# --- CONFIGURATION ---
REGISTRY_URL = os.getenv("REGISTRY_URL", "http://registry:8000")
SEGMENT_DURATION_SECONDS = 30
MINIO_URL = os.getenv("MINIO_URL", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
VIDEO_BUCKET = "videos"

# --- PYDANTIC MODELS ---
class VideoSourceRequest(BaseModel):
    video_uri: str
    tenant_id: str = "default"
    camera_id: str

    @field_validator("camera_id")
    def validate_camera_id(cls, v):
        if not v or not str(v).strip():
            raise ValueError("camera_id is required at ingestion")
        return str(v).strip()

class RtspSourceRequest(BaseModel):
    rtsp_url: str
    tenant_id: str = "default"
    camera_id: str

    @field_validator("camera_id")
    def validate_camera_id(cls, v):
        if not v or not str(v).strip():
            raise ValueError("camera_id is required at ingestion")
        return str(v).strip()

class UploadRequestUrlModel(BaseModel):
    filename: str
    content_type: str = "video/mp4"
    tenant_id: str = "default"
    camera_id: Optional[str] = None

class RtspStopRequest(BaseModel):
    camera_id: Optional[str] = None
    stream_id: Optional[str] = None
    tenant_id: str = "default"

# --- AUTH & SERVICE DEPENDENCIES ---
from deepSightAI.Trinetra.Shared.Middleware import require_auth, RequestIDMiddleware
from deepSightAI.Trinetra.Shared.ErrorHandlers import register_error_handlers
from deepSightAI.Trinetra.Shared.Repositories.CameraRepository import CameraRepository
from deepSightAI.Trinetra.Shared.dsai_circuit_breaker import dsai_check_circuit_breaker, dsai_get_circuit_breaker, CircuitBreakerOpenException
from deepSightAI.Trinetra.Shared.dsai_startup_validation import dsai_validate_startup_config
from deepSightAI.Trinetra.ServerAndExtractor.dsai_edge_ingest import dsai_edge_router

AUTH_AVAILABLE = True

# --- FASTAPI APP INITIALIZATION ---
app = FastAPI(
    title="Input Source Router",
    dependencies=[Depends(require_auth)]
)
app.add_middleware(RequestIDMiddleware)
register_error_handlers(app)
app.include_router(dsai_edge_router)

# --- HELPER FUNCTIONS ---
def fetch_video_from_minio(object_key: str) -> str:
    minio_client = Minio(
        MINIO_URL.replace("http://", "").replace("https://", ""),
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False
    )
    with tempfile.NamedTemporaryFile(suffix=os.path.splitext(object_key)[-1], delete=False) as tmpf:
        minio_client.fget_object(VIDEO_BUCKET, object_key, tmpf.name)
        return tmpf.name

def dsai_validate_request_tenant(http_request: Request, requested_tenant_id: Optional[str]) -> str:
    """Validate that requested tenant_id matches authenticated tenant claim, preventing cross-tenant injection."""
    auth_user = getattr(http_request.state, "user", {}) or {}
    auth_tenant = getattr(http_request.state, "tenant_id", None) or auth_user.get("tenant_id")
    if not auth_tenant:
        return requested_tenant_id or "default"

    user_roles = auth_user.get("roles", []) if isinstance(auth_user, dict) else []
    is_admin = "admin" in user_roles or "system" in user_roles

    if requested_tenant_id and requested_tenant_id != auth_tenant and not is_admin:
        raise HTTPException(
            status_code=403,
            detail=f"Tenant mismatch: authenticated as '{auth_tenant}', cannot submit job for '{requested_tenant_id}'"
        )
    return requested_tenant_id if (requested_tenant_id and is_admin) else auth_tenant


# --- API ENDPOINTS ---
@app.post("/process_video")
async def process_video(request: VideoSourceRequest, http_request: Request):
    enforced_tenant_id = dsai_validate_request_tenant(http_request, request.tenant_id)
    try:
        local_video_path = fetch_video_from_minio(request.video_uri)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Could not fetch video from MinIO: {e}")

    if ffmpeg is None:
        raise HTTPException(status_code=500, detail="ffmpeg is not installed on this system")

    try:
        probe = ffmpeg.probe(local_video_path)
        duration = float(probe['format']['duration'])
        segments = []
        for i in range(0, int(duration), SEGMENT_DURATION_SECONDS):
            start_time = i
            segment_dur = min(SEGMENT_DURATION_SECONDS, duration - start_time)
            segments.append({"start": start_time, "duration": segment_dur})
    except Exception as e:
        err_msg = getattr(e, "stderr", b"").decode() if hasattr(e, "stderr") and e.stderr else str(e)
        raise HTTPException(status_code=400, detail=f"Failed to probe video file: {err_msg}")

    forward_headers = {}
    incoming_auth = http_request.headers.get("Authorization")
    if incoming_auth:
        forward_headers["Authorization"] = incoming_auth

    async with httpx.AsyncClient(timeout=30.0, headers=forward_headers) as client:
        tasks = []
        for i, seg in enumerate(segments):
            try:
                response = await client.get(f"{REGISTRY_URL}/get_available_extractor")
                response.raise_for_status()
                dsai_get_circuit_breaker("registry").dsai_record_success()
                extractor_info = response.json()
                extractor_url = f"{extractor_info['extractor_url']}/extract"
                job_payload = {
                    "video_uri": request.video_uri,
                    "segment_id": i,
                    "start_time": seg['start'],
                    "duration": seg['duration'],
                    "tenant_id": enforced_tenant_id,
                    "camera_id": request.camera_id
                }
                task = client.post(extractor_url, json=job_payload)
                tasks.append(task)
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    dsai_get_circuit_breaker("registry").dsai_record_failure(e)
                print(f"Could not get an available extractor: {e.response.text}")
                break
            except httpx.RequestError as e:
                dsai_get_circuit_breaker("registry").dsai_record_failure(e)
                print(f"Could not reach registry: {e}")
                break

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return {"message": f"Successfully dispatched {len(tasks)} segments for processing."}

@app.post("/process_rtsp_stream")
async def process_rtsp_stream(request: RtspSourceRequest, http_request: Request):
    enforced_tenant_id = dsai_validate_request_tenant(http_request, request.tenant_id)

    # Cross-check camera path assignment (Issue #82, S2)
    try:
        camera_repo = CameraRepository(tenant_id=enforced_tenant_id)
        assigned_path = camera_repo.get_ingestion_path(request.camera_id)
        if assigned_path and assigned_path.strip().lower() == "push":
            raise HTTPException(
                status_code=403,
                detail=f"Camera '{request.camera_id}' is assigned to 'push' path (Issue #82, S2). Central pull extraction is forbidden."
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"[InputRouter] Camera path validation check warning: {e}")

    # Check circuit breaker for registry (Issue #85)
    dsai_check_circuit_breaker("registry")

    forward_headers = {}
    incoming_auth = http_request.headers.get("Authorization")
    if incoming_auth:
        forward_headers["Authorization"] = incoming_auth

    async with httpx.AsyncClient(timeout=10.0, headers=forward_headers) as client:
        # O(log N) placement lookup from Redis sorted set in registry (Issue #74, P5)
        try:
            placement_response = await client.get(f"{REGISTRY_URL}/get_available_rtsp_extractor")
            placement_response.raise_for_status()
            best = placement_response.json()
            dsai_get_circuit_breaker("registry").dsai_record_success()
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500:
                dsai_get_circuit_breaker("registry").dsai_record_failure(e)
            if e.response.status_code == 503:
                raise HTTPException(status_code=503, detail="All extractors are at RTSP stream capacity (Issue #74).")
            raise HTTPException(status_code=e.response.status_code, detail=f"Registry error: {e.response.text}")
        except httpx.RequestError as e:
            dsai_get_circuit_breaker("registry").dsai_record_failure(e)
            raise HTTPException(status_code=503, detail=f"Could not reach registry: {e}")

        try:
            dispatch_response = await client.post(
                f"{best['extractor_url']}/extract_stream",
                json={
                    "rtsp_url": request.rtsp_url,
                    "tenant_id": enforced_tenant_id,
                    "camera_id": request.camera_id
                }
            )
            dispatch_response.raise_for_status()
            dispatch_data = dispatch_response.json()
            stream_id = dispatch_data.get("stream_id", f"rtsp-{request.camera_id}")

            # Record stream assignment in registry for bounded failover tracking (Issue #75, P6)
            try:
                await client.post(
                    f"{REGISTRY_URL}/assign_stream",
                    json={
                        "stream_id": stream_id,
                        "camera_id": request.camera_id,
                        "extractor_id": best.get("extractor_id", "unknown"),
                        "rtsp_url": request.rtsp_url,
                        "tenant_id": enforced_tenant_id
                    }
                )
                dsai_get_circuit_breaker("registry").dsai_record_success()
            except Exception as assign_err:
                dsai_get_circuit_breaker("registry").dsai_record_failure(assign_err)
                print(f"[InputRouter] Warning: failed to record stream assignment: {assign_err}")

            return {
                "message": "Stream monitoring job dispatched successfully",
                "dispatched_to": best,
                "stream_id": stream_id
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503:
                raise HTTPException(status_code=503, detail="Chosen extractor rejected the stream (capacity changed).")
            raise HTTPException(status_code=e.response.status_code, detail=f"Extractor error: {e.response.text}")
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Could not connect to extractor: {e}")


# --- PHASE 0 BACKEND BRIDGES (T0.1.0 / ISSUE #17) ---
@app.post("/upload/request-url")
def dsai_request_upload_url(request: UploadRequestUrlModel, http_request: Request):
    """
    Generate a presigned PUT URL for direct browser-to-MinIO video upload.
    Enforces zero-cloud-SDK constraint on frontend (pure browser fetch(PUT)).
    """
    enforced_tenant_id = dsai_validate_request_tenant(http_request, request.tenant_id)

    from datetime import timedelta
    dsai_safe_filename = os.path.basename(request.filename)
    dsai_timestamp_prefix = int(datetime.utcnow().timestamp())
    dsai_object_name = f"{enforced_tenant_id}/{dsai_timestamp_prefix}_{dsai_safe_filename}"

    dsai_minio_client = Minio(
        MINIO_URL.replace("http://", "").replace("https://", ""),
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False
    )

    try:
        if not dsai_minio_client.bucket_exists(VIDEO_BUCKET):
            dsai_minio_client.make_bucket(VIDEO_BUCKET)

        dsai_presigned_url = dsai_minio_client.presigned_put_object(
            VIDEO_BUCKET,
            dsai_object_name,
            expires=timedelta(minutes=30)
        )
        return {
            "upload_url": dsai_presigned_url,
            "video_uri": dsai_object_name,
            "bucket": VIDEO_BUCKET,
            "tenant_id": enforced_tenant_id,
            "expires_in_seconds": 1800
        }
    except Exception as dsai_err:
        raise HTTPException(status_code=500, detail=f"Failed to generate presigned upload URL: {dsai_err}")


@app.post("/rtsp/stop")
async def dsai_stop_rtsp_stream(request: RtspStopRequest, http_request: Request):
    """
    Stop an active RTSP stream extraction job across registered extractors.
    Accepts either camera_id or stream_id.
    """
    enforced_tenant_id = dsai_validate_request_tenant(http_request, request.tenant_id)
    if not request.camera_id and not request.stream_id:
        raise HTTPException(status_code=400, detail="Either camera_id or stream_id is required to stop stream.")

    forward_headers = {}
    incoming_auth = http_request.headers.get("Authorization")
    if incoming_auth:
        forward_headers["Authorization"] = incoming_auth

    async with httpx.AsyncClient(timeout=10.0, headers=forward_headers) as client:
        try:
            services_response = await client.get(f"{REGISTRY_URL}/get_all_services")
            services_response.raise_for_status()
            dsai_get_circuit_breaker("registry").dsai_record_success()
            extractors = services_response.json().get("extractors", [])
        except httpx.HTTPStatusError as dsai_err:
            if dsai_err.response.status_code >= 500:
                dsai_get_circuit_breaker("registry").dsai_record_failure(dsai_err)
            raise HTTPException(status_code=dsai_err.response.status_code, detail=f"Registry error: {dsai_err.response.text}")
        except httpx.RequestError as dsai_err:
            dsai_get_circuit_breaker("registry").dsai_record_failure(dsai_err)
            raise HTTPException(status_code=500, detail=f"Could not reach registry: {dsai_err}")

        if not extractors:
            raise HTTPException(status_code=503, detail="No extractors registered.")

        dsai_stopped = False
        dsai_details = []
        for dsai_ext_info in extractors:
            try:
                dsai_target_url = None
                if request.stream_id:
                    dsai_target_url = f"{dsai_ext_info['extractor_url']}/stop_stream/{request.stream_id}"
                elif request.camera_id:
                    dsai_target_url = f"{dsai_ext_info['extractor_url']}/stop_camera/{request.camera_id}"

                if dsai_target_url:
                    dsai_resp = await client.post(dsai_target_url)
                    if dsai_resp.status_code == 200:
                        dsai_stopped = True
                        dsai_details.append({
                            "extractor_id": dsai_ext_info.get("extractor_id"),
                            "status": "stopped",
                            "response": dsai_resp.json()
                        })
            except httpx.HTTPError:
                continue

        if not dsai_stopped:
            raise HTTPException(
                status_code=404,
                detail=f"Active stream not found on any extractor for camera_id='{request.camera_id}' stream_id='{request.stream_id}'"
            )

        return {
            "message": "Stream stop signal sent successfully",
            "camera_id": request.camera_id,
            "stream_id": request.stream_id,
            "tenant_id": enforced_tenant_id,
            "details": dsai_details
        }


@app.get("/get_rtsp_frames")
def get_rtsp_frames(bucket_name: str, start_time: datetime, end_time: datetime):
    minio_client = Minio(
        MINIO_URL.replace("http://", "").replace("https://", ""),
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False
    )

    if not minio_client.bucket_exists(bucket_name):
        raise HTTPException(status_code=404, detail="Bucket not found.")

    start_ts_ms = int(start_time.timestamp() * 1000)
    end_ts_ms = int(end_time.timestamp() * 1000)

    matching_frames = []
    objects = minio_client.list_objects(bucket_name, recursive=True)

    for obj in objects:
        try:
            timestamp_str = obj.object_name.split('_')[1].split('.')[0]
            frame_ts_ms = int(timestamp_str)

            if start_ts_ms <= frame_ts_ms <= end_ts_ms:
                presigned_url = minio_client.presigned_get_object(
                    bucket_name,
                    obj.object_name,
                )
                matching_frames.append({
                    "object_name": obj.object_name,
                    "url": presigned_url
                })
        except (IndexError, ValueError):
            continue

    return {"frames": matching_frames}

@app.get("/status")
async def get_system_status():
    """Get the status of all registered services."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{REGISTRY_URL}/get_all_services")
            response.raise_for_status()
            dsai_get_circuit_breaker("registry").dsai_record_success()
            return response.json()
    except Exception as e:
        dsai_get_circuit_breaker("registry").dsai_record_failure(e)
        raise HTTPException(status_code=500, detail=f"Could not fetch system status: {e}")

# --- ADMIN REPLAY ENDPOINT (T2.2.9) ---
@app.post("/admin/replay/{video_id}")
async def replay_video(video_id: str, current_user=Depends(require_auth) if AUTH_AVAILABLE else None):
    """
    Replay all historical FrameReadyEvents for a given video.
    
    This endpoint triggers re-processing of a video by republishing all
    original events to the events:frame_ready stream. The embedder will
    consume these events and re-generate embeddings.
    
    Requires admin authentication.
    
    Args:
        video_id: The video identifier to replay
        
    Returns:
        dict: {"replayed": N, "video_id": video_id}
    """
    # Check admin role if auth available
    if AUTH_AVAILABLE:
        # Assuming current_user is a dict with 'role' or 'roles' field
        user_roles = current_user.get("roles", []) if isinstance(current_user, dict) else []
        if "admin" not in user_roles and current_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin role required")
    
    from deepSightAI.Trinetra.Shared.Streaming.Replay import ReplayService
    service = ReplayService()
    count = service.replay(video_id)
    return {"replayed": count, "video_id": video_id}


# --- HEALTH & READINESS PROBES (REL-63) ---
@app.get("/health")
def dsai_health():
    """Liveness probe (REL-63)."""
    return {"status": "healthy", "service": "ServerAndExtractor.main_api"}


@app.get("/ready")
async def dsai_ready():
    """Readiness probe checking dependencies (REL-63)."""
    checks = {}
    is_ready = True

    try:
        minio_client = Minio(
            MINIO_URL.replace("http://", "").replace("https://", ""),
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=False
        )
        checks["minio"] = "ok"
    except Exception as e:
        checks["minio"] = f"unhealthy: {e}"
        is_ready = False

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{REGISTRY_URL}/health")
            checks["registry"] = "ok" if resp.status_code == 200 else f"status_{resp.status_code}"
    except Exception as e:
        checks["registry"] = f"unreachable: {e}"

    if not is_ready:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks})
    return {"status": "ready", "service": "ServerAndExtractor.main_api", "checks": checks}


@app.get("/health/paths")
def dsai_get_paths_health():
    """Independent health check for pull and push ingestion paths (Issue #83, Moderate 11)."""
    from deepSightAI.Trinetra.Shared.dsai_metrics import dsai_get_per_path_health
    return dsai_get_per_path_health()