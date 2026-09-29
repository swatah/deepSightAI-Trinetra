import os
import uvicorn
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Connect to Redis using the service name from docker-compose
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

import time

# Atomically discover, round-robin-select, and claim an available extractor/embedder.
# Includes automatic reclaim of zombie "busy" workers that have timed out.
_CLAIM_AVAILABLE_SCRIPT = r.register_script("""
local prefix = ARGV[1]
local now = tonumber(ARGV[2] or "0")
local timeout = tonumber(ARGV[3] or "180")
local keys = redis.call("KEYS", prefix .. ":*")
if #keys == 0 then
    return nil
end
local ids = {}
for _, key in ipairs(keys) do
    table.insert(ids, string.sub(key, string.len(prefix) + 2))
end
table.sort(ids)
local num = #ids
local current_index = tonumber(redis.call("GET", KEYS[1]) or "0") % num
for offset = 0, num - 1 do
    local idx = (current_index + offset) % num
    local instance_id = ids[idx + 1]
    local key = prefix .. ":" .. instance_id
    local status = redis.call("HGET", key, "status")
    local last_heartbeat = tonumber(redis.call("HGET", key, "last_heartbeat") or "0")
    local busy_since = tonumber(redis.call("HGET", key, "busy_since") or "0")
    local hb_check = last_heartbeat > 0 and last_heartbeat or busy_since
    -- Reclaim worker only if its heartbeat has ceased for longer than timeout (worker crashed or dead)
    if status == "busy" and hb_check > 0 and (now - hb_check) > timeout then
        status = "available"
        redis.call("HSET", key, "status", "available")
        redis.call("HDEL", key, "busy_since")
    end
    if status == "available" then
        redis.call("HSET", key, "status", "busy", "busy_since", tostring(now), "last_heartbeat", tostring(now))
        redis.call("SET", KEYS[1], (idx + 1) % num)
        local url = redis.call("HGET", key, prefix .. "_url")
        return {instance_id, url}
    end
end
return nil
""")


def _claim_available(prefix: str, index_key: str, timeout_seconds: int = 180):
    """Runs _CLAIM_AVAILABLE_SCRIPT and returns [id, url], or None if nothing's available."""
    now = int(time.time())
    return _CLAIM_AVAILABLE_SCRIPT(keys=[index_key], args=[prefix, str(now), str(timeout_seconds)])

import json
import threading
import httpx
from typing import Optional, List, Dict, Any

class ExtractorRegister(BaseModel):
    extractor_id: str
    extractor_url: str
    capacity: Optional[int] = 6
    active_streams: Optional[int] = 0
    decoder: Optional[str] = "avdec_h264"
    hw_accelerated: Optional[bool] = False

class EmbedderRegister(BaseModel):
    embedder_id: str
    embedder_url: str

class StreamAssignment(BaseModel):
    stream_id: str
    camera_id: str
    extractor_id: str
    rtsp_url: str
    tenant_id: str = "default"

from deepSightAI.Trinetra.Shared.Middleware import RequestIDMiddleware
from deepSightAI.Trinetra.Shared.ErrorHandlers import register_error_handlers
from deepSightAI.Trinetra.Shared.Metrics import (
    dsai_record_pull_stream_count,
    dsai_record_pull_error
)

app = FastAPI(title="Central Registry (Redis)")
app.add_middleware(RequestIDMiddleware)
register_error_handlers(app)

DSAI_HEARTBEAT_TTL_SECONDS = 60
DSAI_MAX_FAILOVER_BATCH = 5
DSAI_SPARE_CAPACITY_SET = "registry:extractors:spare_capacity"
DSAI_STREAM_ASSIGNMENTS_HASH = "registry:stream_assignments"


@app.post("/register")
def register_extractor(extractor: ExtractorRegister):
    """Registers or updates an extractor's info and load/capacity (Issue #74)."""
    extractor_key = f"extractor:{extractor.extractor_id}"
    now = str(int(time.time()))
    capacity = int(extractor.capacity or 6)
    active = int(extractor.active_streams or 0)
    spare = max(0, capacity - active)

    # Store extractor info in a Redis Hash
    r.hset(extractor_key, mapping={
        "extractor_id": extractor.extractor_id,
        "extractor_url": extractor.extractor_url,
        "status": "available" if spare > 0 else "busy",
        "capacity": str(capacity),
        "active_streams": str(active),
        "spare_capacity": str(spare),
        "decoder": str(extractor.decoder or "avdec_h264"),
        "last_heartbeat": now
    })

    # Proactively index into sorted set by spare capacity for O(log N) discovery (P5)
    r.zadd(DSAI_SPARE_CAPACITY_SET, {extractor.extractor_id: spare})

    return {"message": f"Extractor {extractor.extractor_id} registered.", "spare_capacity": spare}

