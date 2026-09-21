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

class ExtractorRegister(BaseModel):
    extractor_id: str
    extractor_url: str

class EmbedderRegister(BaseModel):
    embedder_id: str
    embedder_url: str

from deepSightAI.Trinetra.Shared.Middleware import RequestIDMiddleware
from deepSightAI.Trinetra.Shared.ErrorHandlers import register_error_handlers

app = FastAPI(title="Central Registry (Redis)")
app.add_middleware(RequestIDMiddleware)
register_error_handlers(app)

@app.post("/register")
def register_extractor(extractor: ExtractorRegister):
    """Registers or updates an extractor's info and sets its status to available."""
    extractor_key = f"extractor:{extractor.extractor_id}"
    now = str(int(time.time()))
    # Store extractor info in a Redis Hash
    r.hset(extractor_key, mapping={
        "extractor_id": extractor.extractor_id,
        "extractor_url": extractor.extractor_url,
        "status": "available",
        "last_heartbeat": now
    })
    return {"message": f"Extractor {extractor.extractor_id} registered."}

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
def update_extractor_status(extractor_id: str, status: str):
    """Updates the status of a given extractor."""
    extractor_key = f"extractor:{extractor_id}"
    if not r.exists(extractor_key):
        raise HTTPException(status_code=404, detail="Extractor not found")
    
    # Update the status field and last_heartbeat in the Hash
    r.hset(extractor_key, mapping={
        "status": status,
        "last_heartbeat": str(int(time.time()))
    })
    if status == "available":
        r.hdel(extractor_key, "busy_since")
    return {"message": "Status updated"}

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
def heartbeat(worker_id: str, worker_type: str = "extractor"):
    """Periodic worker heartbeat to verify liveness."""
    key = f"{worker_type}:{worker_id}"
    if not r.exists(key):
        raise HTTPException(status_code=404, detail=f"{worker_type} not found")
    r.hset(key, "last_heartbeat", str(int(time.time())))
    return {"status": "ok"}

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