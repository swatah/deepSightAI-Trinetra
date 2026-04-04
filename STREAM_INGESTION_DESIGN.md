# Unified Video Ingestion Pipeline Design

## Problem Statement

Current video ingestion in deepSightAI Trinetra is fragmented and lacks streaming semantics:

- **File uploads**: Uploaded to MinIO → Main API segments with FFmpeg → Dispatches to extractors (job-based)
- **RTSP streams**: Main API dispatches to extractor → GStreamer pipeline directly reads RTSP

Issues:
- No unified abstraction for different source types
- Embedder uses inefficient polling (every 10s) to detect new frames
- No backpressure mechanism (could overwhelm embedder)
- No stream replay capability (cannot re-process past frames)
- Tight coupling between source handling and processing logic

## Goal

Implement a Kinesis-like streaming ingestion pipeline that:
- Supports multiple source types (file, RTSP, extensible for HLS/DASH)
- Uses event-driven architecture (not polling)
- Provides backpressure and replay capabilities
- Maintains backward compatibility with existing endpoints
- Follows TDD with all tests running in Docker
- Incrementally deliverable via task tracking

---

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 Unified Ingest Service                      │
│  (FastAPI: POST /ingest) with source_type field            │
│  - Accepts: file upload, rtsp_url, hls_url, etc.          │
│  - Dispatches to appropriate adapter                       │
│  - Publishes control events to Redis Streams               │
└───────────────┬─────────────────────────────────────────────┘
                │
                ▼
        ┌───────────────┐
        │   Redis       │
        │   Streams     │ (buffering, replay, backpressure)
        └───────┬───────┘
                │
                ▼
┌─────────────────────────────┐          ┌─────────────────────┐
│   Frame Extraction Workers   │───frames─→│   MinIO Storage     │
│ (Extractor service)          │          │ (same buckets)      │
└─────────────────────────────┘          └──────────┬──────────┘
         │  ▲                                         │
         │  └─── Publishes "frame_ready" events ──────┘
         │
         ▼
┌─────────────────────────────┐
│     Embedder Service         │
│ (Event-driven consumer       │
│  using Redis Streams XREAD) │
└─────────────────────────────┘
```

---

## Event Schema

All events use Pydantic models for validation and JSON serialization.

### Core Events

```python
class IngestJobStarted(BaseModel):
    event_type: Literal["ingest.started"]
    job_id: str
    source_type: str  # "file", "rtsp", "hls"
    source_identifier: str  # e.g., MinIO key or RTSP URL
    tenant_id: str
    timestamp: datetime

class IngestJobCompleted(BaseModel):
    event_type: Literal["ingest.completed"]
    job_id: str
    source_type: str
    video_id: str  # generated ID for the ingested video
    frame_count: int
    duration_seconds: float
    timestamp: datetime

class FrameReadyEvent(BaseModel):
    event_type: Literal["frame.ready"]
    video_id: str
    segment_id: int  # for files; for RTSP use segment_id=0
    frame_paths: List[str]  # full MinIO object paths
    timestamps: List[float]  # timestamps in seconds from video start
    sequence_numbers: List[int]  # frame sequence numbers
    extractor_id: str
    bucket_name: str  # usually "frames" or "frames-rtsp-..."
    timestamp: datetime  # event creation time

class EmbedderProcessingStarted(BaseModel):
    event_type: Literal["embedder.started"]
    video_id: str
    consumer_id: str  # embedder instance ID
    timestamp: datetime

class EmbedderProcessingCompleted(BaseModel):
    event_type: Literal["embedder.completed"]
    video_id: str
    frames_processed: int
    embeddings_inserted: int
    duration_seconds: float
    timestamp: datetime
