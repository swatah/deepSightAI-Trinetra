# API Reference

Complete REST API documentation for deepSightAI Trinetra. All endpoints require authentication unless otherwise noted.

Base URL: `https://api.trinetra.com/v1`

Authentication: `Authorization: Bearer <JWT_TOKEN>` or `X-API-Key: <key>`

---

## Common Response Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad request (invalid parameters) |
| 401 | Unauthorized (missing/invalid token) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Not found |
| 409 | Conflict (e.g., duplicate upload) |
| 429 | Too many requests (rate limit) |
| 500 | Internal server error |
| 503 | Service unavailable (maintenance) |

Error responses include JSON body:

```json
{
  "error": "invalid_token",
  "message": "Token has expired",
  "request_id": "req_abc123"
}
```

---

## Authentication Endpoints

### POST /auth/login

Authenticate with username/password (for interactive UI).

```bash
curl -X POST https://auth.trinetra.com/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "your-password"
  }'
```

Response:

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "user": {
    "id": "user_abc123",
    "email": "user@example.com",
    "tenant_id": "acme-corp",
    "roles": ["operator"]
  }
}
```

---

### POST /auth/refresh

Refresh expired JWT using refresh token.

```bash
curl -X POST https://auth.trinetra.com/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "refresh_token_from_login"}'
```

---

### POST /auth/logout

Revoke current token (requires valid refresh token).

```bash
curl -X POST https://auth.trinetra.com/auth/logout \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

---

## Video Upload Endpoints

### POST /v1/process_video

Upload and process a video file.

**Parameters** (multipart/form-data):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | Yes | Video file (MP4, MOV, AVI, MKV, max 2GB) |
| `tags` | string | No | Comma-separated tags |
| `description` | string | No | Video description |
| `tenant_id` | string | No | Override tenant (admin only) |

**Response** (200 OK):

```json
{
  "video_id": "vid_1a2b3c4d5e6f",
  "status": "processing",
  "uploaded_at": "2025-04-03T14:30:00Z",
  "estimated_completion": "2025-04-03T15:00:00Z",
  "segments_expected": 12,
  "message": "Video accepted for processing"
}
```

---

## Video Management Endpoints

### GET /v1/videos

List all videos for your tenant (paginated).

**Query Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `page` | integer | Page number (default: 1) |
| `per_page` | integer | Items per page (max: 100, default: 25) |
| `status` | string | Filter by status: `processing`, `ready`, `error` |
| `tag` | string | Filter by tag |
| `sort` | string | Sort field: `uploaded_at`, `duration` (default: `uploaded_at`) |
| `order` | string | `asc` or `desc` (default: `desc`) |

**Response**:

```json
{
  "videos": [
    {
      "id": "vid_abc123",
      "name": "camera1_20250403.mp4",
      "description": "North entrance camera",
      "status": "ready",
      "duration_seconds": 3600,
      "frame_count": 3600,
      "thumbnail_url": "https://minio.deepSightAI-Trinetra.com/frames/vid_abc/thumbnail.jpg",
      "uploaded_at": "2025-04-03T08:30:00Z",
      "tags": ["traffic", "north-entrance"],
      "metadata": {
        "camera_id": "cam001",
        "location": "North Entrance"
      }
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 25,
    "total": 156,
    "pages": 7
  }
}
```

---

### GET /v1/video/{video_id}

Get details for a specific video.

**Response**:

```json
{
  "id": "vid_abc123",
  "name": "camera1_20250403.mp4",
  "description": "North entrance camera",
  "status": "ready",
  "duration_seconds": 3600,
  "frame_count": 3600,
  "segments": [
    {
      "id": "seg_0001",
      "start_time": 0,
      "end_time": 30,
      "frame_count": 30,
      "status": "completed"
    },
    ...
  ],
  "uploaded_at": "2025-04-03T08:30:00Z",
  "thumbnail_url": "...",
  "metadata": {}
}
```

---

### DELETE /v1/video/{video_id}

Permanently delete a video and all associated data (frames, embeddings).

**Response**: `204 No Content`

**Warning**: This operation cannot be undone. Audit log retains deletion record.

---

### GET /v1/video/{video_id}/status

Check processing status (useful for polling).

**Response**:

```json
{
  "video_id": "vid_abc123",
  "status": "embedding",
  "progress": {
    "segments_total": 12,
    "segments_completed": 5,
    "frames_total": 3600,
    "frames_embedded": 1800
  },
  "estimated_completion": "2025-04-03T14:45:00Z"
}
```

---

