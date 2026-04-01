# ClipSight Architecture Guide

## Overview

ClipSight is a distributed video content search system that enables semantic search through video frames using natural language queries. The system processes uploaded videos, extracts frames, generates vector embeddings using CLIP, and provides similarity-based search capabilities.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User Interface (Streamlit)                  │
│                         Port: 8501 (Streamlit default)             │
└─────────────────┬───────────────────────────────────────────────────┘
                  │ HTTP Requests
                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Main API Router (FastAPI)                        │
│                    Port: 8080                                       │
│  - Video ingestion                                                  │
│  - Video segmentation (30s chunks)                                 │
│  - RTSP stream coordination                                        │
│  - Service discovery                                               │
└─────────────┬───────────────────────────────────────────────────────┘
              │ Dispatches to
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Extractor Services (FastAPI + GStreamer)              │
│              Ports: 8001, 8002, 8003 (scalable)                   │
│  - Frame extraction (1 FPS)                                        │
│  - JPEG encoding                                                   │
│  - Uploads to MinIO                                                │
└─────────────┬───────────────────────────────────────────────────────┘
              │ Frames stored in
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      MinIO Object Storage                          │
│                      Port: 9000                                    │
│  Buckets:                                                          │
│  - videos (uploaded source videos)                                │
│  - frames (extracted frames - temporary)                          │
│  - frames-rtsp-* (RTSP stream frames)                            │
└─────────────┬───────────────────────────────────────────────────────┘
              │ Polls for new frames
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Embedder Service (Python)                        │
│                   Port: 8001 (internal)                            │
│  - OpenCLIP ViT-B-32 model (512-dim embeddings)                   │
│  - ONNX Runtime GPU acceleration (optional)                       │
│  - Batch processing                                                │
│  - Deletes frames after embedding                                 │
└─────────────┬───────────────────────────────────────────────────────┘
              │ Stores embeddings
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 Milvus Vector Database                             │
│                 Port: 19530                                        │
│  - HNSW index (Cosine similarity)                                 │
│  - Collection: video_frames                                       │
│  - Fields: pk, video_id, frame_path, embedding                    │
└─────────────────────────────────────────────────────────────────────┘

Additional Infrastructure:
┌─────────────────────────────────────────────────────────────────────┐
│              Central Registry (Redis)                              │
│              Port: 8000                                            │
│  - Service discovery for extractors/embedders                     │
│  - Status tracking (available/busy)                               │
│  - Load balancing                                                 │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Main API Router (`Server and Extractor/main_api.py`)
**Role**: Entry point for all video processing requests

**Responsibilities**:
- Accept video uploads (MP4) via `/process_video`
- Accept RTSP stream requests via `/process_rtsp_stream`
- Probe videos with FFmpeg to get duration
- Split videos into 30-second segments
- Query registry for available extractors
- Dispatch segment jobs to extractors (parallel)
- Serve frame retrieval for RTSP: `/get_rtsp_frames`
- System status monitoring: `/status`

**Key Configuration**:
```python
SEGMENT_DURATION_SECONDS = 30
MINIO_URL = "minio:9000"
REGISTRY_URL = "http://registry:8000"
```

### 2. Extractor Service (`Server and Extractor/extractor.py`)
**Role**: Frame extraction workers (horizontally scalable)

**Responsibilities**:
- Register with central registry on startup
- Pull video segments from MinIO
- Extract 1 frame per second using GStreamer
- Encode frames as JPEG
- Upload frames to MinIO with structured paths:
  - File-based: `{video_name}/segment_{id:04d}/frame-{n}.jpg`
  - RTSP: `frames-rtsp-{extractor_id}-{timestamp}/...`
- Update registry status (busy/available)
- Support graceful shutdown via signal handling

**Two Modes**:
1. **File extraction** (`/extract`): Processes predefined segments
2. **RTSP extraction** (`/extract_stream`): Continuous capture from RTSP

**GStreamer Pipelines**:
```bash
# File extraction (1 FPS)
uridecodebin ! videoconvert ! videorate ! video/x-raw,framerate=1/1 ! jpegenc ! multifilesink

# RTSP extraction (1/5 FPS = 0.2 FPS = 1 frame every 5 seconds)
rtspsrc latency=0 ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! videorate ! video/x-raw,framerate=1/5 ! jpegenc ! appsink
```

**Why 1/5 FPS for RTSP?**: Bandwidth conservation for long-running streams.

### 3. Embedder Service (`Embedder/embedder.py`)
**Role**: Convert frames to embeddings and store in vector database

