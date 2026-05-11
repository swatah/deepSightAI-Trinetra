import os
import torch
import open_clip
import onnxruntime as ort
from PIL import Image
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pymilvus import connections, Collection
from typing import List
import numpy as np
import logging

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("search-service")

app = FastAPI(title="Video Search API", version="1.0.0")

# Configuration
MILVUS_HOST = os.getenv("MILVUS_HOST", "milvus-standalone")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION", "video_frames")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "512"))
USE_ONNX = os.getenv("USE_ONNX", "1") == "1"
ONNX_MODEL_PATH = os.getenv("ONNX_MODEL_PATH", "models/open_clip_vit_b32.onnx")

# Global variables for model and preprocessing
model = None
preprocess = None
onnx_session = None
device = "cuda" if torch.cuda.is_available() else "cpu"

# Load model (ONNX or PyTorch) for text encoding
if USE_ONNX and os.path.exists(ONNX_MODEL_PATH):
    logger.info(f"Loading ONNX model from {ONNX_MODEL_PATH}...")
    
    # Set up ONNX Runtime providers
    if torch.cuda.is_available():
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        logger.info("ONNX using GPU acceleration")
    else:
        providers = ['CPUExecutionProvider']
        logger.info("ONNX using CPU")
    
    try:
        # Create ONNX session
        onnx_session = ort.InferenceSession(ONNX_MODEL_PATH, providers=providers)
        
        # Get preprocessing transforms without loading the full model
        _, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained=None)
        
        logger.info("✅ ONNX model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load ONNX model: {e}")
        logger.info("Falling back to PyTorch model...")
        USE_ONNX = False
        onnx_session = None

if not USE_ONNX or not os.path.exists(ONNX_MODEL_PATH):
    logger.info("Loading PyTorch OpenCLIP model ViT-B-32...")
    local_pytorch_model = "models/open_clip_pytorch_model.bin"
    if os.path.exists(local_pytorch_model):
        logger.info(f"Using local PyTorch model: {local_pytorch_model}")
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained=local_pytorch_model
        )
    else:
        logger.info("Using online pretrained model: laion2b_s34b_b79k")
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k"
        )
    model.eval()
    model.to(device)
    logger.info(f"PyTorch model loaded on device: {device}")

def get_milvus_collection() -> Collection:
    """Connect to Milvus and return the collection."""
    connections.connect("default", host=MILVUS_HOST, port=MILVUS_PORT)
    
    if not utility.has_collection(COLLECTION_NAME):
        raise HTTPException(status_code=503, detail=f"Milvus collection '{COLLECTION_NAME}' not found")
    
    return Collection(COLLECTION_NAME)

# Import utility after defining get_milvus_collection to avoid circular import
from pymilvus import utility

class SearchRequest(BaseModel):
    query_text: str
    top_k: int = 10

class SearchResult(BaseModel):
    video_id: str
    frame_path: str
    score: float

@app.on_event("startup")
async def startup_event():
    """Initialize connections on startup."""
    logger.info("Search service starting up...")
    try:
        # Test Milvus connection
        collection = get_milvus_collection()
        logger.info(f"Connected to Milvus collection: {COLLECTION_NAME}")
    except Exception as e:
        logger.error(f"Failed to connect to Milvus: {e}")

@app.post("/search/text", response_model=List[SearchResult])
async def search_text(request: SearchRequest):
    """Search for video frames using text query."""
    try:
        # Encode the query text
        with torch.no_grad():
            text = preprocess([request.query_text]).unsqueeze(0).to(device)
            
            if USE_ONNX and onnx_session:
                # ONNX inference path for text
                # Note: For text encoding, we need the text model
                # For simplicity, we'll use PyTorch path for text encoding here
                # In a full implementation, we'd have separate text encoder
                text_features = model.encode_text(text)
                text_features = text_features / text_features.norm(dim=-1, keepdim=True)
                query_embedding = text_features.cpu().numpy().flatten()
            else:
                # PyTorch inference path
                text_features = model.encode_text(text)
                text_features = text_features / text_features.norm(dim=-1, keepdim=True)
                query_embedding = text_features.cpu().numpy().flatten()
        
        # Search Milvus
        collection = get_milvus_collection()
        collection.load()
        
        search_params = {
            "metric_type": "COSINE",
            "params": {"ef": 64}
        }
        
        results = collection.search(
            data=[query_embedding.tolist()],
            anns_field="embedding",
            param=search_params,
            limit=request.top_k,
            output_fields=["video_id", "frame_path"]
        )
        
        # Format results
        search_results = []
        for hit in results[0]:
            search_results.append(SearchResult(
                video_id=hit.entity.get("video_id"),
                frame_path=hit.entity.get("frame_path"),
                score=hit.score
            ))
        
        return search_results
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        collection = get_milvus_collection()
        return {"status": "healthy", "collection": COLLECTION_NAME}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Unhealthy: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)