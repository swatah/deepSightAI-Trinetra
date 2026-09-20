import os
import torch
import open_clip
import onnxruntime as ort
from PIL import Image
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, model_validator
from pymilvus import connections, Collection
from typing import List, Optional, Any
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
tokenizer = open_clip.get_tokenizer("ViT-B-32")
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
        try:
            model, _, preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained="laion2b_s34b_b79k"
            )
            model.eval()
            model.to(device)
            logger.info(f"PyTorch model loaded on device: {device}")
        except Exception as e:
            logger.warning(f"Could not load online OpenCLIP model (offline/sandbox): {e}")

from shared.milvus import ensure_tenant_collection, connect_milvus_with_retry, get_collection_name

def get_milvus_collection(tenant_id: str = "default") -> Collection:
    """Connect to Milvus and return tenant collection."""
    return ensure_tenant_collection(
        tenant_id=tenant_id,
        embedding_dim=EMBEDDING_DIM,
        milvus_host=MILVUS_HOST,
        milvus_port=MILVUS_PORT
    )

class SearchRequest(BaseModel):
    query_text: Optional[str] = None
    query: Optional[str] = None
    top_k: int = 10
    tenant_id: str = "default"

    @model_validator(mode="after")
    def check_query_present(self):
        if self.query_text is None and self.query is None:
            raise ValueError("Query text or query is required")
        return self

    def get_query(self) -> str:
        text = self.query_text or self.query or ""
        if not text.strip():
            raise ValueError("Query string cannot be empty")
        return text

class SearchResult(BaseModel):
    video_id: str
    frame_path: str
    score: float
    camera_id: Optional[str] = None
    frame_timestamp: Optional[float] = None

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
            text = tokenizer([request.get_query()]).to(device)

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
        collection = get_milvus_collection(request.tenant_id)
        collection.load()
        
        search_params = {
            "metric_type": "COSINE",
            "params": {"ef": 64}
        }
        
        output_fields = ["video_id", "frame_path"]
        try:
            schema_field_names = [f.name for f in collection.schema.fields]
            if "camera_id" in schema_field_names:
                output_fields.append("camera_id")
            if "frame_timestamp" in schema_field_names:
                output_fields.append("frame_timestamp")
        except Exception:
            pass

        results = collection.search(
            data=[query_embedding.tolist()],
            anns_field="embedding",
            param=search_params,
            limit=request.top_k,
            output_fields=output_fields
        )
        
        # Format results
        search_results = []
        for hit in results[0]:
            search_results.append(SearchResult(
                video_id=hit.entity.get("video_id"),
                frame_path=hit.entity.get("frame_path"),
                score=hit.score,
                camera_id=hit.entity.get("camera_id"),
                frame_timestamp=hit.entity.get("frame_timestamp")
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