**Responsibilities**:
- Continuous polling loop (checks every 10s when idle)
- Scan MinIO buckets for new frame segments
- Detect reprocessing scenarios (new frames added to old segments)
- Download frames in batches (default: 32 images/batch)
- Generate embeddings using OpenCLIP ViT-B-32
- Insert into Milvus in batches (default: 500 vectors)
- Delete frames from MinIO after successful embedding
- Mark segments/RTSP buckets as `.processed` when done
- Report status to registry (available/busy)

**Model Support**:
- **Preferred**: ONNX Runtime (GPU or CPU)
  - Faster inference
  - Lower memory footprint
  - Automatic export from PyTorch via `export_to_onnx.py`
- **Fallback**: PyTorch + OpenCLIP
  - Downloads `laion2b_s34b_b79k` if no local model

**Smart Reprocessing**:
If a segment already marked `.processed` but new frames detected, the embedder automatically:
1. Removes the old `.processed` marker
2. Processes the new frames
3. Re-inserts embeddings (may create duplicates - need deduplication in future)

### 4. User Interface (`UI/ui.py`)
**Role**: Streamlit web app for user interaction

**Features**:
- Video upload (MP4)
- RTSP stream initiation
- Text-based semantic search (calls query API at port 8081 - not in this repo)
- Image upload (placeholder - not implemented)
- PySceneDetect integration for scene detection
- Responsive grid display of results

**Configuration** (must edit before use):
```python
SERVER_IP = "<YOUR_SERVER_LAPTOP_IP>"  # Change this!
API_URL = f"http://{SERVER_IP}:8080"
QUERY_API_URL = f"http://{SERVER_IP}:8081"
```

**Note**: The query API (search endpoint) is NOT in this repository. It would need to be implemented separately to query Milvus.

### 5. Central Registry (`Server and Extractor/registry.py`)
**Role**: Service discovery and load balancing

**Storage**: Redis in-memory key-value store

**Data Model**:
```python
# Extractor keys: extractor:{id} → Hash with {extractor_id, extractor_url, status}
# Embedder keys: embedder:{id} → Hash with {embedder_id, embedder_url, status}
```

**Endpoints**:
- `POST /register`: Register extractor (sets status=available)
- `POST /register_embedder`: Register embedder
- `POST /update_status`: Update service status (available/busy)
- `GET /get_available_extractor`: Find and lock an available extractor
- `GET /get_available_embedder`: Find and lock an available embedder
- `GET /get_all_services`: System status overview
- `GET /health`: Health check

**Load Balancing**: Simple first-available scan (could be improved with round-robin).

### 6. Supporting Services

#### MinIO (Object Storage)
- S3-compatible object storage
- Stores: videos, extracted frames, RTSP frames
- Bucket structure:
  ```
  videos/
    └── {uuid}-{filename}.mp4

  frames/
    └── {video_name}/segment_0000/frame-00001.jpg
    └── {video_name}/segment_0000/frame-00002.jpg
    └── ...

  frames-rtsp-{extractor_id}-{timestamp}/
    └── frame_{ms}.jpg
    └── ...
  ```

#### Milvus (Vector Database)
- Stores 512-dim CLIP embeddings
- Collection: `video_frames`
- Indexes:
  - `embedding`: HNSW (M=16, efConstruction=200) with Cosine metric
  - `frame_path`: Trie index for filtering

#### Redis
- Stores service registry data
- Auto-eviction not configured (assumes stable service lifecycle)

## Data Flow: End-to-End Example

### Video Upload Path:

1. **User** uploads `myvideo.mp4` via Streamlit UI
2. **UI** → `PUT /videos/{uuid}-myvideo.mp4` to MinIO
3. **UI** → `POST /process_video` to Main API (port 8080) with `{"video_uri": "uuid-myvideo.mp4"}`
4. **Main API**:
   - Downloads video from MinIO to temp file
   - Uses FFmpeg to probe duration (e.g., 90s)
   - Creates 3 segments: [0-30s, 30-60s, 60-90s]
   - For each segment, calls `GET /get_available_extractor` from registry
   - Gets an extractor URL (e.g., `extractor-1:8001`)
   - Dispatches `POST /extract` with segment metadata
5. **Extractor** (e.g., `extractor-1`):
   - Downloads segment video from MinIO
   - Cuts exact segment using FFmpeg
   - Extracts frames (1 FPS) via GStreamer
   - Uploads frames to MinIO: `myvideo/segment_0000/frame-00001.jpg`, etc.
   - Returns `202 Accepted`
6. **Embedder** (polling loop):
   - Detects new segment: `myvideo/segment_0000/`
   - Downloads all frames in batch (up to 32 at a time)
   - Computes embeddings via OpenCLIP
   - Inserts into Milvus (video_id="myvideo", frame_path="myvideo/segment_0000/frame-00001.jpg")
   - Deletes frames from MinIO
   - Creates `.processed` marker
