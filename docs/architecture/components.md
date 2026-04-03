# Components Deep Dive

Detailed documentation for each ClipSight component.

---

## Main API Router

**Location**: `Server and Extractor/main_api.py`

### Function

HTTP API gateway that handles:
- Video uploads (POST `/process_video`)
- Video status queries (GET `/video/{id}`)
- Search requests (POST `/search`)
- RTSP stream coordination
- Service health monitoring

### Architecture

```python
app = FastAPI()
app.add_middleware(AuthMiddleware)      # JWT validation
app.add_middleware(AuditMiddleware)    # Audit logging
app.add_middleware(TenantMiddleware)   # Extract tenant_id

@app.post("/process_video")
async def process_video(file: UploadFile):
    # 1. Validate MIME type, size
    # 2. Upload to MinIO bucket "videos/{tenant_id}/"
    # 3. Insert metadata to PostgreSQL
    # 4. Split into 30s segments
    # 5. For each segment: dispatch to extractor via registry
    # 6. Return video_id immediately (async processing)
```

### Configuration

Environment variables:

```bash
API_HOST=0.0.0.0
API_PORT=8080
API_WORKERS=4
DATABASE_URL=postgresql://...
MINIO_URL=minio:9000
MINIO_BUCKET_VIDEOS=videos
REGISTRY_URL=redis://registry:8000
AUDIT_ENABLED=true
DISABLE_AUTH=false  # Set true for dev
```

---

## Extractor Service

**Location**: `Server and Extractor/extractor.py`

### Function

Frame extraction workers. Horizontally scalable. Each extractor:
1. Registers itself with Central Registry
2. Polls for jobs (or receives push)
3. Downloads video segment from MinIO
4. Extracts 1 frame per second using GStreamer
5. Uploads frames as JPEGs to MinIO `frames/` bucket
6. Marks segment as complete in PostgreSQL

### GStreamer Pipelines

**File-based extraction**:

```bash
filesrc location=segment.mp4 ! decodebin ! videoconvert ! videorate ! video/x-raw,framerate=1/1 ! jpegenc ! multifilesink location=frames/frame-%04d.jpg
```

**RTSP continuous extraction** (1 frame per 5 seconds):

```bash
rtspsrc location=rtsp://camera/stream latency=0 ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! videorate ! video/x-raw,framerate=1/5 ! jpegenc ! appsink
```

### Job Distribution

Extractors register with Redis Registry:

```python
# On startup
registry.register_extractor({
    "id": "extractor-001",
    "url": "http://extractor-001:8001",
    "status": "available"
})

# Main API asks for extractor:
extractor = registry.get_available_extractor()
# Returns extractor and marks it "busy"

# Extractor processes:
# POST http://extractor:8001/extract
# Body: {segment_id, video_id, minio_path}
```

### Scaling

Run multiple replicas:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: clipsight-extractor
spec:
  replicas: 10  # Scale horizontally
  selector:
    matchLabels:
      app: clipsight-extractor
  template:
    metadata:
      labels:
        app: clipsight-extractor
    spec:
      containers:
      - name: extractor
        image: clipsight/extractor:latest
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
```

---

## Embedder Service

**Location**: `Embedder/embedder.py`

### Function

Generates CLIP embeddings for extracted frames.

### Workflow

```python
while True:
    # 1. Scan MinIO "frames/{tenant_id}/" for new segments
    segments = list_new_segments()
    
    for segment in segments:
        # 2. Download frames from segment (32 at a time)
        frames = download_frames(segment, batch_size=32)
        
        # 3. Generate embeddings
        embeddings = model.encode(frames)  # Shape: (batch, 512)
        
        # 4. Insert into Milvus
        milvus.insert(
            collection_name="video_frames",
            data=[video_ids, frame_paths, embeddings]
        )
        
        # 5. Delete frames from MinIO (cleanup)
        delete_frames(segment)
        
        # 6. Mark segment .processed
        mark_processed(segment)
    
    sleep(10)  # Polling interval
```

### Model Options

**Default**: OpenCLIP (`laion2b_s34b_b79k`) via `open_clip` library.

**ONNX Export** (faster, smaller):

```bash
python Embedder/export_to_onnx.py
# Outputs: embedder.onnx
```

Then use ONNX Runtime:

```python
import onnxruntime as ort
session = ort.InferenceSession("embedder.onnx")
embeddings = session.run(None, {"input": frames})[0]
```

### GPU Support

Build image with CUDA:

```dockerfile
FROM pytorch/pytorch:2.1-cuda11.8-cudnn8-runtime
COPY embedder/ /app/
RUN pip install -r requirements.txt
CMD ["python", "/app/embedder.py"]
```

Set `CUDA_VISIBLE_DEVICES=0` to use GPU.

### Batch Processing

Tradeoff: larger batches = higher throughput, more memory.

Recommendations:
- CPU: batch_size=16
- GPU (8GB): batch_size=64
- GPU (24GB): batch_size=256

---

## Milvus Vector Database

**Port**: 19530

### Schema

Collection: `video_frames`

| Field | Type | Description | Index |
|-------|------|-------------|-------|
| `pk` | BIGINT | Auto-increment ID | Primary key |
| `video_id` | VARCHAR | Source video identifier | Scalar index |
| `frame_path` | VARCHAR | MinIO path to thumbnail | - |
| `embedding` | FLOAT_VECTOR[512] | CLIP embedding | HNSW index |
| `timestamp` | FLOAT | Video timestamp (seconds) | - |
| `tenant_id` | VARCHAR | Tenant partition key | Partition key |

### Index Parameters

```yaml
metric_type: COSINE
index_type: HNSW
params:
  M: 16           # Number of neighbors in HNSW graph
  efConstruction: 200  # Build-time quality (higher = better quality, slower build)
  ef: 64           # Search-time quality (higher = more accurate, slower search)
