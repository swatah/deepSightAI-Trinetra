# Enterprise Ingestion V3 — Testing Plan

Companion to [`enterprise-ingestion-v3.md`](enterprise-ingestion-v3.md) and
[`enterprise-ingestion-v3-implementation-plan.md`](enterprise-ingestion-v3-implementation-plan.md).
Covers full integration testing across both ingestion paths and the shared downstream pipeline.
Test cases are tagged with the requirement ID(s) they verify.

---

## 1. Environment setup (required before any test case below can run)

### 1.1 Simulated camera sources

- Stand up an RTSP test server (e.g. MediaMTX/`rtsp-simple-server`) fed by looped sample video
  files via `ffmpeg`, so each "camera" is a real RTSP stream, not a mock.
- Must be able to spin up a **configurable number** of simulated streams — a handful for
  functional tests, and a large fleet for scale tests. Scale tests toward the 10,000 target will
  need multiple hosts generating streams in parallel; a single machine will not produce 10,000
  real RTSP connections.

### 1.2 Simulated edge device (push path)

- Build a small standalone harness that plays the role of an edge device: pulls from a test RTSP
  source (or replays pre-computed embeddings for pure-endpoint tests), and calls the push
  endpoint following the exact contract in §5 of the requirements doc.
- The harness must be able to **deliberately misbehave** on command, since negative-path tests
  depend on it: send malformed payloads, reuse an `event_id`, drop the connection mid-request,
  present an invalid/revoked credential, send with clock skew, exceed rate limits.
- Build at least **two independently-configured instances** of this harness (different "vendor"
  profiles — e.g. different batch sizes, different retry timing) so hardware-independence (Goal 2
  in the requirements doc) is actually exercised by more than one client behavior, not just one
  reference implementation.

### 1.3 Backing services

- Redis Streams instance (isolated from any shared dev instance) for the `frames` queue,
  `embedder-group` consumer group, and the edge-ingestion dedup store.
- Milvus test instance/collection, reset between test runs.
- MinIO test bucket for frame storage (pull path).
- AuthService test tenant(s) with the ability to issue and revoke edge-device credentials
  programmatically from the test suite.

### 1.4 Test data

- A small set of reference video clips with known content, plus pre-computed reference embeddings
  for those clips, so correctness tests can assert on actual vector output, not just "no error."
- A golden search query set: given known clips indexed via each path, the same query must return
  equivalent results regardless of which path ingested the content (used in §3, S1).

### 1.5 Environment tiers

- **Local/CI tier**: docker-compose stack with a small number of simulated streams and one edge
  harness instance — runs on every change, per the repo's existing TDD-in-Docker convention.
- **Staging/load tier**: a scaled environment (multiple hosts for stream simulation, autoscaling
  enabled) reserved for the scale and soak tests in §4 — these are not expected to run in regular
  CI due to cost/duration.

---

## 2. Pull path integration tests

