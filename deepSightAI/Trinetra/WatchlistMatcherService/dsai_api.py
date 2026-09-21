"""
Watchlist and Alerts REST & Streaming API (WL-27, WL-32, WL-33).

Provides:
- POST, GET, PATCH, DELETE /watchlist (CRUD with tenant scoping & watchlist:write RBAC)
- GET /alerts/poll (Incremental alert polling with presigned thumbnails)
- GET /alerts/stream (Server-Sent Events real-time alert streaming)
- PATCH /alerts/{id}/acknowledge (Operator acknowledgment with immutable audit trail)
"""

import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Request, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from minio import Minio

from deepSightAI.Trinetra.Shared.LoggingSetup import dsai_get_logger
from deepSightAI.Trinetra.Shared.Middleware import require_auth
from deepSightAI.Trinetra.Shared.Streaming.RedisClient import create_redis_client
from deepSightAI.Trinetra.Shared.Repositories.WatchlistRepository import (
    WatchlistRepository,
    AlertRepository,
    WatchlistEntry,
    Alert,
)
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_cache import dsai_get_watchlist_cache
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_consumer import (
    dsai_register_sse_subscriber,
    dsai_unregister_sse_subscriber,
)
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_matcher import dsai_normalize_plate

dsai_logger = dsai_get_logger("deepSightAI.Trinetra.WatchlistMatcherService.dsai_api")

# --- MINIO CONFIGURATION FOR THUMBNAIL URLS ---
DSAI_MINIO_URL = os.getenv("MINIO_URL", "localhost:9000")
DSAI_MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
DSAI_MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
DSAI_FRAME_BUCKET = os.getenv("FRAME_BUCKET", "frames")

_dsai_minio_client: Optional[Minio] = None


def dsai_get_minio() -> Minio:
    global _dsai_minio_client
    if _dsai_minio_client is None:
        dsai_clean_url = DSAI_MINIO_URL.replace("http://", "").replace("https://", "")
        _dsai_minio_client = Minio(
            dsai_clean_url,
            access_key=DSAI_MINIO_ACCESS_KEY,
            secret_key=DSAI_MINIO_SECRET_KEY,
            secure=False
        )
    return _dsai_minio_client


def dsai_presign_thumbnail(dsai_path: Optional[str]) -> Optional[str]:
    """Generate short-TTL presigned URL for crop preview (fail-closed)."""
    if not dsai_path:
        return None
    try:
        dsai_mc = dsai_get_minio()
        return dsai_mc.presigned_get_object(
            DSAI_FRAME_BUCKET, dsai_path, expires=timedelta(seconds=900)
        )
    except Exception as dsai_err:
        dsai_logger.warning(f"MinIO presign error for {dsai_path}: {dsai_err}")
        return None


# --- RBAC DEPENDENCIES (WL-27, UI-89, Plan item 47) ---
def dsai_extract_user_scopes(dsai_user: Dict[str, Any]) -> set:
    """Helper to extract user roles, permissions, and scopes into a unified set."""
    dsai_roles = dsai_user.get("roles", [])
    if not isinstance(dsai_roles, list):
        dsai_roles = [dsai_roles] if dsai_roles else []
    dsai_perms = dsai_user.get("permissions", [])
    if not isinstance(dsai_perms, list):
        dsai_perms = [dsai_perms] if dsai_perms else []
    dsai_scopes = dsai_user.get("scope", dsai_user.get("scopes", []))
    if isinstance(dsai_scopes, str):
        dsai_scopes = dsai_scopes.split()
    elif not isinstance(dsai_scopes, list):
        dsai_scopes = [dsai_scopes] if dsai_scopes else []
    return set(dsai_roles + dsai_perms + dsai_scopes)


def dsai_require_watchlist_write(dsai_user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """Verify authenticated user has watchlist:write permission (WL-27)."""
    dsai_all = dsai_extract_user_scopes(dsai_user)
    if "admin" not in dsai_all and "watchlist:write" not in dsai_all:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission: watchlist:write"
        )
    return dsai_user