7. **Search** (separate query service needed):
   - User enters "dogs playing"
   - Query service calls Milvus `search()` with CLIP text embedding
   - Returns top-k frames with video_id, frame_path
   - UI requests presigned URLs from MinIO to display images

## Configuration & Environment Variables

### Main API & Extractor Docker Compose (`Server and Extractor/docker-compose.extractor.yml`)
Services: redis, minio, registry, input-router (main API), extractor-1/2/3

**Extractor environment**:
- `REGISTRY_URL`: Registry service URL (default: `http://registry:8000`)
- `MINIO_URL`: MinIO endpoint (default: `http://minio:9000`)
- `EXTRACTOR_ID`: Unique ID (default: `default_extractor`)
- `EXTRACTOR_URL`: Public URL for this extractor (default: `http://localhost:8001`)

**Registry environment**:
- `REDIS_URL`: Redis connection (default: `redis://redis:6379`)

**All services** share Docker network: `video-net`

### Embedder Docker Compose (`Embedder/docker-compose.embedder.yaml`)
Services: etcd, milvus-standalone, embedder

Networks:
- `embedder-net` (internal)
- `video-net` (external - attaches to extractor network for MinIO/Registry access)

**Embedder environment**:
- `MILVUS_HOST`: `milvus-standalone`
- `MILVUS_PORT`: `19530`
- `EMBEDDING_DIM`: `512` (ViT-B-32)
- `MINIO_URL`: `host.docker.internal:9000` (bridges to extractor's MinIO)
- `FRAME_BUCKET`: `frames`
- `REGISTRY_URL`: `http://registry:8000`
- `EMBEDDER_ID`: `embedder-1`
- `EMBEDDER_URL`: `http://embedder-1:8001`
- `USE_ONNX`: `1` (enable ONNX)
- `ONNX_MODEL_PATH`: `models/open_clip_vit_b32.onnx`
- `FILES_PER_EMBED_BATCH`: `32`
- `INSERT_BATCH_SIZE`: `500`

**Critical**: `MINIO_URL=host.docker.internal:9000` allows embedder (on separate Docker network) to reach MinIO running on host network. This assumes both Docker compose files are run on same host.

## Prerequisites

- Docker & Docker Compose (v2)
- NVIDIA Docker runtime (for GPU acceleration)
- At least 8GB RAM (16GB recommended)
- ~20GB free disk space (for Milvus, MinIO data, models)

## How to Run

### 1. Clone and Setup

```bash
git clone <repository>
cd ClipSight
```

### 2. Download Model (for Embedder)

The OpenCLIP model is not included due to size. Download it:

```bash
mkdir -p Embedder/models
cd Embedder/models

# Download ViT-B-32 model (~350MB)
wget https://storage.googleapis.com/open_clip_vit_b32/open_clip_pytorch_model.bin

# Optional: Manually export to ONNX (or let Docker do it automatically)
cd ..
python export_to_onnx.py
cd ..
```

**Note**: The Docker startup script will auto-export if ONNX model missing but PyTorch model present.

### 3. Start Infrastructure (MinIO + Registry + Extractors)

In one terminal, from project root:

```bash
# Start Redis, MinIO, Registry, Main API, Extractors
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" up -d
```

Verify all services healthy:
```bash
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" ps
```

Wait until all show `healthy` (especially `registry`, `minio`).

Access:
- MinIO Console: http://localhost:9090 (login: minioadmin/minioadmin)
- Main API: http://localhost:8080/docs (Swagger UI)
- Registry: http://localhost:8000/docs

### 4. Start Embedder Stack

In another terminal:

```bash
# Start etcd, Milvus, Embedder
docker-compose -f "Embedder/docker-compose.embedder.yaml" up -d
```

Verify:
```bash
docker-compose -f "Embedder/docker-compose.embedder.yaml" ps
```

Access:
- Milvus health: http://localhost:9091/healthz

### 5. Configure UI

Edit `UI/ui.py` and update:

```python
SERVER_IP = "localhost"  # or your server's actual IP if remote
```

If running all Docker services locally, `localhost` works.

### 6. Start Streamlit UI

```bash
cd UI
pip install -r requirements_ui.txt
streamlit run ui.py
```

Or if you prefer to run in Docker (create separate compose):
```bash
# Not provided - you would need to create UI/docker-compose.ui.yml
```

### 7. Access Web Interface

Open browser: http://localhost:8501

## Testing the System

### Manual Test:

1. **Upload a video** (MP4 < 100MB recommended for quick testing)
2. UI shows "Server processing started"
3. Check logs:
   ```bash
   docker-compose -f "Server and Extractor/docker-compose.extractor.yml" logs -f extractor-1
   docker-compose -f "Embedder/docker-compose.embedder.yaml" logs -f embedder
   ```
4. **Expected flow**:
   - Extorsor logs: "Finished segment 0 and uploaded frames to MinIO."
   - Embedder logs: "Found new segment to process: myvideo/segment_0000"
   - Embedder logs: "Inserting batch of X vectors into Milvus..."
   - Embedder logs: "Successfully deleted X processed frames"
   - Embedder logs: "Finished processing and marked segment as done"

5. **Verify Milvus data** (optional):
   ```bash
   pip install pymilvus
   python -c "
   from pymilvus import connections, Collection
   connections.connect('default', host='localhost', port=19530)
   coll = Collection('video_frames')
   print('Entity count:', coll.num_entities)
   coll.load()
   results = coll.search([...], 'embedding', ...)
   print(results)
   "
   ```

6. **Search** (requires query API at port 8081 - not included):
   - Implement a simple FastAPI service that:
     - Accepts `POST /search/text` with query text
     - Uses OpenCLIP to encode query text
     - Searches Milvus `video_frames` collection
     - Returns top-k results with `video_id`, `frame_path`, `score`
   - Then use UI's search box

## Troubleshooting

### Embedder can't connect to MinIO
**Error**: `Failed to connect to MinIO`

**Cause**: `MINIO_URL=host.docker.internal:9000` only works if Docker is running with host networking bridge. On Linux, may need `host.docker.internal` not available.

**Fix**:
- Option A: Use `MINIO_URL=172.17.0.1:9000` (Docker bridge IP)
- Option B: Connect both Docker networks together (complex)

Check connectivity:
```bash
docker exec -it <embedder_container> ping host.docker.internal
```

### Milvus fails to start
**Error**: etcd connection issues

**Fix**: Wait longer for etcd. Check logs:
```bash
docker-compose -f "Embedder/docker-compose.embedder.yaml" logs etcd
```

If persistent, increase `depends_on` wait conditions or delete volumes:
```bash
docker-compose -f "Embedder/docker-compose.embedder.yaml" down -v
docker-compose -f "Embedder/docker-compose.embedder.yaml" up -d
```

### Embedder not finding frames
**Check**:
1. MinIO bucket `frames` exists
2. Frames are in paths like `{video_name}/segment_0000/frame-00001.jpg`
3. No `.processed` marker blocking reprocessing
4. Check embedder logs for scanning output

### No GPU acceleration in ONNX
**Check**: `torch.cuda.is_available()` inside embedder container:
```bash
docker exec -it <embedder_container> python -c "import torch; print(torch.cuda.is_available())"
```

If `False` but GPU present, need NVIDIA Container Toolkit:
```bash
# Install nvidia-docker2 on host
sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker
```

Then modify `Embedder/Dockerfile` to use `nvidia/cuda` base image (already done if using `onnxruntime-gpu`).

### Extractors stuck busy
**Cause**: Failed to reset status after job

**Fix**: Restart extractor (it will re-register as available):
```bash
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" restart extractor-1
```

### Port conflicts
If ports 9000, 8080, 8000, 19530, etc. already in use:
- Modify each `docker-compose.yml` to use different host ports
- Example: `"8081:8080"` maps container 8080 → host 8081
- Update UI's `API_URL` accordingly

## Architecture Decisions

### Why separate extractors and embedders?
- **Scalability**: Can have many extractors (I/O-bound) vs fewer embedders (GPU-bound)
- **Fault isolation**: If embedder crashes, video processing continues
- **Resource optimization**: Extractors run on CPU, embedders benefit from GPU

### Why MinIO as intermediate storage?
- Decouples extractors from embedders (async processing)
- Enables retry/reprocessing without re-extraction
- Allows independent scaling and failure recovery
- S3-compatible → easy to replace with real S3

### Why Redis registry?
- Lightweight service discovery
- Fast status updates
- Simple TTL could be added for auto-deregistration
- Alternative: Kubernetes services + health checks if deploying to K8s

### Why ONNX?
- Faster inference than PyTorch (~2-3x)
- Better for production deployment
- Hardware-agnostic (CPU/GPU via different providers)
- Easy to optimize further (TensorRT, OpenVINO)

## Future Improvements

- **Deduplication**: Prevent duplicate embeddings when frames re-processed
- **Query service implementation**: Currently missing port 8081 search API
- **Better load balancer**: Round-robin instead of first-available
- **Embedder auto-scaling**: Multiple embedder instances for parallel processing
- **Progress tracking**: WebSocket updates to UI for processing status
- **Scene detection in pipeline**: Integrate PySceneDetect into extractor
- **Video chunk size optimization**: Adaptive based on content complexity
- **Frame selection**:smart frame picking (not just 1 FPS) - keyframes, semantic saliency
- **Storage tiering**: Move old frames to cold storage

## License

[Add your license here]

## Contact

[Add contact info / maintainers]
