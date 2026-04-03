# User Guide

Welcome to ClipSight! This guide covers everything you need to use the platform effectively: uploading videos, searching content, understanding results, and integrating via API.

---

## Overview

ClipSight is a video content search platform. The workflow:

1. **Upload** a video file (MP4, MOV, AVI) or provide RTSP stream URL
2. **Process**: ClipSight automatically extracts frames, generates AI embeddings (OpenCLIP), and stores in vector database
3. **Search**: Use natural language queries like "red truck" or "person wearing helmet" to find relevant frames
4. **Review**: See matching frames with timestamps, jump to video positions

All processing happens automatically in the background. You don't need to manually tag videos or train models.

---

## Accessing the UI

The web UI is available at your deployment URL:

- **Docker Compose**: http://localhost:8501
- **Kubernetes**: Depends on ingress configuration (e.g., `http://ui.clipsight.com`)
- **Cloud**: Provided by load balancer

Login with your credentials (if authentication enabled). For evaluation deployments, auth may be disabled.

---

## Main Interface

```
┌─────────────────────────────────────────────────────────────┐
│ ClipSight Enterprise                                    👤 │
├─────────────────────────────────────────────────────────────┤
│  [Upload] [Search] [My Videos] [Admin]                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Welcome, Jane! You have 3 videos processed.              │
│                                                             │
│  Quick Actions:                                            │
│    📤 Upload New Video                                    │
│    🔍 Quick Search: "office meeting"                      │
│    ⏳ Processing: 1 video in queue                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Uploading Videos

### Supported Formats

| Format | Extension | Max Duration | Notes |
|--------|-----------|--------------|-------|
| MP4 | `.mp4` | 2 hours | H.264, H.265 |
| MOV | `.mov` | 2 hours | QuickTime |
| AVI | `.avi` | 2 hours | Uncompressed OK |
| MKV | `.mkv` | 2 hours | Some codecs may fail |
| RTSP Stream | N/A | Continuous | `rtsp://camera/stream` |

**Limits**:
- Max file size: 2GB
- Max duration: 2 hours (longer videos should be pre-segmented)
- Concurrent uploads: 3 per tenant (configurable)

---

### Upload via Web UI

1. Click **Upload** in the top navigation
2. Drag & drop video file(s) or click to browse
3. (Optional) Add **Tags** for organization: `vehicle,traffic,intersection`
4. Select **Privacy**:
   - **Private** - Only you can search
   - **Shared with [Other Tenant]** - Collaborative search (if enabled)
5. Click **Upload & Process**

Progress indicator shows:
- Upload progress (percentage)
- Processing stages:
  - "Segmentation" (splitting into 30s chunks)
  - "Frame extraction" (1 FPS)
  - "Embedding generation" (AI processing)
  - "Ready" - searchable!

Processing time estimate: 1-2x video duration (depends on GPU availability).

---

### Upload via API

```bash
# First, obtain JWT token from AuthService
curl -X POST https://auth.clipsight.com/token \
  -d "client_id=YOUR_CLIENT_ID&client_secret=YOUR_SECRET&grant_type=client_credentials&tenant_id=your-tenant"

# Response: {"access_token":"eyJ...","expires_in":3600}

# Upload video
curl -X POST https://api.clipsight.com/v1/process_video \
  -H "Authorization: Bearer eyJ..." \
  -F "file=@/path/to/video.mp4" \
  -F "tags=vehicle,traffic" \
  -F "description=Downtown intersection camera 1"

# Response:
{
  "video_id": "vid_abc123def456",
  "status": "processing",
  "estimated_completion": "2025-04-03T15:30:00Z",
  "message": "Video uploaded, processing started"
}
```

Poll for completion:

```bash
curl -H "Authorization: Bearer eyJ..." \
  https://api.clipsight.com/v1/video/vid_abc123def456/status

# Response:
{
  "video_id": "vid_abc123def456",
  "status": "ready",
  "segments_processed": 12,
  "total_frames": 720,
  "thumbnail_url": "https://minio.clipsight.com/frames/vid_abc123/thumbnail.jpg"
}
```

---

## Searching Videos

### Text-to-Video Search

Once videos are processed, search using natural language:

**UI**:
1. Go to **Search** tab
2. Type query: `"red pickup truck"`
3. Adjust sliders:
   - **Number of results**: 10-100
   - **Minimum similarity**: 70% (filter low-confidence matches)
4. Click **Search**

**Results display**:

```
┌─────────────────────────────────────────────────────────────┐
│ Results for "red pickup truck" (12 matches)                │
├─────────────────────────────────────────────────────────────┤
│  Frame 0:23  98%  [thumbnail]  Jump to timestamp ▶         │
│  Frame 1:05  95%  [thumbnail]  Jump to timestamp ▶         │
│  Frame 2:12  93%  [thumbnail]  Jump to timestamp ▶         │
│  ...                                                        │
└─────────────────────────────────────────────────────────────┘
```

Click **Jump to timestamp** to open video player at that exact moment.

---

### Search API

```bash
curl -X POST https://api.clipsight.com/v1/search \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
  -d '{
    "query": "person wearing hard hat",
    "video_id": "vid_abc123",  # optional: limit to specific video
    "tenant_id": "your-tenant",
    "top_k": 20,
    "min_similarity": 0.7
  }'
```

Response:

```json
{
  "query": "person wearing hard hat",
  "results": [
    {
      "frame_id": "frame_00123",
      "video_id": "vid_abc123",
      "timestamp_seconds": 45.2,
      "timestamp_formatted": "00:00:45",
      "similarity": 0.94,
      "thumbnail_url": "https://minio.clipsight.com/frames/vid_abc123/frame_00123.jpg",
      "video_url": "https://minio.clipsight.com/videos/vid_abc123.mp4",
      "segment_id": "seg_0004"
    },
    ...
  ],
  "total_results": 12,
  "query_time_ms": 145
}
```

---

### Advanced Search Filters

Combine multiple criteria:

```bash
curl -X POST https://api.clipsight.com/v1/search \
  -H "Authorization: Bearer eyJ..." \
  -d '{
    "query": "person",
    "filters": {
      "date_range": {
        "start": "2025-03-01",
        "end": "2025-04-01"
      },
      "videos": ["vid_123", "vid_456"],
      "camera_location": "north-entrance"
    },
    "top_k": 50
  }'
```

---

## Video Management

### Viewing Your Videos

**My Videos** page shows all uploaded videos with status:

| Column | Description |
|--------|-------------|
| Video ID | Internal identifier |
| Name | Original filename |
| Status | `Processing` / `Ready` / `Error` |
| Duration | Length in HH:MM:SS |
| Frames | Number of extracted frames |
| Uploaded | Date/time |
| Actions | View, Delete, Share |

---

### Video Details

Click on a video row to see details:

- **Thumbnails** from key frames
- **Processing log** (segmentation progress, embedding stats)
- **Segments** list (each 30s chunk)
- **Search history** (queries that found this video)

---

### Deleting Videos

From **My Videos**:
1. Select checkbox next to video(s)
2. Click **Delete**
3. Confirm: "Are you sure? This will permanently delete video and all extracted data."

**What gets deleted**:
- Video file from MinIO
- Frame images from MinIO
- Embedding vectors from Milvus
- Database records (video metadata, segments)

**Note**: Deletion is permanent. Audit logs remain (immutable).

API:

```bash
curl -X DELETE https://api.clipsight.com/v1/video/vid_abc123 \
  -H "Authorization: Bearer eyJ..."
```

---

## Understanding Results

### Similarity Scores

ClipSight uses CLIP model for semantic similarity. Scores are cosine similarity (0-1, or 0-100%):

- **90-100%**: Exact match (e.g., "red car" returns frames with red cars)
- **70-89%**: Good match (visually similar but not exact)
- **50-69%**: Possible match (may be false positive)
- **<50%**: Likely irrelevant

Adjust **Minimum similarity** slider to filter results.

---

### False Positives / Limitations

CLIP understands general concepts but may misinterpret:

- "President" might return any person in suit (not Obama/Biden specifically)
- "Truck" might include vans, SUVs
- "Nighttime" works well, but "dark" might also match dimly lit indoor scenes