| Ref | Test | Pass condition |
|---|---|---|
| P1/P2 | Ramp concurrent RTSP connections from 0 toward the target scale, in steps. | Autoscaler adds capacity as load increases; no stream is dropped once within advertised capacity; requests beyond current capacity get `503` + `Retry-After`, not a hang or crash. |
| P3 | Compare decoded frame output (hash/SSIM) between hardware decode and the software-decode baseline for the same source clip. | Output is equivalent within tolerance. Also: force hardware decoder unavailable and confirm clean fallback to software decode with a logged capacity reduction. |
| P3 | Inject a corrupted RTSP packet mid-stream. | Pipeline recovers at the next keyframe; stream is not marked failed for a single bad packet. |
| P4 | Run multiple embedder consumers against a saturated queue. | Events are split across consumers (verify via consumer name in Redis `XPENDING`); throughput scales with consumer count. |
| P4 | Kill an embedder consumer mid-batch. | Its pending entries are reclaimed by another consumer via `XAUTOCLAIM` within the idle timeout; no event is lost or double-processed. |
| P4 | Feed a permanently-invalid frame (corrupt image). | After 3 retries, event lands in `events:dlq`; queue is not blocked behind it. |
| P4 | Force a GPU OOM condition (oversized batch). | Worker recovers via smaller batch/CPU fallback; does not crash. |
| P5 | Kill an extractor pod without clean deregistration. | It disappears from placement selection once its registry TTL expires; no stream is routed to it before then triggers a clear error, not a silent hang. |
| P5 | Make the registry unreachable. | Placement calls fail closed with `503`; no request is routed to a guessed/stale target. |
| P6 | Kill several extractor nodes simultaneously. | Orphaned streams are reassigned within the bounded SLA; reassignment is rate-limited (verify it doesn't spike load on remaining nodes beyond a configured ceiling). |
| P6 | Kill nodes with no spare capacity available anywhere. | Affected streams enter a bounded "pending" state with an alert; no infinite retry loop. |

---

## 3. Push path integration tests

| Ref | Test | Pass condition |
|---|---|---|
| E1/E2 | Submit one event; submit a batch. | Both accepted; batch response is itemized per event. |
| E2 | Submit a batch with one malformed event among valid ones. | Valid events succeed; only the bad one is rejected, with its index and reason. |
| E3 | Submit with a valid credential; then with an invalid one; then with a just-revoked one. | Valid → accepted. Invalid → `401`. Revoked → rejected immediately, not after a delay. |
| E3 | Submit repeated bad credentials from one simulated device. | Device is rate-limited/locked after the configured threshold; an alert fires. |
| E4/S2 | Submit from a device onboarded for camera A but claiming camera B; submit for a camera assigned to the pull path. | Both rejected with `403` and a clear reason. |
| §5.3 | Omit each required field one at a time (`camera_id`, `tenant_id`, `captured_at`, `embedding_vector`, `embedding_dim`, `model_id`, `model_version`, `event_id`). | Each produces a `400` naming that specific field — run as one parameterized test per field. |
| §5.3 | Submit `embedding_dim` that doesn't match the model's known size. | Rejected as `dimension_mismatch`; not coerced or truncated. |
| §5.3 | Submit an unknown/retired `model_id`/`model_version`. | Rejected; confirm nothing was written to Milvus for it. |
| E5 | Submit the same `event_id` twice (sequential). | Second call returns the original result; Milvus has exactly one record. |
| E5 | Submit the same `event_id` twice concurrently (race). | Exactly one write occurs; the other call resolves to the same result without erroring. |
| E5 | Make the dedup store unavailable during submission. | Endpoint returns `503`; confirms no write occurred (no risk of an un-deduplicated insert). |
| E6 | Trigger a downstream (Redis) outage during submission. | Endpoint returns `503`, not `200`, for any event it could not durably enqueue. |
| E7 | Stop the simulated device's traffic entirely. | Camera is flagged stale after the configured window, visible in monitoring. |
| E7 | Submit with significant clock skew in `captured_at`. | Event is flagged/clamped; does not silently corrupt time-ordered queries. |
| E8 | Call a deprecated but not-yet-sunset version. | Still succeeds, with a deprecation header. |
| E8 | Call a version past its sunset date. | Returns `410 Gone` with a pointer to the current version. |

---

## 4. Cross-path and shared-pipeline tests

| Ref | Test | Pass condition |
|---|---|---|
| S1 | Ingest matching known content once via the pull path and once via the push path (two different cameras, same reference clip). | Both land in Milvus with the same record shape; the golden search query (§1.4) returns both, indistinguishably. |
| S2 | Reassign a camera from pull to push (and back) while traffic is in flight. | No window exists where both paths accept data for that camera simultaneously; no duplicate or lost events across the switch. |
| S3 | Induce a failure on only one path (e.g. disconnect all push-path devices) while the other path runs normally. | Only that path's alerts/dashboards fire; the healthy path's metrics are unaffected and don't mask the outage. |

---

## 5. Negative-path / resilience testing

- **Network partition** between a simulated edge device and the ingestion endpoint (e.g. via a
  proxy that can drop/delay traffic): confirm the device's retry/buffering behavior is honored,
  and that reconnection does not produce duplicate inserts (covered by E5's dedup).
- **Redis outage** and **Milvus outage**, independently: confirm circuit-breaker behavior on both
  paths — ingestion rejects cleanly rather than queuing unbounded work or silently dropping data.
- **Input fuzzing** on the edge endpoint: oversized payloads, wrong content-type, non-UTF8 strings,
  deeply nested/adversarial JSON — confirm consistent `4xx` handling with no server error leakage
  or crash.
- **Sustained soak test** at target scale (10,000 concurrent pull-path streams plus a
  representative push-path device count) run for an extended period (e.g. 24–48h): watch for
  memory growth, consumer-group lag trending upward, and DLQ growth — any of these indicate a
  leak or an undersized component rather than a one-off blip.

---

## 6. Exit criteria

| Goal (from requirements §2) | Quantitative gate |
|---|---|
| Pull path supports 10,000 streams | Soak test (§5) sustains target stream count with error rate below an agreed threshold and no unbounded resource growth. |
| Push path is hardware-independent | Both simulated edge-device profiles (§1.2) pass the full push-path suite (§3) without path-specific accommodation. |
| Unified downstream data shape | Cross-path test (§4, S1) passes: no observable difference in search results by ingestion path. |
| Elastic scaling without redesign | P1/P2/P6 scale and failover tests (§2) pass at both the CI-tier scale and the staging-tier target scale. |
