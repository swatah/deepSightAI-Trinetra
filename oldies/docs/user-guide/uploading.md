# Uploading Videos

This page covers everything about getting video content into deepSightAI Trinetra: supported formats, upload methods, processing workflow, and troubleshooting.

---

## Supported Formats

### File Formats

| Container | Video Codecs | Audio Codecs | Max Resolution | Notes |
|-----------|--------------|--------------|----------------|-------|
| MP4 | H.264, H.265/HEVC | AAC, MP3 | 4K (4096x2160) | Most compatible |
| MOV | H.264, ProRes | AAC, PCM | 4K | QuickTime files |
| AVI | Xvid, DivX, MJPEG | PCM, MP3 | 1080p | Legacy support |
| MKV | H.264, H.265, VP9 | AAC, Opus, AC3 | 4K | Some codecs require ffmpeg>=5 |
| WEBM | VP8, VP9 | Opus, Vorbis | 4K | Browser-friendly |

**Unsupported formats**: WMV, FLV, 3GP (convert first)

### RTSP Streams

For live cameras, provide RTSP URL:

```
rtsp://username:password@camera-ip:554/stream
```

Common RTSP paths:
- `/live` (Hikvision)
- `/cam/realmonitor?channel=1&subtype=0` (Dahua)
- `/h264/ch1/main/av_stream` (ONVIF)

deepSightAI Trinetra will continuously pull frames (1 frame per 5 seconds) and process as new videos.

---

## Upload Methods

### 1. Web UI (Easiest)