@app.post("/register_embedder")
def register_embedder(embedder: EmbedderRegister):
    """Registers or updates an embedder's info and sets its status to available."""
    embedder_key = f"embedder:{embedder.embedder_id}"
    now = str(int(time.time()))
    # Store embedder info in a Redis Hash
    r.hset(embedder_key, mapping={
        "embedder_id": embedder.embedder_id,
        "embedder_url": embedder.embedder_url,
        "status": "available",
        "last_heartbeat": now
    })
    return {"message": f"Embedder {embedder.embedder_id} registered."}

@app.post("/update_status")
def update_extractor_status(
    extractor_id: str,
    status: str,
    capacity: Optional[int] = None,
    active_streams: Optional[int] = None
):
    """Updates the status and load of a given extractor."""
    extractor_key = f"extractor:{extractor_id}"
    if not r.exists(extractor_key):
        raise HTTPException(status_code=404, detail="Extractor not found")

    mapping = {
        "status": status,
        "last_heartbeat": str(int(time.time()))
    }
    if capacity is not None:
        mapping["capacity"] = str(capacity)
    if active_streams is not None:
        mapping["active_streams"] = str(active_streams)

    r.hset(extractor_key, mapping=mapping)
    if status == "available":
        r.hdel(extractor_key, "busy_since")

    # Update sorted set
    raw = r.hgetall(extractor_key)
    c = int(raw.get("capacity", 6))
    a = int(raw.get("active_streams", 0))
    spare = max(0, c - a) if status != "draining" else 0
    r.zadd(DSAI_SPARE_CAPACITY_SET, {extractor_id: spare})

    return {"message": "Status updated", "spare_capacity": spare}

@app.post("/update_embedder_status")
def update_embedder_status(embedder_id: str, status: str):
    """Updates the status of a given embedder."""
    embedder_key = f"embedder:{embedder_id}"
    if not r.exists(embedder_key):
        raise HTTPException(status_code=404, detail="Embedder not found")
    
    # Update the status field and last_heartbeat in the Hash
    r.hset(embedder_key, mapping={
        "status": status,
        "last_heartbeat": str(int(time.time()))
    })
    if status == "available":
        r.hdel(embedder_key, "busy_since")
    return {"message": "Embedder status updated"}

@app.post("/heartbeat")
def heartbeat(
    worker_id: str,
    worker_type: str = "extractor",
    capacity: Optional[int] = None,
    active_streams: Optional[int] = None,
    extractor_url: Optional[str] = None
):
    """Periodic worker heartbeat to verify liveness and refresh load capacity (Issue #74)."""
    key = f"{worker_type}:{worker_id}"
    now_ts = int(time.time())
    if not r.exists(key):
        if worker_type == "extractor" and extractor_url:
            r.hset(key, mapping={
                "extractor_id": worker_id,
                "extractor_url": extractor_url,
                "capacity": str(capacity or 6),
                "active_streams": str(active_streams or 0),
                "last_heartbeat": str(now_ts)
            })
        else:
            raise HTTPException(status_code=404, detail=f"{worker_type} not found")

    if capacity is not None or active_streams is not None:
        mapping = {"last_heartbeat": str(now_ts)}
        if capacity is not None:
            mapping["capacity"] = str(capacity)
        if active_streams is not None:
            mapping["active_streams"] = str(active_streams)
        r.hset(key, mapping=mapping)
    else:
        r.hset(key, "last_heartbeat", str(now_ts))

    if worker_type == "extractor":
        c = capacity if capacity is not None else int(r.hget(key, "capacity") or 6)
        a = active_streams if active_streams is not None else int(r.hget(key, "active_streams") or 0)
        spare = max(0, c - a)
        r.zadd(DSAI_SPARE_CAPACITY_SET, {worker_id: spare})

    return {"status": "ok"}


