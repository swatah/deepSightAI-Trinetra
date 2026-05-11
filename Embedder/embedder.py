import os
import time
import logging
import tempfile
import httpx
from typing import List
import numpy as np

import torch
import open_clip
import onnxruntime as ort
from PIL import Image
from minio import Minio
from minio.error import S3Error
from pymilvus import (
    connections,
    utility,
    FieldSchema,
    CollectionSchema,
    DataType,
    Collection,
)

# Import streaming components
from shared.streaming.consumer import StreamConsumer
from shared.streaming.schema import FrameReadyEvent

#Milvus variables
MILVUS_HOST = os.getenv("MILVUS_HOST", "milvus-standalone")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")

#Milvus collection details
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION", "video_frames")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "512"))  # ViT-B-32 embedding size

def frame_exists(collection: Collection, video_id: str, frame_path: str) -> bool:
    """Check if a frame already exists in Milvus."""
    try:
        # Query for existing entity with matching video_id and frame_path
        results = collection.query(
            expr=f'video_id == "{video_id}" && frame_path == "{frame_path}"',
            output_fields=["pk"],
            limit=1
        )
        return len(results) > 0
    except Exception as e:
        logger.warning(f"Error checking for existing frame: {e}")
        # If we can't check, assume it doesn't exist to avoid blocking inserts
        return False

