import uvicorn
import httpx
import ffmpeg
import asyncio
import os
import tempfile
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from minio import Minio
from datetime import datetime

# --- CONFIGURATION ---
REGISTRY_URL = "http://registry:8000"
SEGMENT_DURATION_SECONDS = 30
MINIO_URL = os.getenv("MINIO_URL", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
VIDEO_BUCKET = "videos"

# --- PYDANTIC MODELS ---
class VideoSourceRequest(BaseModel):
    video_uri: str

class RtspSourceRequest(BaseModel):
    rtsp_url: str

# --- FASTAPI APP INITIALIZATION ---
app = FastAPI(title="Input Source Router")

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

# --- API ENDPOINTS ---
@app.post("/process_video")
async def process_video(request: VideoSourceRequest):
    try:
        local_video_path = fetch_video_from_minio(request.video_uri)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Could not fetch video from MinIO: {e}")

    try:
        probe = ffmpeg.probe(local_video_path)
        duration = float(probe['format']['duration'])
        segments = []
        for i in range(0, int(duration), SEGMENT_DURATION_SECONDS):
            start_time = i
            segment_dur = min(SEGMENT_DURATION_SECONDS, duration - start_time)
            segments.append({"start": start_time, "duration": segment_dur})
    except ffmpeg.Error as e:
        raise HTTPException(status_code=400, detail=f"Failed to probe video file: {e.stderr.decode()}")

    async with httpx.AsyncClient(timeout=30.0) as client:
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
                    "duration": seg['duration']
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
async def process_rtsp_stream(request: RtspSourceRequest):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{REGISTRY_URL}/get_available_extractor")
            response.raise_for_status()
            extractor_info = response.json()
            extractor_url = f"{extractor_info['extractor_url']}/extract_stream"
            job_payload = {"rtsp_url": request.rtsp_url}
            dispatch_response = await client.post(extractor_url, json=job_payload)
            dispatch_response.raise_for_status()
            return {
                "message": "Stream monitoring job dispatched successfully",
                "dispatched_to": extractor_info
            }
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=503, detail="All extractors are currently busy.")
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