@app.get("/get_available_rtsp_extractor")
def dsai_get_available_rtsp_extractor():
    """
    O(log N) lookup picking the healthy extractor with the highest spare RTSP capacity (Issue #74, P5).
    Excludes extractors with expired heartbeats or zero capacity.
    Fails closed with 503 if unreachable or full.
    """
    now_ts = int(time.time())
    try:
        candidates = r.zrevrangebyscore(DSAI_SPARE_CAPACITY_SET, max="+inf", min=1, start=0, num=20)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Registry discovery unavailable: {e}")

    if not candidates:
        raise HTTPException(status_code=503, detail="All extractors are at RTSP stream capacity.")

    for extractor_id in candidates:
        key = f"extractor:{extractor_id}"
        try:
            ext_data = r.hgetall(key)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Registry discovery unavailable: {e}")
        if not ext_data:
            try:
                r.zrem(DSAI_SPARE_CAPACITY_SET, extractor_id)
            except Exception:
                pass
            continue

        # Heartbeat TTL check
        last_hb = int(ext_data.get("last_heartbeat") or 0)
        if (now_ts - last_hb) > DSAI_HEARTBEAT_TTL_SECONDS:
            # Stale / crashed node, prune from placement
            try:
                r.zrem(DSAI_SPARE_CAPACITY_SET, extractor_id)
            except Exception:
                pass
            continue

        if ext_data.get("status") == "draining":
            try:
                r.zrem(DSAI_SPARE_CAPACITY_SET, extractor_id)
            except Exception:
                pass
            continue

        cap = int(ext_data.get("capacity", 6))
        act = int(ext_data.get("active_streams", 0))
        computed_spare = max(0, cap - act)
        try:
            score = r.zscore(DSAI_SPARE_CAPACITY_SET, extractor_id)
            spare = int(score) if score is not None and str(score).isdigit() else computed_spare
        except Exception:
            spare = computed_spare

        if spare > 0:
            return {
                "extractor_id": extractor_id,
                "extractor_url": ext_data.get("extractor_url"),
                "spare_capacity": spare,
                "capacity": cap,
                "active_streams": act
            }

    raise HTTPException(status_code=503, detail="No healthy extractors available with spare RTSP capacity.")

get_available_rtsp_extractor = dsai_get_available_rtsp_extractor


@app.post("/assign_stream")
def dsai_assign_stream(assignment: StreamAssignment):
    """Record an active RTSP stream assignment for bounded failover tracking (Issue #75)."""
    val = {
        "stream_id": assignment.stream_id,
        "camera_id": assignment.camera_id,
        "extractor_id": assignment.extractor_id,
        "rtsp_url": assignment.rtsp_url,
        "tenant_id": assignment.tenant_id,
        "assigned_at": time.time(),
        "status": "active"
    }
    r.hset(DSAI_STREAM_ASSIGNMENTS_HASH, assignment.stream_id, json.dumps(val))
    return {"status": "assigned", "stream_id": assignment.stream_id}

assign_stream = dsai_assign_stream


@app.post("/unassign_stream")
def dsai_unassign_stream(stream_id: str):
    """Remove a finished RTSP stream assignment (Issue #75)."""
    r.hdel(DSAI_STREAM_ASSIGNMENTS_HASH, stream_id)
    return {"status": "unassigned", "stream_id": stream_id}

unassign_stream = dsai_unassign_stream


