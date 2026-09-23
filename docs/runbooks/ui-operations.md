# deepSightAI-Trinetra UI Service Operational Runbook

**Service Name:** `trinetra-ui`  
**Classification:** Tier 1 User-Facing Frontend & API Gateway Layer  
**Repository Path:** `deepSightAI/Trinetra/UI`  
**Kubernetes Namespace:** `default` / `trinetra`  
**Internal Port:** `3000` (HTTP)  
**External Ingress:** `https://trinetra.swatah.ai`  
**Last Updated:** September 2026  

---

## 1. System Overview & Architecture Dependency Map

The `trinetra-ui` service is built on Next.js 14 (App Router) running standalone in Node.js. It handles server-side rendering (SSR), client-side interactivity, proxy streaming for Server-Sent Events (SSE), and media retrieval from backend object stores.

### Service Dependency Map

```text
                        ┌─────────────────────────────────────────┐
                        │     Ingress Controller (ingress-nginx)   │
                        └────────────────────┬────────────────────┘
                                             │ HTTPS:443 -> HTTP:3000
                                             ▼
                        ┌─────────────────────────────────────────┐
                        │       trinetra-ui Pods (Port 3000)      │
                        │  - SSR Pages & Static Assets            │
                        │  - /api/health, /api/ready, /api/metrics │
                        │  - /api/media (Presigned MinIO Proxy)   │
                        │  - SSE Alert Web Stream Handler         │
                        └─────┬───────┬─────────┬────────┬────────┘
                              │       │         │        │
           ┌──────────────────┘       │         │        └──────────────────┐
           │ HTTP:8002                │ HTTP:8081│ HTTP:8083                │ HTTP:9000
           ▼                          ▼         ▼                           ▼
┌──────────────────┐       ┌──────────────┐   ┌──────────────────┐   ┌──────────────┐
│   AuthService    │       │SearchService │   │ WatchlistMatcher │   │ MinIO Bucket │
│ (JWT validation, │       │(Multimodal   │   │  (SSE Live Alert │   │ (CCTV frames,│
│  RBAC, Tenants)  │       │ Milvus QPS)  │   │   Event Stream)  │   │ thumbnails)  │
└──────────────────┘       └──────────────┘   └──────────────────┘   └──────────────┘
           │
           ▼ HTTP:8080
┌──────────────────────┐
│ ServerAndExtractor   │
│ (RTSP ingestion &    │
│  video pipeline)     │
└──────────────────────┘
```

---

## 2. Deployment & Release Procedures

### 2.1 GitOps Release via ArgoCD (Preferred)

All production releases are managed via GitOps using ArgoCD targeting the `k8s/overlays/production` directory.

1. **Verify Staging Status:**  
   Ensure all automated integration and E2E tests have passed on `main`.
2. **Promote Git Tag or Release SHA:**  
   Update the container image tag in `k8s/overlays/production/kustomization.yaml`:
   ```bash
   cd k8s/overlays/production
   kustomize edit set image deepSightAI-Trinetra/trinetra-ui=deepSightAI-Trinetra/trinetra-ui:v1.2.0
   git commit -am "chore(release): bump trinetra-ui to v1.2.0"
   git push origin main
   ```
3. **Trigger ArgoCD Synchronization:**  
   ```bash
   argocd app sync trinetra-ui-prod --prune
   argocd app wait trinetra-ui-prod --health --timeout 300
   ```
4. **Verify Application State in ArgoCD:**  
   ```bash
   argocd app get trinetra-ui-prod
   ```

### 2.2 Manual Kubernetes Rollout

If ArgoCD is unavailable or a manual restart is urgently required:

```bash
# 1. Trigger rolling restart
kubectl rollout restart deployment/trinetra-ui -n trinetra

# 2. Monitor rollout status in real-time
kubectl rollout status deployment/trinetra-ui -n trinetra --timeout=180s

# 3. Verify running pods
kubectl get pods -n trinetra -l app=trinetra-ui -o wide
```

### 2.3 Staging Verification Checklist

Before opening user traffic to a newly deployed revision:

- [ ] **Liveness Probe:** `curl -fsS http://localhost:3000/api/health` returns `{"status":"ok"}`.
- [ ] **Readiness Probe:** `curl -fsS http://localhost:3000/api/ready` returns `{"status":"ready"}` with `healthy: true` across all downstream dependencies.
- [ ] **Metrics Scrape:** `curl -fsS http://localhost:3000/api/metrics` returns Prometheus metrics (`trinetra_ui_http_requests_total`).
- [ ] **Authentication:** Login successfully with a test user; verify `dsai_access_token` and `dsai_tenant_id` cookies are populated.
- [ ] **Media Retrieval:** Open search dashboard and confirm thumbnail images load via `/api/media`.
- [ ] **SSE Live Alerts:** Open live monitoring page and confirm SSE stream receives heartbeat ticks within 15 seconds.

