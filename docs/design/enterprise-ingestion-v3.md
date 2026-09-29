# Enterprise Ingestion V3 — Requirements

## 1. Purpose

Define requirements for the next version of Trinetra's video ingestion pipeline, replacing the
current single-mode (central RTSP pull only) design described in
[`STREAM_INGESTION_DESIGN.md`](../../STREAM_INGESTION_DESIGN.md).

V3 must support two ingestion paths at the same time, feeding the same downstream pipeline
(Redis Streams → Embedder → Milvus → Search):

- **Pull path** — the center actively connects to and pulls RTSP streams (current model),
  scaled up to handle far more cameras than today.
- **Push path** — an edge device near the camera pulls RTSP locally, does the decode and
  embedding work itself, and pushes only the result to the center.

A given camera is assigned to exactly one path. The two paths run side by side in the same
deployment.

## 2. Goals

1. The pull path must scale to **10,000 concurrent RTSP streams** on its own.
2. The push path must work with **any edge hardware that meets a stated set of capabilities** —
   the design must not assume or require a specific vendor or chip (no naming Intel, Qualcomm,
   Jetson, or any other brand in the requirement itself).
3. Both paths produce the same downstream data shape, so Milvus indexing and search do not need
   to know which path a given camera used.
4. The system scales elastically as cameras are added — new capacity (central nodes or edge
   boxes) should not require redesigning the pipeline.

## 3. Non-goals (out of scope for this document)

- Selecting a specific edge hardware SKU to buy (that's a procurement decision made against the
  capability spec in §5, not part of the requirement).
- Redesigning search or Milvus indexing.
- Camera-side firmware or RTSP server behavior — cameras are treated as an unmodified, standard
  RTSP source in both paths.

## 4. Pull path requirements (central RTSP ingestion)

| # | Requirement |
|---|---|
| P1 | The pull-side ingestion tier must support up to 10,000 simultaneously connected RTSP streams. |
| P2 | Capacity must scale horizontally by adding nodes — no single process or pod may be the hard limit (today's extractor caps at 6 streams/process with 2–3 static replicas; this must become an autoscaled pool). |
| P3 | Frame decode must use hardware-accelerated video decode, not software (CPU) decode, so a single node can service tens of streams instead of a handful. |
| P4 | Embedding inference on the pull path must run as an autoscaled, GPU-backed pool that consumes from the existing Redis Streams queue via multiple partitioned consumers (the queue already supports this; today only one consumer is active). |
| P5 | Node placement/discovery must not depend on an O(N) poll-all-nodes approach once the fleet is large (today's `main_api.py` polls every extractor's `/rtsp_status`); a scalable registry lookup is required instead. |
| P6 | Losing one pull-path node must not drop more than that node's share of streams — remaining nodes or autoscaling must absorb reassigned cameras within a bounded time. |

## 5. Push path requirements — ingestion contract (hardware-independent)

Trinetra does not build, own, or configure the edge device. This section defines only what
crosses the boundary between an edge device and the platform: the endpoint it calls, how it
authenticates, and the exact data it must send. It says nothing about how the device gets an
RTSP stream, decodes it, or runs a model internally — any device that can produce the payload
in §5.3 and call the endpoint in §5.1 qualifies, regardless of vendor or chip. This section is
written to double as the specification an outside integrator (customer or hardware partner)
implements against directly, without needing anything else from Trinetra.

### 5.1 Endpoint

| # | Requirement |
|---|---|
| E1 | The platform must expose a versioned ingestion endpoint (e.g. `POST /v1/edge/embeddings`) dedicated to push-path submissions, separate from the pull path's internal queue. |
| E2 | The endpoint must accept one embedding event per request, and must accept a batch of events in one request, so a device serving many cameras is not forced into one request per frame. |

### 5.2 Authentication & onboarding

| # | Requirement |
|---|---|
| E3 | An edge device must be issued its own credential (e.g. per-device certificate or API key) before it is allowed to push; the platform must be able to revoke a single device's access without affecting others. |
| E4 | Onboarding a device must record which camera(s) it is submitting on behalf of, so the platform can validate that incoming events belong to a camera actually assigned to the push path (see S2). |

### 5.3 Payload schema

Every push event must include, at minimum:

| Field | Purpose |
|---|---|
| `camera_id` / `tenant_id` | Identifies which camera and tenant the event belongs to, consistent with the platform's existing multi-tenancy model. |
| `captured_at` | Timestamp the frame was captured on the edge device, not when it arrives centrally. |
| `embedding_vector` + `embedding_dim` | The vector itself and its length. |
| `model_id` / `model_version` | Which embedding model produced the vector — required so push-path and pull-path vectors landing in the same Milvus collection stay comparable; a mismatch must be rejected rather than silently indexed. |
| `event_id` | A unique ID the device generates, used for de-duplication (see §5.4). |

### 5.4 Delivery semantics

| # | Requirement |
|---|---|
| E5 | The platform must treat delivery as at-least-once: a device may retry a submission after a network failure, and the platform must de-duplicate using `event_id` rather than assuming each request is new. |
| E6 | The endpoint must return a clear success/failure response per event (or per item in a batch) so the device knows what to retry and what not to. |

### 5.5 Liveness

| # | Requirement |
|---|---|
| E7 | An onboarded device must send a periodic heartbeat (or the absence of expected traffic must be detectable) so the platform can mark a camera's push-path feed as stale/offline, independent of whether that's due to a network issue or a device fault. |

### 5.6 Versioning

| # | Requirement |
|---|---|
| E8 | The endpoint and payload schema are versioned; a new required field or breaking change ships as a new version, and the platform must continue accepting the prior version for a stated deprecation window — since external integrators cannot update in lockstep with internal releases. |

## 6. Shared / central requirements

| # | Requirement |
|---|---|
| S1 | Once accepted, an event from either path must land in the same downstream data store (Milvus) using the same record shape, so search does not need to know which path produced a given result. |
| S2 | Onboarding a camera must include an explicit assignment to "pull" or "push," recorded in the registry, so operational tooling knows which path owns which camera, and so §5.2's validation has something to check against. |
| S3 | Monitoring must report pull-path and push-path health separately (stream count, latency, failure rate per path) so a hardware or network problem on one path is diagnosable without affecting the other. |