#MinIO variables
MINIO_URL = os.getenv("MINIO_URL", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
FRAME_BUCKET = os.getenv("FRAME_BUCKET", "frames")

#Registry variables
REGISTRY_URL = os.getenv("REGISTRY_URL", "http://registry:8000")
EMBEDDER_ID = os.getenv("EMBEDDER_ID", "embedder-1")
EMBEDDER_URL = os.getenv("EMBEDDER_URL", "http://embedder-1:8000")

#Processing markers
PROCESSED_MARKER = ".processed"

FILES_PER_EMBED_BATCH = int(os.getenv("FILES_PER_EMBED_BATCH", "64"))  
INSERT_BATCH_SIZE = int(os.getenv("INSERT_BATCH_SIZE", "1000"))        
SLEEP_NO_WORK_SECONDS = int(os.getenv("SLEEP_NO_WORK_SECONDS", "10"))
SLEEP_ON_ERROR_SECONDS = int(os.getenv("SLEEP_ON_ERROR_SECONDS", "30"))

# ONNX Configuration
USE_ONNX = os.getenv("USE_ONNX", "1") == "1"
ONNX_MODEL_PATH = os.getenv("ONNX_MODEL_PATH", "models/open_clip_vit_b32.onnx")

PIN_MEMORY = os.getenv("PIN_MEMORY", "1") == "1" and torch.cuda.is_available()
USE_AUTOCast = torch.cuda.is_available() 

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("embedder")

# Global variables for model and preprocessing
model = None
preprocess = None
onnx_session = None
device = "cuda" if torch.cuda.is_available() else "cpu"

# Load model (ONNX or PyTorch)
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
    """Connect to Milvus and return the collection, creating it + index if missing."""
    connections.connect("default", host=MILVUS_HOST, port=MILVUS_PORT)

    if utility.has_collection(COLLECTION_NAME):
        logger.info(f"Milvus collection '{COLLECTION_NAME}' already exists.")
        return Collection(COLLECTION_NAME)

    logger.info(f"Milvus collection '{COLLECTION_NAME}' not found. Creating...")

    fields = [
        FieldSchema(name="pk", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="video_id", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="frame_path", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
    ]
    schema = CollectionSchema(fields, description="Video frame embeddings")
    collection = Collection(COLLECTION_NAME, schema)

    # Clip embedding index creation
    try:
        collection.create_index(
            field_name="embedding",
            index_params={
                "index_type": "HNSW",
                "metric_type": "COSINE",
                "params": {"M": 16, "efConstruction": 200},
            },
        )
        collection.create_index(
            field_name="frame_path",
            index_params={"index_type": "Trie"},
        )
    except Exception as e:
        logger.warning(f"Index creation warning (continuing): {e}")

    logger.info("Milvus collection created and indexes built.")
    return collection


def chunk_list(items: List[str], n: int):
    """Yield successive n-sized chunks from a list."""
    for i in range(0, len(items), n):
        yield items[i : i + n]


def get_minio_client():
    """Create and return a MinIO client."""
    clean_minio_url = MINIO_URL.replace("http://", "").replace("https://", "")
    return Minio(clean_minio_url, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)


def list_rtsp_buckets(minio_client: Minio) -> List[str]:
    """List all RTSP frame buckets that match the naming pattern."""
    rtsp_buckets = []
    try:
        buckets = minio_client.list_buckets()
        for bucket in buckets:
            if bucket.name.startswith("frames-rtsp-"):
                rtsp_buckets.append(bucket.name)
    except S3Error as e:
        logger.error(f"Error listing RTSP buckets: {e}")
    return rtsp_buckets


def list_rtsp_frame_objects(minio_client: Minio, bucket_name: str) -> List[str]:
    """List all frame objects in an RTSP bucket."""
    frame_objects = []
    try:
        objects = minio_client.list_objects(bucket_name, recursive=True)
        for obj in objects:
            if obj.object_name.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp')):
                frame_objects.append(obj.object_name)
    except S3Error as e:
        logger.error(f"Error listing frames in RTSP bucket {bucket_name}: {e}")
    return sorted(frame_objects)


def is_rtsp_bucket_processed(minio_client: Minio, bucket_name: str) -> bool:
    """Check if an RTSP bucket has been processed by looking for a marker object."""
    marker_object = PROCESSED_MARKER
    try:
        minio_client.stat_object(bucket_name, marker_object)
        return True
    except S3Error:
        return False


def mark_rtsp_bucket_processed(minio_client: Minio, bucket_name: str):
    """Mark an RTSP bucket as processed by creating a marker object."""
    marker_object = PROCESSED_MARKER
    try:
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(b"processed")
            tmp.flush()
            minio_client.fput_object(bucket_name, marker_object, tmp.name)
        logger.info(f"Marked RTSP bucket {bucket_name} as processed")
    except S3Error as e:
        logger.error(f"Error marking RTSP bucket {bucket_name} as processed: {e}")


def download_rtsp_frame_objects(minio_client: Minio, bucket_name: str, frame_objects: List[str]) -> List[str]:
    """Download frame objects from an RTSP bucket to temporary files and return local paths."""
    local_paths = []
    for frame_object in frame_objects:
        try:
            # Create temporary file
            tmp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
            tmp_file.close()
            
            # Download from MinIO
            minio_client.fget_object(bucket_name, frame_object, tmp_file.name)
            local_paths.append(tmp_file.name)
        except S3Error as e:
            logger.error(f"Error downloading RTSP frame {frame_object} from {bucket_name}: {e}")
    return local_paths


def list_video_prefixes(minio_client: Minio) -> List[str]:
    """List video prefixes (like video folder names) in the MinIO bucket."""
    prefixes = set()
    try:
        objects = minio_client.list_objects(FRAME_BUCKET, recursive=True)
        for obj in objects:
            # Extract video prefix from object names like "video_name/segment_001/frame-00001.jpg"
            parts = obj.object_name.split('/')
            if len(parts) >= 2:
                prefixes.add(parts[0])  # video name prefix
    except S3Error as e:
        logger.error(f"Error listing objects from MinIO: {e}")
        return []
    return list(prefixes)


def list_segments_for_video(minio_client: Minio, video_prefix: str) -> List[str]:
    """List all segment prefixes for a given video."""
    segments = set()
    try:
        objects = minio_client.list_objects(FRAME_BUCKET, prefix=f"{video_prefix}/", recursive=True)
        for obj in objects:
            # Extract segment from object names like "video_name/segment_001/frame-00001.jpg"
            parts = obj.object_name.split('/')
            if len(parts) >= 3:
                segments.add(f"{parts[0]}/{parts[1]}")  # video_name/segment_xxx
    except S3Error as e:
        logger.error(f"Error listing segments for video {video_prefix}: {e}")
        return []
    return list(segments)


def list_frame_objects(minio_client: Minio, segment_prefix: str) -> List[str]:
    """List all frame objects for a given segment prefix."""
    frame_objects = []
    try:
        objects = minio_client.list_objects(FRAME_BUCKET, prefix=f"{segment_prefix}/", recursive=True)
        for obj in objects:
            if obj.object_name.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp')):
                frame_objects.append(obj.object_name)
    except S3Error as e:
        logger.error(f"Error listing frames for segment {segment_prefix}: {e}")
        return []
    return sorted(frame_objects)


def is_segment_processed(minio_client: Minio, segment_prefix: str) -> bool:
    """Check if a segment has been processed by looking for a marker object."""
    marker_object = f"{segment_prefix}/{PROCESSED_MARKER}"
    try:
        minio_client.stat_object(FRAME_BUCKET, marker_object)
        return True
    except S3Error:
        return False


def mark_segment_processed(minio_client: Minio, segment_prefix: str):
    """Mark a segment as processed by creating a marker object."""
    marker_object = f"{segment_prefix}/{PROCESSED_MARKER}"
    try:
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(b"processed")
            tmp.flush()
            minio_client.fput_object(FRAME_BUCKET, marker_object, tmp.name)
        logger.info(f"Marked segment {segment_prefix} as processed")
    except S3Error as e:
        logger.error(f"Error marking segment {segment_prefix} as processed: {e}")


def remove_processed_marker(minio_client: Minio, segment_prefix: str):
    """Remove the processed marker for a segment."""
    marker_object = f"{segment_prefix}/{PROCESSED_MARKER}"
    try:
        minio_client.remove_object(FRAME_BUCKET, marker_object)
        logger.info(f"Removed processed marker for {segment_prefix}")
    except S3Error as e:
        logger.debug(f"Could not remove processed marker for {segment_prefix}: {e}")


def check_segment_has_new_frames(minio_client: Minio, segment_prefix: str) -> bool:
    """Check if a segment has any frame files (excluding the processed marker)."""
    try:
        objects = minio_client.list_objects(FRAME_BUCKET, prefix=f"{segment_prefix}/", recursive=True)
        frame_files = [
            obj.object_name for obj in objects 
            if not obj.object_name.endswith(PROCESSED_MARKER)
        ]
        return len(frame_files) > 0
    except Exception as e:
        logger.error(f"Error checking frames in {segment_prefix}: {e}")
        return False


def download_frame_objects(minio_client: Minio, frame_objects: List[str]) -> List[str]:
    """Download frame objects from MinIO to temporary files and return local paths."""
    local_paths = []
    for frame_object in frame_objects:
        try:
            # Create temporary file
            tmp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
            tmp_file.close()
            
            # Download from MinIO
            minio_client.fget_object(FRAME_BUCKET, frame_object, tmp_file.name)
            local_paths.append(tmp_file.name)
        except S3Error as e:
            logger.error(f"Error downloading frame {frame_object}: {e}")
    return local_paths


def cleanup_temp_files(file_paths: List[str]):
    """Clean up temporary files."""
    for path in file_paths:
        try:
            os.unlink(path)
        except OSError as e:
            logger.warning(f"Could not delete temporary file {path}: {e}")


def delete_frame_objects(minio_client: Minio, frame_objects: List[str]):
    """Delete frame objects from the frames bucket after successful processing."""
    deleted_count = 0
    for frame_object in frame_objects:
        try:
            minio_client.remove_object(FRAME_BUCKET, frame_object)
            deleted_count += 1
            logger.debug(f"Deleted frame: {frame_object}")
        except S3Error as e:
            logger.error(f"Error deleting frame {frame_object}: {e}")
    logger.info(f"Successfully deleted {deleted_count}/{len(frame_objects)} frames from {FRAME_BUCKET}")


def delete_rtsp_frame_objects(minio_client: Minio, bucket_name: str, frame_objects: List[str]):
    """Delete frame objects from an RTSP bucket after successful processing."""
    deleted_count = 0
    for frame_object in frame_objects:
        try:
            minio_client.remove_object(bucket_name, frame_object)
            deleted_count += 1
            logger.debug(f"Deleted RTSP frame: {bucket_name}/{frame_object}")
        except S3Error as e:
            logger.error(f"Error deleting RTSP frame {bucket_name}/{frame_object}: {e}")
    logger.info(f"Successfully deleted {deleted_count}/{len(frame_objects)} frames from {bucket_name}")


@torch.no_grad()
#Normalize and encode images using OpenCLIP
@torch.no_grad()
def encode_images(paths: List[str]) -> torch.Tensor:
    """Encode a list of image paths into a tensor of normalized CLIP features (N, D)."""
    tensors: List[torch.Tensor] = []

    for p in paths:
        try:
            with Image.open(p) as im:
                im = im.convert("RGB")
                t = preprocess(im)
                tensors.append(t)
        except Exception as e:
            logger.error(f"Failed to load/preprocess image '{p}': {e}")

    if not tensors:
        if USE_ONNX and onnx_session:
            return torch.empty((0, EMBEDDING_DIM), dtype=torch.float32)
        else:
            return torch.empty((0, EMBEDDING_DIM), dtype=torch.float32, device=device)

    batch = torch.stack(tensors, dim=0)

    if USE_ONNX and onnx_session:
        # ONNX inference path
        logger.debug(f"Processing {batch.shape[0]} images with ONNX")
        batch_np = batch.numpy()
        onnx_inputs = {onnx_session.get_inputs()[0].name: batch_np}
        onnx_output = onnx_session.run(None, onnx_inputs)[0]
        
        # Convert back to PyTorch tensor and normalize
        feats = torch.from_numpy(onnx_output).float()
        feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats
    else:
        # PyTorch inference path
        logger.debug(f"Processing {batch.shape[0]} images with PyTorch")
        batch = batch.to(device, non_blocking=True)
        
        if USE_AUTOCast:
            with torch.autocast("cuda"):
                feats = model.encode_image(batch)
        else:
            feats = model.encode_image(batch)

    feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats.float()


# Worker function: process a segment (video or RTSP)
def process_segment_frames(minio_client: Minio, collection: Collection, video_id: str, segment_path: str, frame_objects: List[str]):
    """Process frames from a video segment."""
    # Prepare buffers for batched insert
    buf_video_id: List[str] = []
    buf_frame_path: List[str] = []
    buf_embedding: List[List[float]] = []
    processed_frames = []  # Track successfully processed frames for deletion

    # Process frames in chunks to avoid downloading all at once
    for frame_batch in chunk_list(frame_objects, FILES_PER_EMBED_BATCH):
        try:
            # Download frames to temporary files
            local_paths = download_frame_objects(minio_client, frame_batch)
            if not local_paths:
                continue

            # Encode the downloaded frames
            feats = encode_images(local_paths)
            if feats.numel() == 0:
                cleanup_temp_files(local_paths)
                continue

            # Add to buffers
            for frame_obj, vec in zip(frame_batch, feats.cpu().numpy().tolist()):
                # Check for duplicates before adding to buffer
                if not frame_exists(collection, video_id, frame_obj):
                    buf_video_id.append(video_id)
                    buf_frame_path.append(frame_obj)  # Store MinIO object path
                    buf_embedding.append(vec)
                    processed_frames.append(frame_obj)  # Track for deletion
                else:
                    logger.debug(f"Skipping duplicate frame: {video_id}/{frame_obj}")

            # Clean up temporary files
            cleanup_temp_files(local_paths)

            # Insert when buffer is large enough
            if len(buf_video_id) >= INSERT_BATCH_SIZE:
                logger.info(f"Inserting batch of {len(buf_video_id)} vectors into Milvus...")
                try:
                    collection.insert([
                        buf_video_id,
                        buf_frame_path,
                        buf_embedding,
                    ])
                    collection.flush()
                    buf_video_id.clear()
                    buf_frame_path.clear()
                    buf_embedding.clear()
                except Exception as e:
                    logger.error(f"Error inserting batch into Milvus: {e}")
                    raise  # Re-raise to skip deletion for this batch

            # Optional: free GPU memory between mini-batches
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        except Exception as e:
            logger.error(f"Error processing frame batch in {segment_path}: {e}")
            continue

    # Insert any remaining vectors
    if buf_video_id:
        logger.info(f"Inserting final batch of {len(buf_video_id)} vectors into Milvus...")
        try:
            collection.insert([
                buf_video_id,
                buf_frame_path,
                buf_embedding,
            ])
            collection.flush()
        except Exception as e:
            logger.error(f"Error inserting final batch into Milvus: {e}")
            # Don't delete frames if insertion failed
            return

    # Always delete successfully processed frames to save space
    if processed_frames:
        logger.info(f"Deleting {len(processed_frames)} processed frames from {segment_path}")
        delete_frame_objects(minio_client, processed_frames)

    # Check if segment is now empty after deleting all frames
    if not check_segment_has_new_frames(minio_client, segment_path):
        logger.info(f"Segment {segment_path} is now empty, will allow reprocessing")
        # Don't mark as processed if there are no frames left
        # This allows the same segment name to be reused for new videos
    else:
        # Mark segment as processed only if there are still unprocessed frames
        mark_segment_processed(minio_client, segment_path)
        logger.info(f"Finished processing and marked segment as done: {segment_path}")
        
    logger.info(f"Completed processing segment: {segment_path}")


def process_rtsp_frames(minio_client: Minio, collection: Collection, bucket_name: str, frame_objects: List[str]):
    """Process frames from an RTSP bucket."""
    # Extract video ID from bucket name (frames-rtsp-{EXTRACTOR_ID}-{timestamp})
    video_id = bucket_name.replace("frames-rtsp-", "")
    
    # Prepare buffers for batched insert
    buf_video_id: List[str] = []
    buf_frame_path: List[str] = []
    buf_embedding: List[List[float]] = []
    processed_frames = []  # Track successfully processed frames for deletion

    # Process frames in chunks to avoid downloading all at once
    for frame_batch in chunk_list(frame_objects, FILES_PER_EMBED_BATCH):
        try:
            # Download frames to temporary files
            local_paths = download_rtsp_frame_objects(minio_client, bucket_name, frame_batch)
            if not local_paths:
                continue

            # Encode the downloaded frames
            feats = encode_images(local_paths)
            if feats.numel() == 0:
                cleanup_temp_files(local_paths)
                continue

            # Add to buffers
            for frame_obj, vec in zip(frame_batch, feats.cpu().numpy().tolist()):
                # Check for duplicates before adding to buffer
                if not frame_exists(collection, video_id, f"{bucket_name}/{frame_obj}"):
                    buf_video_id.append(video_id)
                    buf_frame_path.append(f"{bucket_name}/{frame_obj}")  # Store full bucket/object path
                    buf_embedding.append(vec)
                    processed_frames.append(frame_obj)  # Track for deletion
                else:
                    logger.debug(f"Skipping duplicate frame: {bucket_name}/{frame_obj}")

            # Clean up temporary files
            cleanup_temp_files(local_paths)

            # Insert when buffer is large enough
            if len(buf_video_id) >= INSERT_BATCH_SIZE:
                logger.info(f"Inserting batch of {len(buf_video_id)} RTSP vectors into Milvus...")
                try:
                    collection.insert([
                        buf_video_id,
                        buf_frame_path,
                        buf_embedding,
                    ])
                    collection.flush()
                    buf_video_id.clear()
                    buf_frame_path.clear()
                    buf_embedding.clear()
                except Exception as e:
                    logger.error(f"Error inserting RTSP batch into Milvus: {e}")
                    raise  # Re-raise to skip deletion for this batch

            # Optional: free GPU memory between mini-batches
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        except Exception as e:
            logger.error(f"Error processing RTSP frame batch in {bucket_name}: {e}")
            continue

    # Insert any remaining vectors
    if buf_video_id:
        logger.info(f"Inserting final batch of {len(buf_video_id)} RTSP vectors into Milvus...")
        try:
            collection.insert([
                buf_video_id,
                buf_frame_path,
                buf_embedding,
            ])
            collection.flush()
        except Exception as e:
            logger.error(f"Error inserting final RTSP batch into Milvus: {e}")
            # Don't delete frames if insertion failed
            return

    # Always delete successfully processed frames to save space
    if processed_frames:
        logger.info(f"Deleting {len(processed_frames)} processed frames from RTSP bucket {bucket_name}")
        delete_rtsp_frame_objects(minio_client, bucket_name, processed_frames)

    # Mark RTSP bucket as processed only after successful inserts and deletions
    mark_rtsp_bucket_processed(minio_client, bucket_name)
    logger.info(f"Finished processing and marked RTSP bucket as done: {bucket_name}")


def register_with_registry():
    """Register this embedder with the central registry."""
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{REGISTRY_URL}/register_embedder",
                json={
                    "embedder_id": EMBEDDER_ID,
                    "embedder_url": EMBEDDER_URL
                }
            )
            response.raise_for_status()
            logger.info(f"Successfully registered embedder {EMBEDDER_ID} with registry")
    except Exception as e:
        logger.error(f"Failed to register with registry: {e}")


def update_embedder_status(status: str):
    """Update this embedder's status in the registry."""
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{REGISTRY_URL}/update_embedder_status",
                params={"embedder_id": EMBEDDER_ID, "status": status}
            )
            response.raise_for_status()
    except Exception as e:
        logger.warning(f"Failed to update embedder status to {status}: {e}")