---

## 3. Rollback Procedures

### 3.1 Immediate Rollback via ArgoCD

If an alert fires immediately following an ArgoCD deployment:

```bash
# 1. Sync directly to the previous known-good Git commit SHA
argocd app sync trinetra-ui-prod --revision <PREVIOUS_COMMIT_SHA>

# 2. Wait for pods to reconcile
argocd app wait trinetra-ui-prod --health --timeout 180
```

### 3.2 Emergency Rollback via `kubectl`

When immediate mitigation is required and GitOps sync cannot be performed fast enough:

```bash
# 1. Check revision history
kubectl rollout history deployment/trinetra-ui -n trinetra

# 2. Roll back to immediate previous revision
kubectl rollout undo deployment/trinetra-ui -n trinetra

# 3. Or roll back to a specific known-good revision
kubectl rollout undo deployment/trinetra-ui -n trinetra --to-revision=<REVISION_NUMBER>

# 4. Monitor rollout until complete
kubectl rollout status deployment/trinetra-ui -n trinetra --timeout=120s

# 5. Verify pod status
kubectl get pods -n trinetra -l app=trinetra-ui
```

---

## 4. Common Incident Runbooks

### Incident 1: 401 Unauthorized Cascade

**Symptoms:**
- Widespread user session logouts.
- High rate of HTTP 401 responses on downstream microservice proxy calls.
- Browser console shows `401 Unauthorized` on `/api/ready` or protected routes.

**Root Causes:**
1. Clock drift between Kubernetes worker nodes (causing JWT `iat`/`exp` mismatch).
2. Secret rotation out-of-sync: `AuthService` updated its JWT signing key before `trinetra-ui` or client tokens refreshed.
3. Network partition between `trinetra-ui` and `AuthService` on port 8002.

**Diagnostic Steps:**
```bash
# 1. Check AuthService health from within a UI pod
kubectl exec -it deployment/trinetra-ui -n trinetra -- wget -qO- http://auth-service:8002/health

# 2. Verify clock synchronization across nodes
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.addresses[0].address}{"\n"}{end}' | while read name ip; do
  ssh $ip "timedatectl status | grep 'System clock synchronized'"
done

# 3. Check UI pod logs for JWT decoding/verification errors
kubectl logs -n trinetra -l app=trinetra-ui --tail=200 | grep -i "token"
```

**Resolution Steps:**
- If clock drift: sync NTP on affected nodes (`sudo systemctl restart chronyd` or `systemd-timesyncd`).
- If secret mismatch: restart `trinetra-ui` pods to pull updated ConfigMaps/Secrets:
  ```bash
  kubectl rollout restart deployment/trinetra-ui -n trinetra
  ```

---

### Incident 2: Thumbnail & Media Loading Failures

**Symptoms:**
- Search result cards and incident review galleries display broken image placeholders.
- Requests to `/api/media?path=...` return HTTP 404, 502, or 504.

**Root Causes:**
1. MinIO service down or unreachable from the UI network policy.
2. Ingress proxy body or buffer limits rejecting image payloads.
3. Presigned URL expiration or bucket permission misconfiguration.

**Diagnostic Steps:**
```bash
# 1. Check MinIO pod status and logs
kubectl get pods -n trinetra -l app=minio
kubectl logs -n trinetra -l app=minio --tail=100

# 2. Test MinIO DNS resolution and connectivity from inside a UI pod
kubectl exec -it deployment/trinetra-ui -n trinetra -- nc -zv minio 9000

# 3. Check NetworkPolicy compliance for port 9000 egress
kubectl describe networkpolicy trinetra-ui-network-policy -n trinetra
```

