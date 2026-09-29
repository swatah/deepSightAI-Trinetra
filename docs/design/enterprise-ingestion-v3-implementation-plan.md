# Enterprise Ingestion V3 — Implementation Plan

Companion to [`enterprise-ingestion-v3.md`](enterprise-ingestion-v3.md). Every work item below is
tagged with the requirement ID(s) it satisfies (P = pull path, E = push path, S = shared).
Each item states the change, the failure modes it must handle, and how it degrades — this is a
production build, so the negative path is part of the deliverable, not a follow-up.

---

## Phase 1 — Pull path scaling

### 1.1 Hardware video decode (P3)

**Change**: In `ServerAndExtractor/extractor.py`, replace the software decode element
(`avdec_h264`) in the GStreamer pipeline with a hardware decode element appropriate to the node
(e.g. `nvv4l2decoder`/`nvdec` on NVIDIA nodes, `vaapih264dec` on Intel/QuickSync nodes). Detect
which decoder is actually available at process startup and select accordingly.

**Error / negative paths**:
- No hardware decoder present on a node → fall back to software decode, log a warning, and cap
  that node's advertised capacity lower (it should not claim GPU-node throughput it can't deliver).
- GStreamer pipeline reports an `ERROR` bus message mid-stream → the owning thread must catch it,
  tear down and rebuild the pipeline with exponential backoff, not crash the process. After a
  configurable number of consecutive failures, mark the stream `failed` (not endlessly retry) and
  emit a metric/event so it surfaces in monitoring rather than silently looping.
- Corrupt/partial RTSP packets from a flaky camera → pipeline must recover on the next keyframe,
  not treat a single bad packet as terminal.

### 1.2 Remove static caps, autoscale (P2)

**Change**: Replace the hardcoded `RTSP_HARD_LIMIT = min(6, ...)` in `extractor.py` with a
capacity value derived from the node's actual decode headroom (config-driven per node type, not
a single hardcoded constant). Replace the static `replicaCount` in the extractor Helm chart and
the fixed 3-replica `docker-compose.extractor.yml` pattern with a Horizontal Pod Autoscaler keyed
on a custom metric (active-stream-count vs. capacity), not raw CPU.

**Error / negative paths**:
- Demand exceeds current capacity while the autoscaler is still scaling up → new stream requests
  must return `503` with a `Retry-After` header (extending the existing behavior in
  `/extract_stream`), never silently drop or block indefinitely.
- Scale-down must drain a pod (stop accepting new streams, finish/reassign existing ones) before
  termination — a `PreStop` hook calling a drain endpoint, not a hard kill mid-stream.

### 1.3 GPU-backed, parallel embedder pool (P4)

**Change**: In `Embedder/embedder.py`, move `process_events` from a single serial consumer to
multiple consumers within the existing `embedder-group` Redis Streams consumer group (distinct
consumer names per replica/worker), so `replicaCount` can go above 1 and actually parallelize.
Add a GPU resource request to the Helm chart and switch the ONNX Runtime execution provider to
`CUDAExecutionProvider`.

**Error / negative paths**:
- A consumer crashes mid-batch → its pending entries must be reclaimed by another consumer via
  `XAUTOCLAIM` after an idle timeout, not left stuck or lost.
- An event repeatedly fails to embed (e.g. corrupt image) → after the existing 3-retry limit,
  route to the existing `events:dlq`, not retried forever.
- GPU out-of-memory during batch inference → catch the OOM, retry the batch at a smaller size or
  fall back to CPU for that batch, log and emit a metric — do not crash the worker.

### 1.4 Scalable registry / discovery (P5)

**Change**: Replace `main_api.py`'s current pattern of polling every extractor's `/rtsp_status`
(O(N) per placement decision) with extractors proactively pushing their load/capacity into the
existing Redis-hash registry (`registry.py`), and have placement read from a sorted structure
(e.g. a sorted set by spare capacity) for an O(log N) pick.

**Error / negative paths**:
- An extractor crashes without deregistering → registry entries must carry a TTL refreshed by
  heartbeat; expired entries are excluded from placement automatically.
- Registry itself unreachable → placement must fail closed with a clear `503`, never guess or
  route to a stale/unknown target.

### 1.5 Bounded failover (P6)

**Change**: Add a reconciliation loop that detects orphaned RTSP streams (owner's registry entry
expired) and redispatches them to nodes with spare capacity.

**Error / negative paths**:
- Many nodes fail at once (e.g. a node-pool event) → reassignment must be rate-limited/batched so
  the reconciliation loop doesn't itself overwhelm remaining capacity.
- No spare capacity available → affected streams go to a bounded "pending" state with an alert,
  not an infinite retry loop.

---

## Phase 2 — Push path (edge ingestion contract)

### 2.1 New ingestion endpoint (E1, E2)

**Change**: Add a dedicated ingestion service/route (e.g. `POST /v1/edge/embeddings`), separate
from the pull path's internal queue, accepting either a single event or a batch in one request.