```

### Redis Streams Configuration

- **Control stream** (ingest jobs): `control:ingest` (retention: 7 days)
- **Frame streams**: One per video: `frames:{video_id}` (retention: 30 days)
  - Allows replay of specific video processing
- **Embedder heartbeat**: `heartbeat:embedder:{embedder_id}` (retention: 1 hour)

Stream max length: capped at 10,000 entries per stream to bound memory; older entries trimmed automatically.

---

## Component Specifications

### 1. Unified Ingest Service (`Server and Extractor/ingest_service.py`)

FastAPI application providing a single ingestion entry point.

**Endpoints:**
- `POST /ingest` (multipart/form-data or JSON)
  - Fields: `source_type` (enum), `file` (optional), `rtsp_url` (optional), `hls_url` (optional), `tenant_id` (optional, from auth)
  - Returns: `{ "job_id": "...", "status": "accepted", "video_id": "..." }`
- `GET /ingest/{job_id}/status` (optional, for job status polling)

**Logic:**
1. Validate request based on source_type
2. Generate `job_id` (UUID)
3. Route to appropriate adapter (Strategy pattern)
4. Adapter handles source-specific preparation (upload file, validate RTSP URL)
5. Publish `IngestJobStarted` to `control:ingest`
6. Dispatch to extractor via registry
7. Return job_id immediately (async processing)

**Adapters:** (folder: `Server and Extractor/adapters/`)
- `FileAdapter`: Takes uploaded file, saves to MinIO `videos/`, segments with FFmpeg metadata, creates ingest job
- `RtspAdapter`: Validates RTSP URL (simple connectivity test), creates ingest job for live stream
- (Future: `HlsAdapter`, `DashAdapter`, `MjpegAdapter`)

### 2. Enhanced Extractor (`extractor.py` modifications)

**Changes:**
- After uploading frames to MinIO in `run_file_extraction_job`, publish `FrameReadyEvent` to Redis Stream `frames:{video_id}`
- Include all metadata: video_id, segment_id, frame paths, timestamps
- Use producer utility from `shared/streaming/producer.py`

**No changes to extraction logic**, just add event publishing after upload.

**RTSP mode**: The `GStreamerRtspExtractor` runs continuously. After each batch of frames uploaded, publish `FrameReadyEvent` with segment_id=0 and incremental sequence numbers.

**Error handling**: If publishing fails, log error but don't fail the job (best effort). Dead letter queue could be added later.

### 3. Event-Driven Embedder (`Embedder/embedder.py` refactor)

**Current:** Polls MinIO every 10 seconds for new frame segments.

**New:** Consumer group on Redis Streams:
- Connect to `control:ingest` to learn about new videos? Or directly read `frames:{video_id}` streams?
- Option A: Subscribe to all `frames:*` via `XREAD` with `STREAMS` block
- Option B: Each video gets its own stream; embedder reads from multiple streams using `XREADGROUP` with `$` (last ID) per stream

Better approach: Use `XREADGROUP` with a consumer group per embedder instance. Streams are created dynamically when first frame arrives. Embedder uses `XREAD` blocking call to wait for new events. When event arrives, process frames, then `XACK` to acknowledge. If multiple embedders, they share work via consumer group.

Implementation:
- On startup, discover existing `frames:*` streams (scan keys)
- For each stream, join consumer group (or create if not exists)
- Read pending entries (`XREADGROUP` with `ID=0-0` for new, or use `XCLAIM` for rebalancing)
- Block indefinitely waiting for new events
- Process batch, delete frames from MinIO, mark processed in DB/Milvus
- `XACK` on successful processing to remove from pending entries list (PEL)

**Fallback safety:** Periodically (every hour) do a full scan of MinIO buckets to detect any missed frames (not received via events). Process them as fallback, to handle cases where events were lost.

### 4. Replay & Management (`shared/streaming/replay.py`)

Utility to re-read events from a completed video's stream for re-processing (e.g., if embedding failed partially).

- Admin API endpoint: `POST /admin/replay/{video_id}` (protected)
- Reads all events from `frames:{video_id}` (from oldest to newest) using `XREVRANGE` + reverse
- Republishes events to a temporary replay stream, or directly calls embedder logic
- Avoids duplicates: embedder uses idempotent insert based on frame_path deduplication

---

## Data Flow: End-to-End (Happy Path)

1. **Client** calls `POST /ingest` with `{"source_type": "file", "file": <upload>}`
2. **Ingest Service**:
   - Saves file to MinIO `videos/`
   - Generates `video_id = uuid4()`
   - Publishes `IngestJobStarted(job_id, source_type="file", ...)` to `control:ingest`
   - Gets extractor from registry
   - Dispatches `POST /extract` with job payload (`video_uri`, segment info)
3. **Extractor** (`/extract` endpoint receives request):
   - Downloads video segment from MinIO
   - Extracts frames with GStreamer
   - Uploads frames to MinIO `frames/{video_name}/segment_{id}/frame-xxxx.jpg`
   - Publishes `FrameReadyEvent(video_id, segment_id, frame_paths[], timestamps[], ...)` to `frames:{video_id}`
   - Updates status to available
4. **Embedder** (blocking on `XREADGROUP` on all `frames:*` streams):
   - Receives event
   - Downloads frames batch
   - Generates embeddings
   - Inserts into Milvus
   - Deletes frames from MinIO
   - Publishes `EmbedderProcessingCompleted` to `control:ingest`
   - Acknowledges event (`XACK`) to remove from PEL

---

## Backward Compatibility

- Existing endpoints `/process_video` and `/process_rtsp_stream` in Main API remain unchanged (or become thin wrappers that call `/ingest` internally)
- No changes needed to UI or external clients
- Extractors unchanged (except add event publishing)
- Embedder can run old polling-based version alongside new event-driven version during migration

---

## Implementation Tasks (T2.2.1 - T2.2.12)

See `DEVELOPMENT_TRACKING.md` for full task structure. Tasks will be added under Phase 2, Area 2.2.

### Task List Summary

| Task | Description | Est. Hours |
|------|-------------|------------|
| T2.2.1 | Design event schema and Redis Streams integration | 4 |
| T2.2.2 | Implement Redis Streams producer utility | 6 |
| T2.2.3 | Implement Redis Streams consumer with consumer groups | 8 |
| T2.2.4 | Create Unified Ingest Service endpoint | 8 |
| T2.2.5 | Implement FileSourceAdapter | 8 |
| T2.2.6 | Implement RtspSourceAdapter | 6 |
| T2.2.7 | Add event publishing to extractor after frame upload | 4 |
| T2.2.8 | Modify embedder to consume events instead of polling | 12 |
| T2.2.9 | Implement replay functionality | 6 |
| T2.2.10 | Integration test: end-to-end streaming flow | 10 |
| T2.2.11 | Performance benchmarking | 6 |
| T2.2.12 | Add monitoring and metrics | 6 |

**Total Estimated**: 84 hours

---

## Testing Strategy

### Unit Tests
- Use `fakeredis` to mock Redis Streams operations
- Mock MinIO client, Milvus client
- Test each adapter in isolation
- Test producer/consumer logic thoroughly

### Integration Tests
- Use Docker Compose to spin up real Redis, MinIO, Milvus
- Test full pipeline: ingest → extract → embed
- Use small sample videos (few seconds)
- Verify frame count, embedding count, no data loss

### Performance Tests
- Benchmark end-to-end latency (upload to embedding)
- Throughput: frames per second under sustained load
- Consumer lag measurement

All tests run in Docker via `tests/Dockerfile.test` and `tests/docker-compose.test.yml`.

---

## Verification

After implementation:
```bash
# Run unit tests
pytest tests/unit tests/streaming tests/api tests/ingest -v

