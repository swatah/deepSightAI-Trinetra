import uvicorn
import httpx
import ffmpeg
import asyncio
import os
import tempfile
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from minio import Minio

REGISTRY_URL = "http://registry:8000"
SEGMENT_DURATION_SECONDS = 30
MINIO_URL = os.getenv("MINIO_URL", "minio:9000")  # Use Docker DNS
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
VIDEO_BUCKET = "videos"

class VideoSourceRequest(BaseModel):
    video_uri: str  # this is the object key in MinIO

class RtspSourceRequest(BaseModel):
    rtsp_url: str

app = FastAPI(title="Input Source Router")

def fetch_video_from_minio(object_key: str) -> str:
    minio_client = Minio(
        MINIO_URL.replace("http://", "").replace("https://", ""),
        access_key=MINIO_ACCESS_KEY, 
        secret_key=MINIO_SECRET_KEY, 
        secure=False
    )
    with tempfile.NamedTemporaryFile(suffix=os.path.splitext(object_key)[-1], delete=False) as tmpf:
        minio_client.fget_object(VIDEO_BUCKET, object_key, tmpf.name)
        return tmpf.name  # Return the local path

@app.post("/process_video")
async def process_video(request: VideoSourceRequest):
    # Download video from MinIO
    try:
        local_video_path = fetch_video_from_minio(request.video_uri)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Could not fetch video from MinIO: {e}")

    try:
        print(f"Probing video: {local_video_path}")
        probe = ffmpeg.probe(local_video_path)
        duration = float(probe['format']['duration'])
        print(f"Video duration: {duration} seconds")

        segments = []
        for i in range(0, int(duration), SEGMENT_DURATION_SECONDS):
            start_time = i
            segment_dur = min(SEGMENT_DURATION_SECONDS, duration - start_time)
            segments.append({"start": start_time, "duration": segment_dur})
        print(f"Divided video into {len(segments)} segments.")
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
                    "video_uri": request.video_uri,  # Pass MinIO object key downstream
                    "segment_id": i,
                    "start_time": seg['start'],
                    "duration": seg['duration']
                }
                task = client.post(extractor_url, json=job_payload)
                tasks.append(task)
                print(f"Dispatching segment {i+1}/{len(segments)} to {extractor_info['extractor_id']}")
            except httpx.HTTPStatusError as e:
                print(f"Could not get an available extractor: {e.response.text}")
                break

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return {"message": f"Successfully dispatched {len(tasks)} segments for processing."}

@app.post("/process_rtsp_stream")
async def process_rtsp_stream(request: RtspSourceRequest):
    """
    Finds one available extractor and tells it to start monitoring an RTSP stream.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{REGISTRY_URL}/get_available_extractor")
            response.raise_for_status()
            extractor_info = response.json()
            # Note the new endpoint on the extractor
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