**Error / negative paths**:
- Malformed JSON / wrong content-type → `400` immediately, no partial processing.
- One bad event inside an otherwise-valid batch → reject only that event with an itemized error
  (index + reason); the rest of the batch must still succeed (per E6, this is a hard requirement,
  not an optimization).
- Payload or batch size over the configured limit → `413`, not a silent truncation.
- A required downstream dependency (Redis) is unavailable at request time → `503`; the endpoint
  must never return `200` for an event it did not durably enqueue.

### 2.2 Authentication & onboarding (E3, E4)

**Change**: Extend the existing AuthService with an "edge device" credential type (per-device
mTLS certificate or scoped API key), issued during onboarding and tied to a specific
tenant + camera assignment.

**Error / negative paths**:
- Invalid or expired credential → `401`.
- Revoked device continues sending → must be rejected immediately (revocation check per request
  or short-lived token expiry), not just at next redeploy.
- Repeated auth failures from the same device → rate-limit/lock after N consecutive failures and
  alert (possible compromised or misconfigured device), rather than allowing unlimited retries.
- A device pushes for a camera it wasn't onboarded for, or for a camera assigned to the pull path
  (cross-checked against S2's registry field) → `403` with the reason, not a silent accept.

### 2.3 Payload schema & versioning (E2/§5.3, E8)

**Change**: Define the payload as a versioned schema (e.g. `EdgeEmbeddingEventV1`): `camera_id`,
`tenant_id`, `captured_at`, `embedding_vector`, `embedding_dim`, `model_id`, `model_version`,
`event_id`. Version the endpoint path (`/v1/`, `/v2/`) and publish the schema so external
integrators can validate client-side before submitting.

**Error / negative paths**:
- Missing/malformed required field → `400` naming the exact field.
- `embedding_dim` doesn't match the declared model's known output size → reject that event
  specifically (`dimension_mismatch`), don't attempt to coerce or truncate.
- Unknown or retired `model_id`/`model_version` → reject, don't silently index into the wrong
  vector space (this is what protects S1's cross-path consistency guarantee).
- Client calls a deprecated version past its sunset date → `410 Gone` with a pointer to the
  current version, not a generic `404`.

### 2.4 Delivery semantics & idempotency (E5, E6)

**Change**: Track `event_id` in a dedup store (Redis, TTL'd to cover realistic retry windows).
A resubmission of a previously-processed `event_id` returns the original result rather than
reprocessing.

**Error / negative paths**:
- Dedup store itself unavailable at request time → reject with `503` to force a client retry;
  never proceed without the dedup check, since that risks double-insertion into Milvus.
- Two requests for the same `event_id` arrive concurrently (race) → the second must either wait
  for or reuse the first's result, not both write.

### 2.5 Liveness (E7)

**Change**: Add a scheduled check that flags a push-path camera as stale if no heartbeat or
event has arrived within a configurable window, surfaced next to pull-path health (S3).

**Error / negative paths**:
- Device clock is skewed (`captured_at` far from server time) → clamp/flag rather than let it
  corrupt time-ordered queries; do not use it as the sole staleness signal — combine with
  server-side receipt time.

---

## Phase 3 — Shared / unification

### 3.1 One record shape into Milvus (S1)

**Change**: Add a normalization step (new shared module, used by both the embedder's pull-path
writer and the new edge-ingestion path) that maps either source into one canonical record before
insert.

**Error / negative paths**: normalization failure (e.g. missing tenant partition, schema
mismatch) → route to the DLQ, never insert a partial/malformed record.

### 3.2 Registry path assignment (S2)

**Change**: Add an `ingestion_path: pull | push` field to camera registration, enforced both at
extractor dispatch (pull) and edge-ingestion auth (push).

**Error / negative paths**: switching a camera's assigned path while events are in flight must
drain the old path before the new one is authorized, to avoid a window where both paths accept
data for the same camera simultaneously.

### 3.3 Per-path monitoring (S3)

**Change**: Separate metrics/dashboards (`ingestion.pull.*`, `ingestion.push.*`) for stream/device
count, latency, error rate, and DLQ depth, with independent alert thresholds per path.

**Error / negative path**: alerting must not aggregate the two paths into one health number — a
push-path-only outage (e.g. many edge devices offline) must not be masked by a healthy pull-path
average.

---

## Cross-cutting production requirements

- **Structured logging with a correlation/trace ID** carried from ingestion (either path) through
  to the Milvus write, so any event can be traced end-to-end during an incident.
- **Circuit breakers** around Redis, Milvus, and MinIO — a downstream outage must cause the
  ingestion layer to reject new work cleanly (`503`) rather than pile up threads/connections.
- **Fail-fast startup**: missing or invalid required configuration must stop the process at boot,
  not surface as a runtime error on the first real request.
- **Rollout safety**: hardware-decode and the new edge endpoint ship behind a flag/canary with a
  fallback to the previous behavior, given both touch high-traffic paths.