# ==================== EVENT-DRIVEN MAIN LOOP (T2.2.8) ====================

def process_events():
    """
    Main event loop: consume FrameReadyEvent messages from Redis Stream.
    Replaces the old polling-based process_frames() loop.
    """
    # Initialize connections
    collection = get_milvus_collection()
    minio_client = get_minio_client()
    
    # Create Redis Stream consumer
    consumer = StreamConsumer(
        group_name="embedder-group",
        consumer_id=EMBEDDER_ID,
        redis_client=None  # will create via create_redis_client()
    )
    
    # Mark as available when starting
    update_embedder_status("available")
    
    logger.info("Embedder event consumer started, waiting for FrameReadyEvent messages...")
    
    while True:
        try:
            # Read events from Redis Stream (block up to 5s)
            messages = consumer.read(
                stream_name="events:frame_ready",
                count=10,
                block_ms=5000
            )
            
            if not messages:
                # No messages, continue polling
                continue
            
            for msg in messages:
                try:
                    # Parse event
                    event = FrameReadyEvent.model_validate_json(msg.data["event"])
                    logger.info(f"Processing event: {event.video_id} / {event.segment_path}")
                    
                    # Determine event type and dispatch
                    if event.event_type == "frame_ready":
                        # Event contains segment_path (for file-based) or rtsp_bucket
                        if event.segment_path:
                            # File-based video segment
                            # List frames for this segment
                            frame_objects = list_frame_objects(minio_client, event.segment_path)
                            if frame_objects:
                                process_segment_frames(
                                    minio_client, collection,
                                    event.video_id, event.segment_path, frame_objects
                                )
                        elif event.rtsp_bucket:
                            # RTSP stream
                            frame_objects = list_rtsp_frame_objects(minio_client, event.rtsp_bucket)
                            if frame_objects:
                                process_rtsp_frames(
                                    minio_client, collection,
                                    event.rtsp_bucket, frame_objects
                                )
                    
                    # Acknowledge message after successful processing
                    consumer.ack("events:frame_ready", msg.id)
                    
                except Exception as e:
                    logger.error(f"Failed to process event {msg.id}: {e}")
                    # Do NOT ack – message will be redelivered
                    # Continue with next message
                    continue
        
        except Exception as e:
            logger.exception(f"Consumer error: {e}")
            update_embedder_status("error")
            time.sleep(5)  # backoff before reconnecting
            # Recreate consumer on error? For now continue


if __name__ == "__main__":
    # Register with registry on startup
    register_with_registry()
    
    # Start event-driven processing
    process_events()