**Tips for better results**:
- Use specific terms: "pickup truck" not "vehicle"
- Combine concepts: "person wearing *blue* hard hat"
- Exclude: "car -sedan" (future feature)
- Try synonyms if no results: "automobile" vs "car"

---

## Batch Processing

For bulk uploads, use the bulk API:

```bash
curl -X POST https://api.clipsight.com/v1/batch_upload \
  -H "Authorization: Bearer eyJ..." \
  -F "files=@video1.mp4" \
  -F "files=@video2.mp4" \
  -F "files=@video3.mp4" \
  -F "common_tags=traffic,intersection"
```

Returns array of `video_id`s. Poll each for status.

Or use CLI tool (comes with Python SDK):

```bash
pip install clipsight-sdk

clipsight upload --tags "traffic,intersection" /path/to/videos/*.mp4
```

---

## Notifications

Get notified when processing completes:

### Email Notifications (if configured)

Admin can enable email alerts:
- Processing complete (success/failure)
- Errors requiring attention
- Storage quota warnings

Configure in `Admin → Notifications`.

### Webhook Hooks

For automation, configure webhook URL:

```yaml
POST https://your-server.com/clipsight-hooks
Content-Type: application/json

{
  "event": "video.ready",
  "video_id": "vid_abc123",
  "timestamp": "2025-04-03T14:30:00Z",
  "tenant_id": "acme-corp"
}
```

Events: `video.uploaded`, `video.processing`, `video.ready`, `video.error`, `search.completed`.

---

## Keyboard Shortcuts (Web UI)

| Key | Action |
|-----|--------|
| `Ctrl/Cmd` + `O` | Open upload dialog |
| `Ctrl/Cmd` + `F` | Focus search box |
| `Esc` | Close modal/dialog |
| `→` / `←` | Navigate results (in search view) |
| `Space` | Play/pause video (when focused) |
| `Enter` | Open selected result video |

---

## Mobile Access

The UI is mobile-responsive. Access from phone/tablet at same URL. Optimized for:
- Safari (iOS)
- Chrome (Android)
- Viewport size >= 768px recommended

Mobile-specific gestures:
- Swipe left/right to browse search results
- Pinch to zoom thumbnails
- Tap timestamp to copy to clipboard

---

## Accessibility

ClipSight UI follows WCAG 2.1 AA guidelines:
- Keyboard navigation support
- Screen reader compatible (ARIA labels)
- High contrast mode (toggle in Admin → Settings)
- Font size scaling (browser zoom works)

---

## Performance Tips

1. **Upload large videos** from wired connection (WiFi may time out)
2. **Search while others upload** - No performance degradation (asynchronous processing)
3. **Too many results?** Use `min_similarity` filter to narrow
4. **Slow thumbnails?** Enable browser caching or use CDN for MinIO
5. **Many videos visible?** Pagination in My Videos page (default 25/page)

---

## API Rate Limits

To prevent abuse, API has rate limits (configurable):

| Endpoint | Rate Limit | Burst |
|----------|------------|-------|
| `POST /process_video` | 10/minute | 20 |
| `POST /search` | 60/minute | 100 |
| `GET /video/*` | 120/minute | 200 |
| Auth endpoints | 20/minute | 30 |

Exceeding returns `429 Too Many Requests`. Contact admin to increase limits for your tenant.

---

## Support Resources

- **In-app help**: Click ? icon in top-right for tooltips
- **Documentation**: This site (use search)
- **API reference**: [Full API docs](api.md)
- **Troubleshooting**: [Operations Guide](operations/troubleshooting.md)
- **Community**: [GitHub Discussions](https://github.com/yourorg/clipsight/discussions)
- **Bugs/Feature requests**: [GitHub Issues](https://github.com/yourorg/clipsight/issues)

---

## Next Steps

You now know how to:
- Upload videos
- Search with natural language
- Manage your video library
- Use the API for automation

**Advanced topics**:
- Configure authentication and multi-tenancy: [Authentication](auth.md)
- Monitor system health: [Monitoring](operations/monitoring.md)
- Deploy to production Kubernetes: [Installation → Kubernetes](installation/kubernetes.md)
- Set up custom plugins: [Plugin Development](../architecture/components.md#plugin-architecture)

Happy searching! 🔍