@app.post("/reconcile_streams")
def dsai_reconcile_streams():
    """
    Reconciliation loop: detects orphaned RTSP streams whose extractor has died/timed out,
    and redispatches them to extractors with spare capacity (Issue #75, P6).
    Rate-limited to MAX_FAILOVER_BATCH per tick. Sets bounded pending state if capacity is full.
    """
    now_ts = int(time.time())
    all_assignments = r.hgetall(DSAI_STREAM_ASSIGNMENTS_HASH)
    reassigned = []
    pending_streams = []

    orphaned = []
    for stream_id, val_str in all_assignments.items():
        try:
            val = json.loads(val_str)
        except Exception:
            continue

        if val.get("status") == "failover_pending":
            pending_streams.append(stream_id)
            continue

        extractor_id = val.get("extractor_id")
        ext_data = r.hgetall(f"extractor:{extractor_id}")
        last_hb = int(ext_data.get("last_heartbeat") or 0) if ext_data else 0

        # If extractor missing or expired heartbeat > TTL
        if not ext_data or (now_ts - last_hb) > DSAI_HEARTBEAT_TTL_SECONDS:
            orphaned.append(val)

    # Rate-limit reassignment to prevent storm (Issue #75)
    batch_to_reassign = orphaned[:DSAI_MAX_FAILOVER_BATCH]

    for stream_info in batch_to_reassign:
        try:
            # Find extractor with spare capacity
            target = get_available_rtsp_extractor()
            target_url = target["extractor_url"]

            # Dispatch stream to new extractor
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    f"{target_url}/extract_stream",
                    json={
                        "rtsp_url": stream_info["rtsp_url"],
                        "tenant_id": stream_info["tenant_id"],
                        "camera_id": stream_info["camera_id"]
                    }
                )
                resp.raise_for_status()
                res_data = resp.json()
                new_stream_id = res_data.get("stream_id", stream_info["stream_id"])

            # Update assignment
            r.hdel(DSAI_STREAM_ASSIGNMENTS_HASH, stream_info["stream_id"])
            stream_info["extractor_id"] = target["extractor_id"]
            stream_info["stream_id"] = new_stream_id
            stream_info["status"] = "active"
            stream_info["reassigned_at"] = now_ts
            r.hset(DSAI_STREAM_ASSIGNMENTS_HASH, new_stream_id, json.dumps(stream_info))
            reassigned.append(stream_info["camera_id"])
        except HTTPException as e:
            if e.status_code == 503:
                # No spare capacity anywhere -> transition to bounded pending state (P6)
                stream_info["status"] = "failover_pending"
                stream_info["pending_since"] = now_ts
                r.hset(DSAI_STREAM_ASSIGNMENTS_HASH, stream_info["stream_id"], json.dumps(stream_info))
                pending_streams.append(stream_info["camera_id"])
                dsai_record_pull_error("failover_pending_capacity_exhausted")
        except Exception as gen_err:
            print(f"[Reconciliation] Error reassigning stream {stream_info.get('stream_id')}: {gen_err}")

    return {
        "status": "ok",
        "reassigned": reassigned,
        "orphaned_detected": len(orphaned),
        "reassigned_in_batch": len(reassigned),
        "reassigned_cameras": reassigned,
        "pending_cameras": pending_streams,
    }

reconcile_streams = dsai_reconcile_streams


def _dsai_start_reconciliation_thread(interval: float = 20.0):
    """Background daemon thread running stream reconciliation loop."""
    def _loop():
        while True:
            try:
                dsai_reconcile_streams()
            except Exception:
                pass
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True, name="stream-reconciliation")
    t.start()
    return t


@app.on_event("startup")
def dsai_registry_startup():
    """Start stream reconciliation daemon on startup."""
    _dsai_start_reconciliation_thread()


@app.get("/get_available_extractor")
def get_available_extractor():
    """Finds an available extractor using round-robin, atomically marks it busy, and returns its info."""
    result = _claim_available("extractor", "extractor_index")
    if result is None:
        raise HTTPException(status_code=503, detail="No available extractors")
    extractor_id, extractor_url = result
    return {"extractor_id": extractor_id, "extractor_url": extractor_url}

@app.get("/get_available_embedder")
def get_available_embedder():
    """Finds an available embedder using round-robin, atomically marks it busy, and returns its info."""
    result = _claim_available("embedder", "embedder_index")
    if result is None:
        raise HTTPException(status_code=503, detail="No available embedders")
    embedder_id, embedder_url = result
    return {"embedder_id": embedder_id, "embedder_url": embedder_url}

@app.get("/get_all_services")
def get_all_services():
    """Get status of all registered services."""
    services = {"extractors": [], "embedders": []}
    
    # Get all extractors
    for key in r.scan_iter("extractor:*"):
        extractor_info = r.hgetall(key)
        services["extractors"].append(extractor_info)
    
    # Get all embedders  
    for key in r.scan_iter("embedder:*"):
        embedder_info = r.hgetall(key)
        services["embedders"].append(embedder_info)
    
    return services

@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "ServerAndExtractor.registry"}


@app.get("/ready")
def ready_check():
    """Readiness check endpoint (REL-63)."""
    try:
        r.ping()
        return {"status": "ready", "service": "ServerAndExtractor.registry"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Redis unreachable: {e}")