```

Tuning:
- Increase `ef` for better recall (max 1000)
- Decrease `ef` for faster queries (min 50)
- Increase `M` for better recall but larger index (16-64 typical)

### Querying

```python
# Search for closest vectors to query_embedding
results = milvus.search(
    collection_name="video_frames",
    data=[query_embedding],
    limit=100,
    anns_field="embedding",
    param={"metric_type": "COSINE", "params": {"ef": 64}},
    filter='tenant_id == "acme"'  # tenant isolation
)
```

### Deployment Modes

- **Standalone**: Single pod (dev, < 1M vectors) (current)
- **Distributed**: 3+ nodes with etcd consensus (recommended for production)

See [Milvus docs](https://milvus.io/docs) for cluster setup.

---

## MinIO Object Storage

**Port**: 9000 (API), 9090 (Console)

### Buckets

| Bucket | Purpose | Lifecycle |
|--------|---------|-----------|
| `videos` | Original uploads | Permanent (or archive to S3 after 90 days) |
| `frames` | Extracted JPEGs | Delete after embedding |
| `frames-rtsp` | Live stream frames | Delete after 24h |

### Tenant Isolation

Paths include tenant ID:

```
s3://minio/videos/acme-corp/video1.mp4
s3://minio/frames/acme-corp/video1/segment_0001/frame-0001.jpg
```

### S3 API

ClipSight uses `boto3` S3 client to talk to MinIO. MinIO presents S3-compatible endpoint.

For production, you can replace MinIO with **AWS S3** or **Google Cloud Storage** by changing:
- Endpoint URL
- Credentials
- Bucket names

Configure via environment variables:

```bash
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET_VIDEOS=videos
```

---

## Redis Registry

**Port**: 8000 (custom API), 6379 (Redis protocol)

### Purpose

Service discovery and load balancing for extractors and embedders.

### Data Model

```redis
# Extractor registration
HSET extractor:extractor-001 \
  id "extractor-001" \
  url "http://extractor-001:8001" \
  status "available" \
  last_heartbeat "2025-04-03T14:30:00Z"

# Get available extractor
SSCAN extractor:available  # Return extractor ID
HSET extractor:extractor-001 status "busy"
```

### API Endpoints

- `POST /register` - Register extractor
- `POST /register_embedder` - Register embedder
- `GET /get_available_extractor` - Reserve and return extractor
- `GET /get_available_embedder` - Reserve and return embedder
- `POST /update_status` - Update status (available/busy/offline)
- `GET /health` - Health check

### Implementation

`Server and Extractor/registry.py` - FastAPI app wrapping Redis operations.

---

## PostgreSQL

**Port**: 5432

### Databases

- `clipsight` - main application metadata
- Per-tenant schemas (if using schema-per-tenant strategy)

### Tables

**Core tables**:

```sql
-- Videos uploaded
CREATE TABLE videos (
    id UUID PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    name VARCHAR(500),
    status VARCHAR(50),  -- 'processing', 'ready', 'error'
    duration_seconds INT,
    uploaded_at TIMESTAMPTZ,
    ...
);

-- Video segments (30s chunks)
CREATE TABLE segments (
    id UUID PRIMARY KEY,
    video_id UUID REFERENCES videos(id),
    segment_index INT,
    status VARCHAR(50),
    ...
);

-- Audit logs (WORM)
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    action VARCHAR(50) NOT NULL,
    ...
);
CREATE POLICY audit_deny_update ON audit_logs FOR UPDATE USING (false);
CREATE POLICY audit_deny_delete ON audit_logs FOR DELETE USING (false);
```

---

## Events & Streaming

### Kafka Topics

- `audit-logs` - All audit events (for SIEM)
- `video-events` - Video lifecycle events (uploaded, processed, error)
- `segment-events` - Segment extraction status

### Event Producers

- AuditMiddleware: produces audit logs
- Main API: produces `video.uploaded`, `video.ready`
- Extractor: produces `segment.completed`

### Event Consumers

- Logstash → SIEM (Splunk/Elastic)
- Metrics collector
- Notification service (webhooks)

---

## Plugin Architecture (Phase 2)

Plugins allow sector-specific detection models to be loaded dynamically.

### Plugin Interface

```python
class DetectionPlugin:
    name: str
    version: str
    sector: str
    
    def initialize(self, config: dict):
        """Load model, set up resources"""
        pass
    
    def detect(self, frame: np.ndarray) -> List[Detection]:
        """
        Run inference on frame.
        Returns list of detections: {label, bbox, confidence}
        """
        pass
    
    def cleanup(self):
        """Free resources"""
        pass
```

### Loading Mechanism

```python
plugin_config = {
    "sector": "law_enforcement",
    "plugins": [
        {"name": "lpr", "enabled": true},
        {"name": "weapon_detection", "enabled": true}
    ]
}

loader = PluginLoader(config)
plugins = loader.load_plugins()
```

### Built-in Plugins

- **Law Enforcement**: LPR, Weapon Detection, Face Blur
- **Commercial**: Demographics, Heatmap/Queue detection
- **Logistics**: PPE detection, forklift detection

---

## Next Steps

- [Security architecture](security.md) - Multi-tenancy, encryption, audit
- [Diagrams](diagrams.md) - More architectural diagrams
- [Installation](..//installation/kubernetes.md) - Deploy this architecture
- [Operations](../operations/monitoring.md) - Monitor and operate