def dsai_require_watchlist_read(dsai_user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """Verify authenticated user has watchlist:read permission (Plan item 47)."""
    dsai_all = dsai_extract_user_scopes(dsai_user)
    if not dsai_all.intersection({"admin", "watchlist:read", "watchlist:write"}):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission: watchlist:read"
        )
    return dsai_user


def dsai_require_alerts_read(dsai_user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """Verify authenticated user has alerts:read permission (Plan item 47)."""
    dsai_all = dsai_extract_user_scopes(dsai_user)
    if not dsai_all.intersection({"admin", "alerts:read", "alerts:write", "alerts:acknowledge"}):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission: alerts:read"
        )
    return dsai_user


def dsai_require_alerts_acknowledge(dsai_user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """Verify authenticated user has alerts:acknowledge permission (Plan item 47)."""
    dsai_all = dsai_extract_user_scopes(dsai_user)
    if not dsai_all.intersection({"admin", "alerts:acknowledge"}):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission: alerts:acknowledge"
        )
    return dsai_user


# --- SCHEMAS ---
class WatchlistCreateRequest(BaseModel):
    entry_type: str = Field(..., description="'plate' | 'person_reid' | 'vehicle_reid'")
    label: str = Field(..., description="Description / case reason / label")
    plate_text: Optional[str] = None
    plate_number: Optional[str] = None  # alias
    reid_reference_pk: Optional[str] = None
    reid_embedding: Optional[List[float]] = None
    priority: str = Field(default="medium", description="'low' | 'medium' | 'high' | 'critical'")
    expires_at: Optional[datetime] = None
    active: bool = True


class WatchlistUpdateRequest(BaseModel):
    label: Optional[str] = None
    priority: Optional[str] = None
    active: Optional[bool] = None
    expires_at: Optional[datetime] = None
    plate_text: Optional[str] = None
    reid_embedding: Optional[List[float]] = None


class WatchlistEntryResponse(BaseModel):
    id: int
    tenant_id: str
    entry_type: str
    plate_text_norm: Optional[str] = None
    reid_reference_pk: Optional[str] = None
    has_embedding: bool = False
    label: str
    priority: str
    active: bool
    created_by: str
    created_at: datetime
    expires_at: Optional[datetime] = None


class AlertResponse(BaseModel):
    id: int
    tenant_id: str
    watchlist_entry_id: int
    video_object_pk: str
    camera_id: str
    matched_at: datetime
    match_score: float
    crop_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    acknowledged: bool
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    created_at: datetime


def dsai_serialize_watchlist_entry(dsai_e: WatchlistEntry) -> WatchlistEntryResponse:
    return WatchlistEntryResponse(
        id=dsai_e.id,
        tenant_id=dsai_e.tenant_id,
        entry_type=dsai_e.entry_type,
        plate_text_norm=dsai_e.plate_text_norm,
        reid_reference_pk=dsai_e.reid_reference_pk,
        has_embedding=bool(dsai_e.reid_embedding_json),
        label=dsai_e.label,
        priority=dsai_e.priority,
        active=dsai_e.active,
        created_by=dsai_e.created_by,
        created_at=dsai_e.created_at,
        expires_at=dsai_e.expires_at,
    )


def dsai_serialize_alert(dsai_a: Alert) -> AlertResponse:
    dsai_thumb = dsai_presign_thumbnail(dsai_a.crop_path)
    return AlertResponse(
        id=dsai_a.id,
        tenant_id=dsai_a.tenant_id,
        watchlist_entry_id=dsai_a.watchlist_entry_id,
        video_object_pk=dsai_a.video_object_pk,
        camera_id=dsai_a.camera_id,
        matched_at=dsai_a.matched_at,
        match_score=dsai_a.match_score,
        crop_path=dsai_a.crop_path,
        thumbnail_url=dsai_thumb,
        acknowledged=dsai_a.acknowledged,
        acknowledged_by=dsai_a.acknowledged_by,
        acknowledged_at=dsai_a.acknowledged_at,
        created_at=dsai_a.created_at,
    )


