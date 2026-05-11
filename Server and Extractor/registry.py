import os
import uvicorn
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Connect to Redis using the service name from docker-compose
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

class ExtractorRegister(BaseModel):
    extractor_id: str
    extractor_url: str

class EmbedderRegister(BaseModel):
    embedder_id: str
    embedder_url: str

app = FastAPI(title="Central Registry (Redis)")

@app.post("/register")
def register_extractor(extractor: ExtractorRegister):
    """Registers or updates an extractor's info and sets its status to available."""
    extractor_key = f"extractor:{extractor.extractor_id}"
    # Store extractor info in a Redis Hash
    r.hset(extractor_key, mapping={
        "extractor_id": extractor.extractor_id,
        "extractor_url": extractor.extractor_url,
        "status": "available"
    })
    return {"message": f"Extractor {extractor.extractor_id} registered."}

@app.post("/register_embedder")
def register_embedder(embedder: EmbedderRegister):
    """Registers or updates an embedder's info and sets its status to available."""
    embedder_key = f"embedder:{embedder.embedder_id}"
    # Store embedder info in a Redis Hash
    r.hset(embedder_key, mapping={
        "embedder_id": embedder.embedder_id,
        "embedder_url": embedder.embedder_url,
        "status": "available"
    })
    return {"message": f"Embedder {embedder.embedder_id} registered."}

@app.post("/update_status")
def update_extractor_status(extractor_id: str, status: str):
    """Updates the status of a given extractor."""
    extractor_key = f"extractor:{extractor_id}"
    if not r.exists(extractor_key):
        raise HTTPException(status_code=404, detail="Extractor not found")
    
    # Update the status field in the Hash
    r.hset(extractor_key, "status", status)
    return {"message": "Status updated"}

@app.post("/update_embedder_status")
def update_embedder_status(embedder_id: str, status: str):
    """Updates the status of a given embedder."""
    embedder_key = f"embedder:{embedder_id}"
    if not r.exists(embedder_key):
        raise HTTPException(status_code=404, detail="Embedder not found")
    
    # Update the status field in the Hash
    r.hset(embedder_key, "status", status)
    return {"message": "Embedder status updated"}

@app.get("/get_available_extractor")
def get_available_extractor():
    """Finds an available extractor using round-robin, marks it as busy, and returns its info."""
    # Get all extractor keys
    extractor_keys = []
    for key in r.scan_iter("extractor:*"):
        extractor_keys.append(key)
    
    if not extractor_keys:
        raise HTTPException(status_code=503, detail="No available extractors")
    
    # Extract IDs and sort them for consistent order
    extractor_ids = sorted([key.split(":", 1)[1] for key in extractor_keys])
    
    # Get current index for extractors, default to 0
    index_key = "extractor:index"
    current_index = r.get(index_key)
    if current_index is None:
        current_index = 0
    else:
        current_index = int(current_index)
    
    # Try to find an available extractor starting from current_index
    num_extractors = len(extractor_ids)
    for offset in range(num_extractors):
        idx = (current_index + offset) % num_extractors
        extractor_id = extractor_ids[idx]
        extractor_key = f"extractor:{extractor_id}"
        status = r.hget(extractor_key, "status")
        if status == "available":
            # Mark as busy
            r.hset(extractor_key, "status", "busy")
            # Update index to next position
            r.set(index_key, (idx + 1) % num_extractors)
            # Return the extractor info
            extractor_info = r.hgetall(extractor_key)
            return {
                "extractor_id": extractor_info["extractor_id"],
                "extractor_url": extractor_info["extractor_url"]
            }
    
    # If we get here, no extractor was available
    raise HTTPException(status_code=503, detail="No available extractors")

@app.get("/get_available_embedder")
def get_available_embedder():
    """Finds an available embedder using round-robin, marks it as busy, and returns its info."""
    # Get all embedder keys
    embedder_keys = []
    for key in r.scan_iter("embedder:*"):
        embedder_keys.append(key)
    
    if not embedder_keys:
        raise HTTPException(status_code=503, detail="No available embedders")
    
    # Extract IDs and sort them for consistent order
    embedder_ids = sorted([key.split(":", 1)[1] for key in embedder_keys])
    
    # Get current index for embedders, default to 0
    index_key = "embedder:index"
    current_index = r.get(index_key)
    if current_index is None:
        current_index = 0
    else:
        current_index = int(current_index)
    
    # Try to find an available embedder starting from current_index
    num_embedders = len(embedder_ids)
    for offset in range(num_embedders):
        idx = (current_index + offset) % num_embedders
        embedder_id = embedder_ids[idx]
        embedder_key = f"embedder:{embedder_id}"
        status = r.hget(embedder_key, "status")
        if status == "available":
            # Mark as busy
            r.hset(embedder_key, "status", "busy")
            # Update index to next position
            r.set(index_key, (idx + 1) % num_embedders)
            # Return the embedder info
            embedder_info = r.hgetall(embedder_key)
            return {
                "embedder_id": embedder_info["embedder_id"],
                "embedder_url": embedder_info["embedder_url"]
            }
    
    # If we get here, no embedder was available
    raise HTTPException(status_code=503, detail="No available embedders")

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
    return {"status": "ok"}