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

@app.post("/update_status")
def update_extractor_status(extractor_id: str, status: str):
    """Updates the status of a given extractor."""
    extractor_key = f"extractor:{extractor_id}"
    if not r.exists(extractor_key):
        raise HTTPException(status_code=404, detail="Extractor not found")
    
    # Update the status field in the Hash
    r.hset(extractor_key, "status", status)
    return {"message": "Status updated"}

@app.get("/get_available_extractor")
def get_available_extractor():
    """Finds an available extractor, marks it as busy, and returns its info."""
    # Scan through all extractor keys
    for key in r.scan_iter("extractor:*"):
        extractor_info = r.hgetall(key)
        if extractor_info.get("status") == "available":
            # Atomically mark as busy and return
            r.hset(key, "status", "busy")
            return {
                "extractor_id": extractor_info["extractor_id"],
                "extractor_url": extractor_info["extractor_url"]
            }
    
    raise HTTPException(status_code=503, detail="No available extractors")

@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}