# --- ROUTER DEFINITION ---
dsai_watchlist_router = APIRouter(tags=["watchlist", "alerts"])


# 1. WATCHLIST CRUD (WL-27)
@dsai_watchlist_router.post(
    "/watchlist",
    response_model=WatchlistEntryResponse,
    status_code=status.HTTP_201_CREATED
)
@dsai_watchlist_router.post(
    "/watchlists",
    response_model=WatchlistEntryResponse,
    status_code=status.HTTP_201_CREATED
)
def dsai_create_watchlist_entry(
    dsai_req: WatchlistCreateRequest,
    dsai_user: Dict[str, Any] = Depends(dsai_require_watchlist_write)
):
    """Create a new watchlist entry with tenant scoping and watchlist:write RBAC (WL-27)."""
    dsai_tenant_id = str(dsai_user.get("tenant_id") or "default")
    dsai_user_id = str(dsai_user.get("sub") or dsai_user.get("username") or "operator")

    dsai_target_plate = dsai_req.plate_text or dsai_req.plate_number
    if dsai_req.entry_type == "plate":
        if not dsai_target_plate:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="plate_text or plate_number is required for plate entry_type"
            )
        dsai_target_plate = dsai_normalize_plate(dsai_target_plate)

    dsai_repo = WatchlistRepository(dsai_tenant_id)
    dsai_created = dsai_repo.dsai_create(
        entry_type=dsai_req.entry_type,
        label=dsai_req.label,
        created_by=dsai_user_id,
        plate_text_norm=dsai_target_plate,
        reid_reference_pk=dsai_req.reid_reference_pk,
        reid_embedding=dsai_req.reid_embedding,
        priority=dsai_req.priority,
        expires_at=dsai_req.expires_at,
        active=dsai_req.active
    )

    # Invalidate cache for tenant (WL-30)
    dsai_get_watchlist_cache().dsai_invalidate(dsai_tenant_id)
    return dsai_serialize_watchlist_entry(dsai_created)


