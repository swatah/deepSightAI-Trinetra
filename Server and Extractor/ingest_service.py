"""
T2.2.4: Unified Ingest Service endpoint

Provides a single POST /ingest endpoint that accepts multiple source types
(file upload, RTSP URL, etc.) and dispatches to appropriate handlers.
"""

import os
import uuid
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse
import httpx
from shared.streaming.producer import StreamProducer
from shared.streaming.schema import IngestJobStarted
from datetime import datetime


# --- CONFIGURATION ---
REGISTRY_URL = os.getenv("REGISTRY_URL", "http://registry:8000")
CONTROL_STREAM = "control:ingest"

# --- FASTAPI APP ---
app = FastAPI(
    title="Unified Ingest Service",
    description="Single entry point for video ingestion from various sources"
)


# --- DEPENDENCIES ---

def get_producer() -> StreamProducer:
    """Dependency that provides a StreamProducer instance."""
    return StreamProducer()

def get_extractor() -> dict:
    """
    Dependency that fetches an available extractor from the registry.
    Returns extractor info dict with 'extractor_url'.
    """
    try:
        return {"extractor_url": os.getenv("EXTRACTOR_URL", "http://extractor:8000")}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not get extractor: {e}")


async def publish_event(stream: str, event):
    """Publish an event to a Redis stream."""
    producer = get_producer()
    producer.publish(stream, event)


def get_job_id() -> str:
    """Generate a unique job ID."""
    return str(uuid.uuid4())


# --- HELPER FUNCTIONS ---

def determine_video_id(job_id: str, source_type: str) -> str:
    """Generate a video ID."""
    return job_id


async def dispatch_to_extractor(extractor_url: str, payload: dict):
    """Dispatch a job to an extractor service."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(f"{extractor_url}/extract", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"Extractor returned error: {e.response.text}")
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Could not reach extractor: {e}")


# --- ENDPOINT ---

@app.post("/ingest")
async def ingest_endpoint(
    request: Request,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID")
):
    """
    Ingest a video from various sources.

    Supports:
    - multipart/form-data for file uploads (field: file, source_type='file')
    - application/json for RTSP and other sources (body: source_type, rtsp_url, etc.)

    Returns job_id immediately; processing happens asynchronously.
    """
    # Determine content type and parse accordingly
    content_type = request.headers.get("content-type", "")

    source_type: Optional[str] = None
    file = None
    rtsp_url: Optional[str] = None
    filename: Optional[str] = None

    if "multipart/form-data" in content_type:
        # Parse form data
        form = await request.form()
        source_type = form.get("source_type")
        file = form.get("file")
        rtsp_url = form.get("rtsp_url") if "rtsp_url" in form else None
        if file and hasattr(file, 'filename'):
            filename = file.filename
    elif "application/json" in content_type:
        # Parse JSON body
        try:
            json_data = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")
        source_type = json_data.get("source_type")
        rtsp_url = json_data.get("rtsp_url")
        filename = None  # No file in JSON
    else:
        raise HTTPException(status_code=400, detail="Unsupported content type. Use multipart/form-data or application/json")

    # Validate source_type
    valid_sources = {"file", "rtsp", "hls", "dash", "mjpeg"}
    if source_type not in valid_sources:
        raise HTTPException(status_code=400, detail=f"Invalid source_type. Must be one of {valid_sources}")

    # Determine tenant_id
    tenant_id = x_tenant_id or "default"

    # Generate IDs
    job_id = get_job_id()
    video_id = determine_video_id(job_id, source_type)

    # Prepare source identifier for event
    if source_type == "file":
        source_identifier = filename if filename else (rtsp_url or "unknown")
    elif source_type == "rtsp":
        source_identifier = rtsp_url if rtsp_url else "missing_rtsp_url"
    else:
        source_identifier = "unsupported"

    # Publish IngestJobStarted event
    try:
        event = IngestJobStarted(
            job_id=job_id,
            source_type=source_type,
            source_identifier=source_identifier,
            tenant_id=tenant_id,
            timestamp=datetime.utcnow()
        )
        await publish_event(CONTROL_STREAM, event)
    except Exception as e:
        # Log but don't fail - best effort
        print(f"Warning: Failed to publish IngestJobStarted event: {e}")

    # Route based on source_type
    if source_type == "file":
        if not file:
            raise HTTPException(status_code=400, detail="File upload required for source_type='file'")

        extractor_info = get_extractor()
        extractor_url = extractor_info["extractor_url"]

        # Build payload for extractor
        payload = {
            "job_id": job_id,
            "video_id": video_id,
            "source_type": "file",
            "filename": filename,
        }

        # Dispatch asynchronously
        try:
            import asyncio
            asyncio.create_task(dispatch_to_extractor(extractor_url, payload))
        except Exception as e:
            print(f"Warning: failed to dispatch to extractor: {e}")

        return {
            "job_id": job_id,
            "status": "accepted",
            "video_id": video_id,
            "source_type": source_type,
            "message": "File ingestion started"
        }

    elif source_type == "rtsp":
        if not rtsp_url:
            raise HTTPException(status_code=400, detail="rtsp_url required for source_type='rtsp'")

        extractor_info = get_extractor()
        extractor_url = extractor_info["extractor_url"]

        payload = {
            "job_id": job_id,
            "video_id": video_id,
            "source_type": "rtsp",
            "rtsp_url": rtsp_url
        }

        try:
            import asyncio
            asyncio.create_task(dispatch_to_extractor(extractor_url, payload))
        except Exception as e:
            print(f"Warning: failed to dispatch to extractor: {e}")

        return {
            "job_id": job_id,
            "status": "accepted",
            "video_id": video_id,
            "source_type": source_type,
            "message": "RTSP monitoring started"
        }

    else:
        raise HTTPException(status_code=501, detail=f"source_type '{source_type}' not yet implemented")


@app.get("/ingest/{job_id}/status")
async def get_job_status(job_id: str):
    """
    Optional endpoint to check status of an ingest job.
    """
    return {
        "job_id": job_id,
        "status": "unknown",
        "detail": "Status tracking not yet implemented"
    }