See [Quickstart](quickstart.md#step-4-upload-a-video).

Drag & drop or click to select. Max 2GB per file.

### 2. REST API (Programmatic)

#### Single File Upload

```bash
curl -X POST https://api.trinetra.com/v1/process_video \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -F "file=@/path/to/video.mp4" \
  -F "tags=traffic,highway" \
  -F "description=Highway 101 camera 12"
```

**Parameters**:
- `file` (required) - Video file
- `tags` (optional) - Comma-separated tags for organization
- `description` (optional) - Human-readable description
- `camera_id` (optional) - Link to camera in registry (if using RTSP)
- `start_time` (optional) - Override video timestamp (ISO 8601)

**Response**:

```json
{
  "video_id": "vid_1a2b3c4d5e6f",
  "status": "processing",
  "uploaded_at": "2025-04-03T14:30:00Z",
  "estimated_completion": "2025-04-03T15:00:00Z",
  "message": "Video accepted for processing",
  "segments_expected": 120
}
```

#### Multiple Files (Batch)

```bash
curl -X POST https://api.trinetra.com/v1/batch_upload \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -F "files=@video1.mp4" \
  -F "files=@video2.mp4" \
  -F "common_tags=traffic" \
  -F "concurrent=true"
```

Returns array of video IDs. Max 10 concurrent uploads per tenant.

---

### 3. Python SDK

Install:

```bash
pip install deepSightAI-Trinetra
```

Usage:

```python
from deepSightAI-Trinetra import Client

client = Client(
    api_url="https://api.trinetra.com",
    api_key="YOUR_API_KEY"  # or JWT
)

# Upload single video
video = client.upload(
    file_path="/path/to/video.mp4",
    tags=["traffic", "intersection"],
    description="Morning rush hour"
)
print(f"Video ID: {video.id}, Status: {video.status}")

# Wait for completion
video.wait_until_ready(poll_interval=5, timeout=3600)
print(f"Processed {video.frame_count} frames")

# Batch upload
video_ids = client.batch_upload(
    file_paths=["/videos/a.mp4", "/videos/b.mp4"],
    tags=["bulk-upload"],
    max_concurrent=3
)
```

---

### 4. S3/Swedish: Upload to MinIO, then notify

For large-scale pipelines, upload directly to MinIO S3 endpoint, then tell deepSightAI Trinetra:

```bash
# 1. Upload to MinIO S3 bucket "videos"
mc cp /videos/video.mp4 deepSightAI-Trinetra/videos/

# 2. Register with deepSightAI Trinetra
curl -X POST https://api.trinetra.com/v1/register_s3_video \
  -H "Authorization: Bearer TOKEN" \
  -d '{
    "s3_key": "videos/video.mp4",
    "tenant_id": "acme",
    "tags": ["traffic"]
  }'
```

Useful for integrating with existing video storage systems (Surveillance NVRs, etc.).

---

## Processing Workflow

Once uploaded, what happens:

```
[Upload Complete]
      ↓
[Video Validated]
      ↓
[Segment into 30s chunks]
      ↓
[Each segment → Extract frames (1 FPS)]
      ↓
[Frames uploaded to MinIO bucket: {tenant_id}/frames/{video_id}/segment_XXXX/]
      ↓
[Embedder polls MinIO, detects new frames]
      ↓
[Generate CLIP embeddings (512-dim vectors)]
      ↓
[Insert vectors into Milvus collection: video_frames]
      ↓
[Mark video as "ready"]
      ↓
[Webhook/notification sent]
```

### Processing Times

| Video Length | Approx Processing Time | Factors |
|--------------|----------------------|---------|
| 1 minute | 1-2 minutes | Fast with GPU embedder |
| 10 minutes | 10-20 minutes | Linear scaling |
| 1 hour | 1-2 hours | Queue depth affects |

**Real-world example**: 30-minute 1080p video on 1 GPU embedder: ~35 minutes total.

---

## Processing Status

Video statuses:

| Status | Meaning | Actions |
|--------|---------|---------|
| `uploaded` | File received, not yet validated | Wait |
| `validating` | Checking codec, duration | Wait |
| `segmenting` | Splitting into chunks | Wait |
| `extracting_frames` | Pulling JPEGs from video | Wait |
| `embedding` | AI generating vectors (longest step) | Wait |
| `ready` | ✅ Searchable! | Can search now |
| `error` | Failed (see error_message) | Check logs, retry |

Check status:

```bash
curl https://api.trinetra.com/v1/video/{video_id}/status \
  -H "Authorization: Bearer TOKEN"
```

Example response:

```json
{
  "video_id": "vid_abc123",
  "status": "embedding",
  "progress": {
    "segments_total": 12,
    "segments_completed": 5,
    "frames_total": 720,
    "frames_embedded": 280
  },
  "estimated_completion": "2025-04-03T14:45:00Z"
}
```

---

## Progress Monitoring

### Web UI

**Processing** tab shows:
- Current active videos (processing now)
- Completed videos (ready)
- Failed videos (with error message)
- Queue length (waiting for embedder)

Auto-refresh every 10 seconds.

### CLI Monitoring

```bash
# Watch status of all videos
watch -n 5 'curl -H "Authorization: Bearer TOKEN" https://api.trinetra.com/v1/videos | jq .'

# Check embedder queue depth
curl http://localhost:8002/queue/status | jq .
```

---

## Video Organization

### Tags

Add tags during upload for categorization:

```
"tags": ["traffic", "highway-101", "morning-rush", "incident"]
```

Search by tag:

```bash
# Find videos with tag "traffic"
curl https://api.trinetra.com/v1/videos?tag=traffic

# Multiple tags: must have all
curl https://api.trinetra.com/v1/videos?tag=traffic&tag=highway-101
```

### Metadata

Attach custom metadata:

```json
{
  "metadata": {
    "camera_location": "north-entrance",
    "operator": "john-doe",
    "weather": "clear",
    "incident_number": "INV-2025-12345"
  }
}
```

Search by metadata in future (requires implementing custom filter).

---

## Storage Consumption

Estimating storage needs:

| Video (1 hour, 1080p) | ~2 GB | Uploaded file |
|------------------------|-------|---------------|
| Extracted frames (1 FPS) | ~3600 JPEGs @ 200KB each = 720 MB | MinIO |
| Embeddings (3600 × 512 floats) | ~14 MB | Milvus |
| **Total per hour** | **~3 GB** | |

Memory for processing:
- Extractor: ~500 MB RAM per concurrent extraction
- Embedder: ~2 GB RAM per GPU + batch size
- API: ~200 MB

Configure resource limits in Kubernetes manifests accordingly.

---

## Failed Uploads

If upload fails:

1. **Check file size** - Max 2GB
2. **Check format** - Must be MP4/MOV/AVI/MKV
3. **Check network** - Upload timeout after 1 hour
4. **Check logs**: API logs show validation errors

Common errors:

| Error | Cause | Fix |
|-------|-------|-----|
| `Unsupported codec` | Video codec not in list | Convert with `ffmpeg -c:v libx264` |
| `File too large` | > 2GB | Compress or split video |
| `Invalid duration` | 0 seconds or corrupted | Check video plays in VLC |
| `Upload timeout` | Slow network | Increase `client_max_body_size` in API, or upload from closer location |
| `Quota exceeded` | Tenant upload limit reached | Delete old videos or request quota increase |

---

## Deleting Videos

From Web UI:
1. Go to **My Videos**
2. Select video(s)
3. Click **Delete** → Confirm

From API:

```bash
curl -X DELETE https://api.trinetra.com/v1/video/{video_id} \
  -H "Authorization: Bearer TOKEN"
```

Deletion is **permanent**. Cannot undo. Audit logs retain deletion record.

---

## Retrying Failed Videos

If a video fails during processing:

1. Check error message in **My Videos** or via API
2. Fix underlying issue (e.g., convert codec)
3. Delete the failed video entry
4. Re-upload corrected video

Some errors are transient (e.g., embedder temporarily down). In these cases, the system auto-retries for up to 3 hours.

---

## Bulk Export (Download Data)

Export all video metadata and search results:

```bash
curl -X POST https://api.trinetra.com/v1/export \
  -H "Authorization: Bearer TOKEN" \
  -d '{"format": "csv"}' > videos_export.csv
```

Columns: video_id, upload_date, duration, frame_count, tags, status.

For embeddings export (advanced use cases), contact support.

---

## Best Practices

1. **Pre-process long videos**: Split >2 hour videos into segments before upload
2. **Use descriptive names**: `cam1_20250403_0800_0900.mp4` instead of `video1.mp4`
3. **Tag consistently**: Define taxonomy for your organization (location, date, purpose)
4. **Monitor quota**: Set alerts when storage reaches 80% capacity
5. **Test with short clips first**: 1-minute sample to verify quality before bulk upload

---

## Next Steps

After uploading videos:
- [Search for content](../user-guide/searching.md)
- Use [API Reference](api.md) for automation
- Set up [monitoring](operations/monitoring.md) to track system health
- Review [troubleshooting](operations/troubleshooting.md) if issues arise