@dsai_watchlist_router.get(
    "/watchlist",
    response_model=List[WatchlistEntryResponse]
)
@dsai_watchlist_router.get(
    "/watchlists",
    response_model=List[WatchlistEntryResponse]
)
def dsai_list_watchlist_entries(
    active_only: bool = Query(False, description="Filter active entries only"),
    entry_type: Optional[str] = Query(None, description="Filter by entry_type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    dsai_user: Dict[str, Any] = Depends(dsai_require_watchlist_read)
):
    """List watchlist entries for the authenticated tenant."""
    dsai_tenant_id = str(dsai_user.get("tenant_id") or "default")
    dsai_repo = WatchlistRepository(dsai_tenant_id)
    dsai_entries = dsai_repo.dsai_list_entries(
        active_only=active_only,
        entry_type=entry_type,
        limit=limit,
        offset=offset
    )
    return [dsai_serialize_watchlist_entry(e) for e in dsai_entries]


@dsai_watchlist_router.get(
    "/watchlist/{dsai_id}",
    response_model=WatchlistEntryResponse
)
def dsai_get_watchlist_entry(
    dsai_id: int,
    dsai_user: Dict[str, Any] = Depends(dsai_require_watchlist_read)
):
    """Get single watchlist entry by ID scoped to authenticated tenant."""
    dsai_tenant_id = str(dsai_user.get("tenant_id") or "default")
    dsai_repo = WatchlistRepository(dsai_tenant_id)
    dsai_entry = dsai_repo.dsai_get_by_id(dsai_id)
    if not dsai_entry:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    return dsai_serialize_watchlist_entry(dsai_entry)


@dsai_watchlist_router.patch(
    "/watchlist/{dsai_id}",
    response_model=WatchlistEntryResponse
)
@dsai_watchlist_router.put(
    "/watchlist/{dsai_id}",
    response_model=WatchlistEntryResponse
)
def dsai_update_watchlist_entry(
    dsai_id: int,
    dsai_req: WatchlistUpdateRequest,
    dsai_user: Dict[str, Any] = Depends(dsai_require_watchlist_write)
):
    """Update a watchlist entry for tenant (gated by watchlist:write)."""
    dsai_tenant_id = str(dsai_user.get("tenant_id") or "default")
    dsai_repo = WatchlistRepository(dsai_tenant_id)
    dsai_updated = dsai_repo.dsai_update(
        entry_id=dsai_id,
        label=dsai_req.label,
        priority=dsai_req.priority,
        active=dsai_req.active,
        expires_at=dsai_req.expires_at,
        plate_text_norm=dsai_req.plate_text,
        reid_embedding=dsai_req.reid_embedding
    )
    if not dsai_updated:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    dsai_get_watchlist_cache().dsai_invalidate(dsai_tenant_id)
    return dsai_serialize_watchlist_entry(dsai_updated)


@dsai_watchlist_router.delete(
    "/watchlist/{dsai_id}"
)
def dsai_delete_watchlist_entry(
    dsai_id: int,
    dsai_user: Dict[str, Any] = Depends(dsai_require_watchlist_write)
):
    """Delete a watchlist entry for tenant (gated by watchlist:write)."""
    dsai_tenant_id = str(dsai_user.get("tenant_id") or "default")
    dsai_repo = WatchlistRepository(dsai_tenant_id)
    dsai_deleted = dsai_repo.dsai_delete(dsai_id)
    if not dsai_deleted:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    dsai_get_watchlist_cache().dsai_invalidate(dsai_tenant_id)
    return {"status": "deleted", "id": dsai_id}


# 2. ALERTS POLLING & STREAMING (WL-32, WL-33)
@dsai_watchlist_router.get(
    "/alerts/poll",
    response_model=List[AlertResponse]
)
def dsai_poll_alerts(
    since_id: int = Query(0, ge=0, description="Fetch alerts with ID > since_id"),
    limit: int = Query(50, ge=1, le=200),
    unacknowledged_only: bool = Query(False),
    dsai_user: Dict[str, Any] = Depends(dsai_require_alerts_read)
):
    """Poll alerts incrementally for the authenticated tenant (WL-32)."""
    dsai_tenant_id = str(dsai_user.get("tenant_id") or "default")
    dsai_repo = AlertRepository(dsai_tenant_id)
    dsai_alerts = dsai_repo.dsai_poll_alerts(
        since_id=since_id,
        limit=limit,
        unacknowledged_only=unacknowledged_only
    )
    return [dsai_serialize_alert(a) for a in dsai_alerts]


@dsai_watchlist_router.get("/alerts/stream")
async def dsai_stream_alerts(
    request: Request,
    max_events: Optional[int] = Query(None, description="Optional cap on events for bounded testing"),
    dsai_user: Dict[str, Any] = Depends(dsai_require_alerts_read)
):
    """
    Server-Sent Events (SSE) real-time alert stream (WL-32).
    Streams alerts for the authenticated tenant as they occur across service processes.
    """
    dsai_tenant_id = str(dsai_user.get("tenant_id") or "default")
    dsai_queue: asyncio.Queue = asyncio.Queue()
    dsai_register_sse_subscriber(dsai_queue)

    # Cross-process Redis Pub/Sub subscription (WL-32)
    dsai_stop_event = asyncio.Event()
    dsai_pubsub = None
    dsai_pubsub_task = None

    try:
        dsai_redis = create_redis_client()
        dsai_pubsub = dsai_redis.pubsub()
        dsai_pubsub.subscribe(f"channel:alerts:{dsai_tenant_id}")

        async def dsai_redis_listener():
            while not dsai_stop_event.is_set():
                try:
                    dsai_msg = await asyncio.to_thread(
                        dsai_pubsub.get_message,
                        ignore_subscribe_messages=True,
                        timeout=1.0
                    )
                    if dsai_msg and dsai_msg.get("type") == "message":
                        dsai_raw = dsai_msg.get("data")
                        if dsai_raw:
                            if isinstance(dsai_raw, bytes):
                                dsai_raw = dsai_raw.decode("utf-8")
                            dsai_parsed = json.loads(dsai_raw) if isinstance(dsai_raw, str) else dsai_raw
                            await dsai_queue.put(dsai_parsed)
                except asyncio.CancelledError:
                    break
                except Exception as dsai_err:
                    dsai_logger.debug(f"Redis pubsub read loop notice: {dsai_err}")
                    await asyncio.sleep(0.5)

        dsai_pubsub_task = asyncio.create_task(dsai_redis_listener())
    except Exception as dsai_rc_err:
        dsai_logger.debug(f"Redis Pub/Sub setup skipped or unavailable: {dsai_rc_err}")
        dsai_pubsub = None

    async def dsai_event_generator():
        dsai_yielded_count = 0
        dsai_seen_ids = set()
        try:
            # Send initial keepalive ping
            yield f": connected\n\n"
            dsai_yielded_count += 1
            if max_events is not None and dsai_yielded_count >= max_events:
                return

            while True:
                # Check for client disconnect
                if await request.is_disconnected():
                    break

                try:
                    dsai_alert_data = await asyncio.wait_for(dsai_queue.get(), timeout=15.0)
                    # Filter by tenant
                    if dsai_alert_data.get("tenant_id") == dsai_tenant_id:
                        dsai_alert_pk = dsai_alert_data.get("alert_id") or dsai_alert_data.get("id")
                        if dsai_alert_pk is not None:
                            if dsai_alert_pk in dsai_seen_ids:
                                continue
                            dsai_seen_ids.add(dsai_alert_pk)
                            if len(dsai_seen_ids) > 500:
                                dsai_seen_ids.pop()

                        dsai_json_str = json.dumps(dsai_alert_data)
                        yield f"data: {dsai_json_str}\n\n"
                        dsai_yielded_count += 1
                        if max_events is not None and dsai_yielded_count >= max_events:
                            break
                except asyncio.TimeoutError:
                    # Heartbeat comment to keep connection alive
                    yield f": heartbeat\n\n"
        finally:
            dsai_stop_event.set()
            if dsai_pubsub_task and not dsai_pubsub_task.done():
                dsai_pubsub_task.cancel()
                try:
                    await dsai_pubsub_task
                except (asyncio.CancelledError, Exception):
                    pass
            if dsai_pubsub:
                try:
                    await asyncio.to_thread(dsai_pubsub.close)
                except Exception:
                    pass
            dsai_unregister_sse_subscriber(dsai_queue)

    return StreamingResponse(
        dsai_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )



@dsai_watchlist_router.patch(
    "/alerts/{dsai_alert_id}/acknowledge",
    response_model=AlertResponse
)
def dsai_acknowledge_alert(
    dsai_alert_id: int,
    dsai_user: Dict[str, Any] = Depends(dsai_require_alerts_acknowledge)
):
    """
    Acknowledge an alert and record audit trail with user and timestamp (WL-32, WL-33).
    Gated by alerts:acknowledge RBAC scope (Plan item 47).
    """
    dsai_tenant_id = str(dsai_user.get("tenant_id") or "default")
    dsai_user_id = str(dsai_user.get("sub") or dsai_user.get("username") or "operator")

    dsai_repo = AlertRepository(dsai_tenant_id)
    dsai_ack_alert = dsai_repo.dsai_acknowledge(
        alert_id=dsai_alert_id,
        acknowledged_by=dsai_user_id
    )
    if not dsai_ack_alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    dsai_logger.info(
        f"Alert {dsai_alert_id} acknowledged by '{dsai_user_id}' at {dsai_ack_alert.acknowledged_at}"
    )
    return dsai_serialize_alert(dsai_ack_alert)