# Run integration tests
pytest tests/integration/test_streaming_flow.py -v

# Run performance tests
pytest tests/performance/test_streaming_throughput.py -v
```

Deploy to staging and run manual smoke test:
- Upload video file via API
- Check Redis streams populated
- Check embedder processing events
- Verify frames searchable in Milvus

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Redis memory growth | Set `MAXLEN` on streams, add trimming logic, monitor |
| Consumer lag | Add metrics and alerts, scale embedder horizontally |
| Event ordering issues | Sequence numbers per video; single stream per video preserves order |
| Lost events (Redis crash) | Enable Redis persistence (AOF), replicate with sentinel/cluster |
| Migration complexity | Keep both polling and event-driven embedder running in parallel during rollout; feature flag |

---

## Future Enhancements

- Exactly-once semantics with idempotency tokens (currently at-least-once)
- Kafka backend for higher scalability (replace Redis Streams)
- HLS/DASH adapters for adaptive bitrate streams
- Webhook notifications for job completion
- Video chunking optimization per source type
- Compression of frame batches in events (currently just paths)

---

## Success Criteria

- ✅ All T2.2 tasks completed and committed
- ✅ All tests passing (≥80% coverage)
- ✅ End-to-end latency < 30s for 1-minute video
- ✅ Throughput > 10 FPS sustained
- ✅ No data loss (verified by integration tests)
- ✅ Backward compatibility maintained