## Search Endpoints

### POST /v1/search

Search for frames matching a text query.

**Request Body** (application/json):

```json
{
  "query": "person wearing hard hat",
  "tenant_id": "acme-corp",
  "video_filter": "vid_abc123",      // optional
  "top_k": 20,
  "min_similarity": 0.7,
  "timestamp_range": {               // optional
    "start": "00:01:00",
    "end": "00:10:00"
  }
}
```

**Response**:

```json
{
  "query": "person wearing hard hat",
  "results": [
    {
      "frame_id": "frame_00423",
      "video_id": "vid_abc123",
      "video_name": "construction_site_day1.mp4",
      "timestamp_seconds": 45.2,
      "timestamp_formatted": "00:00:45",
      "similarity": 0.94,
      "thumbnail_url": "https://minio.deepSightAI-Trinetra.com/frames/vid_abc/frame_00423.jpg",
      "video_url": "https://minio.deepSightAI-Trinetra.com/videos/vid_abc.mp4"
    }
  ],
  "total_results": 156,
  "returned": 20,
  "query_time_ms": 145
}
```

---

### POST /v1/search/image

Reverse image search: find frames visually similar to provided image.

**Request** (multipart/form-data):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `image` | file | Yes | Query image (JPEG/PNG) |
| `top_k` | integer | No | Max results (default: 10) |
| `min_similarity` | float | No | 0.0-1.0 (default: 0.5) |

**Response**: Same format as text search.

---

### POST /v1/search/batch

Execute multiple queries in one request.

**Request**:

```json
{
  "queries": [
    {"query": "person", "top_k": 5},
    {"query": "vehicle", "top_k": 5}
  ]
}
```

**Response**:

```json
{
  "results": [
    {"query": "person", "results": [...]},
    {"query": "vehicle", "results": [...]}
  ]
}
```

---

## Tenancy & User Management Endpoints

### POST /v1/tenants

Create new tenant (admin only).

```bash
curl -X POST https://api.trinetra.com/v1/tenants \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -d '{
    "name": "Acme Corp",
    "slug": "acme-corp",
    "plan": "enterprise",
    "admin_email": "admin@acme.com",
    "storage_quota_gb": 1000
  }'
```

---

### GET /v1/tenants/{tenant_id}/users

List users in tenant (admin only).

---

### POST /v1/tenants/{tenant_id}/users

Add user to tenant.

```bash
curl -X POST https://api.trinetra.com/v1/tenants/acme-corp/users \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -d '{
    "email": "newuser@acme.com",
    "roles": ["viewer"]
  }'
```

---

## Health & Monitoring

### GET /health

Health check endpoint (no auth required in dev, may require in prod).

**Response**:

```json
{
  "status": "healthy",
  "version": "1.2.3",
  "timestamp": "2025-04-03T14:30:00Z",
  "checks": {
    "database": "healthy",
    "redis": "healthy",
    "milvus": "healthy"
  }
}
```

---

### GET /metrics

Prometheus metrics endpoint (no auth).

Key metrics:
- `deepSightAI-Trinetra_api_requests_total`
- `deepSightAI-Trinetra_api_request_duration_seconds`
- `deepSightAI-Trinetra_videos_uploaded_total`
- `deepSightAI-Trinetra_searches_performed_total`
- `deepSightAI-Trinetra_frames_indexed_total`

---

## OpenAPI Schema

Generate OpenAPI spec:

```bash
curl https://api.trinetra.com/openapi.json > openapi.json
```

Use with API clients (Swagger UI, Postman, Insomnia). Interactive docs available at `/docs` (Swagger UI) and `/redoc` (ReDoc) when running in development mode.

---

## SDKs

Official SDKs:

- **Python**: `pip install deepSightAI-Trinetra`
- **JavaScript/TypeScript**: `npm install @deepSightAI-Trinetra/client`

Example Python SDK:

```python
from deepSightAI-Trinetra import Client

client = Client(
    api_url="https://api.trinetra.com",
    api_key="YOUR_API_KEY"
)

# Upload
video = client.upload("video.mp4", tags=["traffic"])

# Search
results = client.search("red truck", top_k=20)

# Iterate
for frame in results:
    print(frame.timestamp, frame.similarity)
```

---

## Webhooks

Configure webhook URL in Tenant Settings to receive real-time notifications.

**Events**:

| Event | Payload |
|-------|---------|
| `video.uploaded` | `{video_id, tenant_id, filename}` |
| `video.ready` | `{video_id, frame_count, duration}` |
| `video.error` | `{video_id, error_message}` |
| `search.completed` | `{query, result_count, query_time_ms}` |

