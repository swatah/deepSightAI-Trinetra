# Quickstart: Evaluate ClipSight in 5 Minutes

This guide gets you from zero to first search result in under 10 minutes using Docker Compose on your laptop or a single server.

**What you'll get**:
- Running ClipSight stack (API, extractor, embedder, MinIO, Milvus, Redis, PostgreSQL)
- Web UI to upload videos and perform semantic search
- Sample video processed and searchable

---

## Prerequisites

- Docker 24+ and Docker Compose v2
- 8GB RAM minimum (16GB recommended)
- 50GB free disk space
- x86_64 or ARM64 (Apple Silicon) architecture

---

## Step 1: Clone Repository

```bash
git clone https://github.com/yourorg/clipsight.git
cd clipsight
```

---

## Step 2: Start Services

We'll use the provided Docker Compose files. They're designed to run all components on a single host:

```bash
# Start the main API, extractor, PostgreSQL, Redis, MinIO
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" up -d

# Start the embedder service (in separate compose stack)
docker-compose -f "Embedder/docker-compose.embedder.yaml" up -d
```

**What's starting?**
- Main API (port 8080)
- Extractor service (port 8001)
- Embedder service (port 8002)
- PostgreSQL (port 5432)
- Redis (port 6379)
- MinIO (port 9090)
- Milvus (port 19530)

**Wait 30 seconds** for all services to initialize. Check status:

```bash
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" ps
docker-compose -f "Embedder/docker-compose.embedder.yaml" ps
```

All containers should show `Status: Up` (healthy).

---

## Step 3: Access Web UI

Open your browser to: **[http://localhost:8501](http://localhost:8501)**

That's the Streamlit UI. You should see:

```
┌─────────────────────────────────────┐
│          ClipSight Enterprise        │
│  ┌─────────┐  ┌─────────┐          │
│  │ Upload  │  │ Search  │          │
│  └─────────┘  └─────────┘          │
│                                     │
│  Upload a video to get started...   │
└─────────────────────────────────────┘
```

---

## Step 4: Upload a Video

1. Click **Upload** in the left sidebar
2. Select a video file (MP4, MOV, AVI supported, up to 2GB)
3. Click **Process**

You'll see:

```
Uploading: my_video.mp4 (450 MB)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%
Processing: Step 1/2 - Segmenting video... (5s)
Processing: Step 2/2 - Extracting frames... (45s)
Embedding: AI processing in background...
```

**What's happening under the hood**:
- Video split into 30-second segments
- Extractor pulls 1 frame per second
- Frames uploaded to MinIO
- Embedder generates CLIP embeddings
- Embeddings stored in Milvus vector database

Processing a 1-minute video takes ~1 minute total. Check status in **Processing** tab.

---

## Step 5: Search Your Video

Once processing completes (status: `Ready`), go to the **Search** tab:

1. Type a natural language query:
   - `"red car"` - finds frames with red vehicles
   - `"person wearing blue shirt"` - finds people in blue
   - `"indoor office scene"` - finds indoor shots
   - `"nighttime"` - finds dark frames

2. Adjust **Number of results** (default: 10)

3. Click **Search**

Results appear as image thumbnails with similarity scores:

```
┌─────────────────────────────────────┐
│ Results for "red car" (10 found)    │
├─────────────────────────────────────┤
│ [Frame 0:23]  97% ✓                 │
│ [Frame 1:05]  95%                   │
│ [Frame 2:12]  93%                   │
│ ...                                  │
└─────────────────────────────────────┘
```

Click any thumbnail to view full-size and jump to that timestamp in the original video.

---

## Step 6: Try the API Directly

The UI talks to the same REST API you can use programmatically:

```bash
# Get API status
curl http://localhost:8080/status

# Upload video (requires JWT auth - see auth guide for setup)
# For quick evaluation, we'll skip auth for now (if configured)
curl -X POST http://localhost:8080/process_video \
  -F "file=@/path/to/video.mp4"

# Search
curl -X POST http://localhost:8080/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "person smiling",
    "top_k": 5,
    "tenant_id": "demo"
  }'
```

Full API reference: [User Guide → API Reference](user-guide/api.md)

---

## Step 7: View Processing Logs

All container logs are available via Docker:

```bash
# Main API logs (includes request logging)
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" logs -f api

# Extractor logs
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" logs -f extractor

# Embedder logs
docker-compose -f "Embedder/docker-compose.embedder.yaml" logs -f embedder
```

You'll see structured JSON logs with timestamps, tenant IDs, and audit information.

---

## Step 8: Explore Metrics (Optional)

Prometheus metrics are exposed on port 9090:

```
http://localhost:9090/metrics
```

Key metrics:
- `clipsight_videos_processed_total`
- `clipsight_frames_embedded_total`
- `clipsight_search_queries_total`
- `clipsight_api_request_duration_seconds`

---

## Stopping & Cleaning Up

```bash
# Stop all services
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" down
docker-compose -f "Embedder/docker-compose.embedder.yaml" down

# Remove volumes (WARNING: deletes all data!)
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" down -v
docker-compose -f "Embedder/docker-compose.embedder.yaml" down -v

# Remove images
docker rmi clipsight-api clipsight-extractor clipsight-embedder
```

---

## What's Next?

✅ You have a working ClipSight deployment! Next steps:

1. **Configure Authentication** (Optional but recommended)
   - See [Authentication Setup](user-guide/auth.md) for JWT/OAuth2
   
2. **Deploy to Production**
   - See [Kubernetes Installation](installation/kubernetes.md)
   - Or cloud-specific guides: [AWS](installation/cloud.md), GCP, Azure

3. **Enable Multi-Tenancy**
   - Configure tenant isolation
   - Set up provisioning scripts
   
4. **Monitor & Scale**
   - Configure Prometheus alerts
   - Set up Grafana dashboards
   - Add more extractor workers

---

## Troubleshooting

**Q: Services won't start, port already in use**

```bash
# Check what's using the port
sudo lsof -i :8080  # example
# Kill or reconfigure
```

**Q: Embedder fails to connect to Milvus**

Ensure Milvus container is healthy (check logs). It may take 60 seconds to start.

**Q: Videos upload but never process**

Check extractor logs for errors. Common issue: MinIO credentials mismatch.

**Q: Search returns no results**

Verify embedding completed successfully. Check embedder logs for "Finished processing N frames".

**Q: Out of memory**

You need at least 8GB RAM. Free up memory or increase swap.

---

More help:
- [Troubleshooting Guide](operations/troubleshooting.md)
- [GitHub Issues](https://github.com/yourorg/clipsight/issues)
- [Community Slack](https://clipsight-community.slack.com)
