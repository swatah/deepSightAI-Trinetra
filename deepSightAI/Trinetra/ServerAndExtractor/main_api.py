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

# --- AUTH DEPENDENCY ---
from deepSightAI.Trinetra.Shared.Middleware import require_auth, RequestIDMiddleware
from deepSightAI.Trinetra.Shared.ErrorHandlers import register_error_handlers
AUTH_AVAILABLE = True

# --- FASTAPI APP INITIALIZATION ---
app = FastAPI(
    title="Input Source Router",
    dependencies=[Depends(require_auth)]
)
app.add_middleware(RequestIDMiddleware)
register_error_handlers(app)

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
                print(f"Could not get an available extractor: {e.response.text}")
                break

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return {"message": f"Successfully dispatched {len(tasks)} segments for processing."}

@app.post("/process_rtsp_stream")
async def process_rtsp_stream(request: RtspSourceRequest, http_request: Request):
    enforced_tenant_id = dsai_validate_request_tenant(http_request, request.tenant_id)
    # RTSP capacity is per-extractor and numeric (soft/hard limit, current
    # used count), not the binary busy/available claim used for file jobs --
    # one extractor can watch several camera feeds at once. So instead of
    # /get_available_extractor's atomic claim, poll every registered
    # extractor's own /rtsp_status and pick one with room.
    #
    # Extractor endpoints require the same auth this request came in with
    # (they're behind require_auth too), so forward it -- without this every
    # call below 401s whenever auth is actually enabled, since neither this
    # nor any other extractor-dispatch call in this file has ever forwarded
    # the caller's token.
    forward_headers = {}
    incoming_auth = http_request.headers.get("Authorization")
    if incoming_auth:
        forward_headers["Authorization"] = incoming_auth

    async with httpx.AsyncClient(timeout=10.0, headers=forward_headers) as client:
        try:
            services_response = await client.get(f"{REGISTRY_URL}/get_all_services")
            services_response.raise_for_status()
            extractors = services_response.json().get("extractors", [])
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Could not reach registry: {e}")

        if not extractors:
            raise HTTPException(status_code=503, detail="No extractors registered.")

        async def get_status(extractor_info):
            try:
                resp = await client.get(f"{extractor_info['extractor_url']}/rtsp_status")
                resp.raise_for_status()
                return extractor_info, resp.json()
            except httpx.HTTPError:
                return extractor_info, None

        results = await asyncio.gather(*(get_status(e) for e in extractors))

        # Pick the extractor with the most spare RTSP capacity (fewest
        # current_used relative to its effective limit), skipping any that
        # didn't respond or are already at capacity.
        best = None
        best_spare = -1
        for extractor_info, status in results:
            if status is None:
                continue
            spare = status["effective_limit"] - status["current_used"]
            if spare > 0 and spare > best_spare:
                best = extractor_info
                best_spare = spare

        if best is None:
            raise HTTPException(status_code=503, detail="All extractors are at RTSP capacity.")

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
            return {
                "message": "Stream monitoring job dispatched successfully",
                "dispatched_to": best
            }
        except httpx.HTTPStatusError:
            raise HTTPException(status_code=503, detail="Chosen extractor rejected the stream (capacity changed).")
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Could not connect to a service: {e}")

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
            return response.json()
    except Exception as e:
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