POSTed to your configured URL with header `X-deepSightAI Trinetra-Signature` (HMAC-SHA256 of payload using webhook secret).

Verify signature:

```python
import hmac, hashlib

signature = request.headers['X-deepSightAI Trinetra-Signature']
expected = hmac.new(
    WEBHOOK_SECRET.encode(),
    request.body,
    hashlib.sha256
).hexdigest()
assert hmac.compare_digest(signature, expected)
```

---

## Rate Limits

| Endpoint | Limit | Burst |
|----------|-------|-------|
| Upload (`/process_video`) | 10/min | 20 |
| Search (`/search`) | 60/min | 100 |
| Video list (`/videos`) | 120/min | 200 |
| Health (`/health`) | Unlimited | - |

Exceeding returns `429 Too Many Requests` with `Retry-After` header.

Contact admin to increase limits for your tenant.

---

## Error Codes

Detailed error codes:

| Code | Error | Meaning | Action |
|------|-------|---------|--------|
| `invalid_token` | 401 | JWT malformed/expired | Re-authenticate |
| `insufficient_scope` | 403 | Token lacks required scope | Request proper role |
| `quota_exceeded` | 403 | Storage/API quota exceeded | Delete old data or upgrade |
| `video_not_found` | 404 | Video ID doesn't exist | Check ID |
| `processing_failed` | 409 | Video processing error | Check video format, check logs |
| `rate_limited` | 429 | Too many requests | Retry after `Retry-After` seconds |
| `service_unavailable` | 503 | Backend service down | Retry later |

---

## API Versioning

Current version: `v1`

Future versions will be additive and backward-compatible within major version. Breaking changes require new major version (e.g., `v2`).

Deprecated endpoints return `Warning` header: `199 - "This endpoint will be removed in v2. Use /new-endpoint instead"`

---

## Pagination

List endpoints (`/videos`, `/users`) support pagination:

```
GET /v1/videos?page=2&per_page=50
```

Response includes pagination metadata:

```json
{
  "videos": [...],
  "pagination": {
    "page": 2,
    "per_page": 50,
    "total": 342,
    "pages": 7,
    "has_next": true,
    "has_prev": true
  }
}
```

Use `Link` header for navigation:

```
Link: </v1/videos?page=1&per_page=50>; rel="prev", 
      </v1/videos?page=3&per_page=50>; rel="next"
```

---

## Filtering

Search and list endpoints support filtering:

```
GET /v1/videos?tag=traffic&status=ready
GET /v1/videos?metadata[camera_location]=north-entrance
GET /v1/videos?uploaded_after=2025-04-01
```

Supported operators:
- `field=value` (exact match)
- `field[op]=value` where op = `gt`, `gte`, `lt`, `lte`, `ne`, `like`
  - Example: `duration_seconds[gte]=300` (videos 5+ minutes)

---

## Content Negotiation

Responses available in:
- `application/json` (default)
- `application/x-ndjson` (newline-delimited JSON for streaming)
- `text/csv` (for bulk exports)

Accept header controls:

```bash
curl -H "Accept: text/csv" https://api.trinetra.com/v1/videos > videos.csv
```

---

## Client Libraries & Examples

Python example with error handling:

```python
import requests
from requests.exceptions import HTTPError

API_URL = "https://api.trinetra.com/v1"
TOKEN = "YOUR_JWT"

headers = {"Authorization": f"Bearer {TOKEN}"}

def search_video(video_id, query):
    try:
        response = requests.post(
            f"{API_URL}/search",
            headers=headers,
            json={
                "query": query,
                "video_filter": video_id,
                "top_k": 20
            },
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except HTTPError as e:
        if response.status_code == 401:
            raise Exception("Unauthorized - check token")
        elif response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            time.sleep(retry_after)
            return search_video(video_id, query)  # retry
        else:
            raise
```

---

## Testing the API

Use the sandbox environment for testing: `https://sandbox-api.deepSightAI-Trinetra.com/v1`

Sandbox account credentials:
- Email: `test@deepSightAI-Trinetra.dev`
- Password: `test-password`
- Token: Request with `/auth/login`

Sandbox has:
- 1GB storage limit
- 10 videos max
- Processing accelerated (1x speed instead of realtime)
- No rate limits

---

## Next Steps

- Learn to [upload videos](uploading.md)
- Perform [semantic search](searching.md)
- Set up [authentication](auth.md)
- Deploy to [production](installation/kubernetes.md)