**Resolution Steps:**
- Ensure `k8s/base/ui/network-policy.yaml` explicitly allows TCP port `9000` egress (verified in Issue #57).
- If MinIO pod crashed due to PVC storage exhaustion, expand PVC or trigger retention prune:
  ```bash
  kubectl describe pvc minio-data-pvc -n trinetra
  ```

---

### Incident 3: SSE Alert Feed Lag or Connection Drops

**Symptoms:**
- Real-time alert badges stop updating on the operator dashboard.
- Client browsers show repeated reconnect toasts ("Live Feed Reconnecting...").
- Ingress logs show HTTP 499 or 504 on `/api/alerts/stream`.

**Root Causes:**
1. Nginx Ingress timeout closing idle SSE connections (default is 60s).
2. `WatchlistMatcherService` event queue backpressured or Redis Pub/Sub dropped.
3. Client browser hitting maximum concurrent HTTP/1.1 connections (HTTP/2 required).

**Diagnostic Steps:**
```bash
# 1. Check WatchlistMatcherService logs
kubectl logs -n trinetra -l app=watchlist-matcher --tail=150

# 2. Inspect Ingress controller annotations for proxy timeout
kubectl get ingress trinetra-ui -n trinetra -o yaml | grep proxy-read-timeout
```

**Resolution Steps:**
- Ensure Ingress annotation `nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"` is set to keep long-lived SSE connections open.
- Verify the Web Stream handler in `trinetra-ui` sends periodic heartbeat pings (every 15s) to prevent intermediary proxy timeouts.
- Restart `WatchlistMatcherService` if event loop is stalled:
  ```bash
  kubectl rollout restart deployment/watchlist-matcher -n trinetra
  ```

---

### Incident 4: High Memory / Container Restarts (OOMKilled)

**Symptoms:**
- Pods terminating with exit code `137` (`OOMKilled`).
- `kubectl get pods` shows restarts climbing rapidly (`CrashLoopBackOff`).
- Response latencies degrade significantly before restarts.

**Root Causes:**
1. High-concurrency video chunk uploads accumulating in Node.js server heap.
2. In-memory caching without eviction limits.
3. Memory limit (currently `512Mi`) insufficient for peak concurrent search sessions.

**Diagnostic Steps:**
```bash
# 1. Check last termination reason
kubectl describe pod -n trinetra -l app=trinetra-ui | grep -A 4 "Last State"

# 2. Check memory usage metrics
kubectl top pods -n trinetra -l app=trinetra-ui
```

**Resolution Steps:**
- For immediate emergency relief, patch the deployment memory limit to `1024Mi`:
  ```bash
  kubectl set resources deployment/trinetra-ui -n trinetra --limits=memory=1024Mi
  ```
- Verify video uploads are using direct-to-object-storage presigned PUT URLs rather than proxying raw multipart streams through Node.js.
- Ensure HPA is enabled and scaling out based on CPU/Memory thresholds.

---

## 5. On-Call & Escalation Matrix

### 5.1 Incident Severity Levels

| Severity | Definition | Target Initial Response | Resolution SLA |
| :--- | :--- | :--- | :--- |
| **P0 (Critical)** | Entire UI unavailable; all users unable to authenticate or search; CJIS audit compromised | `< 15 minutes` | `< 2 hours` |
| **P1 (High)** | Core feature degraded (e.g. SSE alert feed down, thumbnails failing for all tenants) | `< 30 minutes` | `< 4 hours` |
| **P2 (Medium)** | Non-critical feature failure (e.g. CSV analytics export error, mobile navbar quirk) | `< 2 hours` | `< 24 hours` |
| **P3 (Low)** | Minor visual defect, documentation clarification | `< 1 business day` | Next sprint |

### 5.2 Contact Matrix

| Role | Primary Contact | Secondary Contact | Escalation Channel |
| :--- | :--- | :--- | :--- |
| **Frontend On-Call** | `@frontend-lead` | `@frontend-duty` | `#trinetra-alerts-ui` |
| **Backend Core On-Call**| `@backend-lead` | `@infra-duty` | `#trinetra-alerts-core` |
| **Infrastructure / DevOps**| `@sre-lead` | `@cloud-ops` | `#trinetra-infra-ops` |
| **Incident Commander** | Rotating SRE IC | Engineering Director | `#trinetra-war-room` |

---

## 6. Key Prometheus Alert Definitions

These alerts are configured in Prometheus and route directly to Alertmanager / PagerDuty:

```yaml
groups:
- name: trinetra-ui.alerts
  rules:
  - alert: TrinetraUIHigh5xxRate
    expr: sum(rate(trinetra_ui_http_requests_total{status=~"5.."}[5m])) / sum(rate(trinetra_ui_http_requests_total[5m])) * 100 > 2
    for: 3m
    labels:
      severity: critical
    annotations:
      summary: "trinetra-ui 5xx error rate > 2%"
      description: "UI service is returning >2% 5xx errors over the last 5 minutes. Check pod logs and downstream AuthService/SearchService."

  - alert: TrinetraUIP95LatencyHigh
    expr: histogram_quantile(0.95, sum(rate(trinetra_ui_http_request_duration_seconds_bucket[5m])) by (le)) > 0.5
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "trinetra-ui p95 latency > 500ms"
      description: "p95 response latency exceeded 500ms for 5 minutes. Inspect downstream microservice response times."

  - alert: TrinetraUIContainerRestarting
    expr: rate(kube_pod_container_status_restarts_total{container="trinetra-ui"}[15m]) * 900 > 2
    for: 1m
    labels:
      severity: high
    annotations:
      summary: "trinetra-ui pod restarting frequently"
      description: "trinetra-ui container has restarted > 2 times in 15 minutes. Check for OOMKilled or probe failures."

  - alert: TrinetraUIReadinessFailing
    expr: probe_success{instance=~".*/api/ready"} == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "trinetra-ui /api/ready probe failing"
      description: "Readiness probe failing. One or more backend microservices are unreachable from trinetra-ui."
```
