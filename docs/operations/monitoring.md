# Monitoring & Alerting

This guide covers setting up monitoring, metrics collection, and alerting for ClipSight production deployments.

---

## Overview

ClipSight exposes Prometheus metrics on all services. Recommended stack:

- **Metrics collection**: Prometheus
- **Visualization**: Grafana dashboards
- **Alerting**: Alertmanager (email, Slack, PagerDuty)
- **Log aggregation**: Loki or Elasticsearch
- **Tracing**: Jaeger (optional)

---

## Prometheus Metrics

All services expose `/metrics` endpoint (no auth in default config, but you should add auth in production).

### API Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `clipsight_api_requests_total` | Counter | Total API requests by path, method, status |
| `clipsight_api_request_duration_seconds` | Histogram | Request latency distribution |
| `clipsight_api_active_requests` | Gauge | Currently processing requests |
| `clipsight_videos_uploaded_total` | Counter | Total videos uploaded |
| `clipsight_searches_performed_total` | Counter | Total search queries |
| `clipsight_search_results_count` | Histogram | Number of results returned |

Example query: "95th percentile search latency over 1 hour"

```promql
histogram_quantile(0.95, rate(clipsight_search_results_count_bucket[1h]))
```

---

### Extractor Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `clipsight_extractor_frames_extracted_total` | Counter | Total frames extracted |
| `clipsight_extractor_processing_seconds` | Histogram | Time to extract one segment |
| `clipsight_extractor_queue_depth` | Gauge | Number of segments waiting |
| `clipsight_extractor_active_workers` | Gauge | Number of extractor pods available |
| `clipsight_extractor_errors_total` | Counter | Extraction failures by reason |

---

### Embedder Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `clipsight_embedder_frames_embedded_total` | Counter | Total frames processed |
| `clipsight_embedder_batch_duration_seconds` | Histogram | Time per batch |
| `clipsight_embedder_queue_depth` | Gauge | Frames waiting in MinIO |
| `clipsight_embedder_memory_usage_bytes` | Gauge | RAM consumption |
| `clipsight_embedder_inference_seconds` | Histogram | CLIP model inference time |

---

### Milvus Metrics

Milvus exposes its own metrics (use built-in exporter):

| Metric | Description |
|--------|-------------|
| `milvus_insert_cost` | Insert latency |
| `milvus_search_cost` | Search latency |
| `milvus_index_size` | Size of HNSW index in bytes |
| `milvus_num_entities` | Number of vectors indexed |

---

### Infrastructure Metrics

Kubernetes & node metrics via `kube-state-metrics` and `node-exporter`:

| Metric | Description |
|--------|-------------|
| `kube_pod_status_ready` | Pod health |
| `kube_deployment_status_replicas_available` | Available replicas |
| `node_cpu_seconds_total` | Node CPU usage |
| `node_memory_MemAvailable_bytes` | Available RAM |
| `container_fs_usage_bytes` | Disk consumption |

---

## Grafana Dashboards

Import these dashboard IDs (or create from JSON in `docs/operations/grafana/`):

### Dashboard 1: System Overview

Shows:
- Request rate (RPS) by endpoint
- Error rate (5xx responses)
- P95 latency
- Active video processing count
- System uptime

### Dashboard 2: Processing Pipeline

Shows:
- Extractor queue depth (backlog)
- Embedder FPS (frames per second)
- Frame extraction rate
- Videos ready per hour
- Storage usage (MinIO, Milvus, PostgreSQL)

### Dashboard 3: Resource Utilization

Shows:
- CPU usage by pod
- Memory usage by pod
- GPU utilization (if using)
- Network I/O
- Disk I/O

### Dashboard 4: Business Metrics

Shows:
- Total videos stored
- Active tenants
- Search queries per day
- Top search queries (from logs)
- Feature usage breakdown

---

## Alerting Rules

Configure Alertmanager to send notifications.

### Critical Alerts (P0)

```yaml
- alert: API_Down
  expr: up{job="clipsight-api"} == 0
  for: 2m
  annotations:
    severity: critical
    summary: "ClipSight API is down"
    description: "API endpoint has been unreachable for >2 minutes"
    
- alert: MilvusHighLatency
  expr: histogram_quantile(0.99, rate(clipsight_milvus_search_duration_seconds_bucket[5m])) > 5
  for: 5m
  annotations:
    severity: critical
    summary: "Search latency >5s P99"
    description: "Users experiencing slow search"
    
- alert: ExtractorQueueBlocked
  expr: clipsight_extractor_queue_depth > 1000
  for: 10m
  annotations:
    severity: critical
    summary: "Extractor queue > 1000 segments"
    description: "Video processing backlog, no extractors available"
    
- alert: DatabaseDown
  expr: up{job="postgres"} == 0
  for: 1m
  annotations:
    severity: critical
    summary: "PostgreSQL unreachable"
```

### Warning Alerts (P1)

```yaml
- alert: Storage90PercentFull
  expr: (container_fs_usage_bytes{mountpoint="/var/lib/postgresql/data"} / container_fs_limit_bytes{mountpoint="/var/lib/postgresql/data"}) > 0.9
  for: 1h
  annotations:
    severity: warning
    summary: "Database storage >90% full"
    
- alert: HighErrorRate
  expr: rate(clipsight_api_requests_total{status=~"5.."}[5m]) / rate(clipsight_api_requests_total[5m]) > 0.05
  for: 5m
  annotations:
    severity: warning
    summary: "Error rate >5%"
```

---

## Logging

### Structured JSON Logs

All applications emit JSON logs:

```json
{
  "timestamp": "2025-04-03T14:30:00.123Z",
  "level": "INFO",
  "service": "api",
  "message": "Video processing started",
  "video_id": "vid_abc123",
  "tenant_id": "acme-corp",
  "user_id": "user_456",
  "request_id": "req_789",
  "duration_ms": 145
}
```

### Loki Query Examples

**Find errors for a specific video**:

```
{service="api", video_id="vid_abc123"} |= "error"
```

**Search audit logs for user actions**:

```
{service="audit", user_id="user_456"} | json | tenant_id="acme-corp"
```

**Slowest searches in last hour**:

```
{service="api", path="/search"} | json | query_time_ms > 1000
```

---

## Distributed Tracing (Optional)

Enable OpenTelemetry:

```python
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

tracer = trace.get_tracer(__name__)
FastAPIInstrumentor.instrument_app(app)
```

Traces exported to Jaeger:

```bash
docker run -d --name jaeger \
  -p 16686:16686 \
  jaegertracing/all-in-one:latest
```

View traces at http://localhost:16686.

---

## Health Checks

### Liveness Probe (Kubernetes)

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

### Readiness Probe

```yaml
readinessProbe:
  httpGet:
    path: /health/ready
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 5
```

**/health** endpoint checks:
- Database connection
- Redis connection
- Milvus connection
- Disk space

---

## Backup & Recovery Metrics

Monitor backup success:

| Metric | Desired State |
|--------|---------------|
| `backup_last_success_timestamp` | < 24 hours ago |
| `backup_size_bytes` | Stable (not growing unexpectedly) |
| `restore_test_last_success` | Last 7 days |

[Backup procedure](../backup-restore.md)

---

## Capacity Planning

Monitor these to plan scaling:

- **Storage growth rate**: GB/day → project 6-month storage needs
- **Search QPS**: Queries per second → scale Milvus nodes accordingly
- **Upload bandwidth**: Mbps → ensure network not saturated
- **CPU/Memory trends**: Steady increase may need more nodes

Alerts:
- Storage usage >80% for 3 days → scale MinIO
- Search latency P95 >500ms → add Milvus query nodes
- Queue depth consistently >100 → add extractors

---

## Dashboard Screenshots

<img src="../../assets/dashboards/overview.png" alt="System Overview" width="600">

<img src="../../assets/dashboards/processing.png" alt="Processing Pipeline" width="600">

*(Screenshots in this documentation; actual dashboards in repo `docs/assets/dashboards/`)*

---

## Setting Up Prometheus (Quick)

For Kubernetes deployments:

```bash
# Install kube-prometheus-stack (includes Prometheus, Alertmanager, Grafana)
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring --create-namespace

# Add ServiceMonitor for ClipSight services (annotations on deployments)
kubectl annotate deployment clipsight-api prometheus.io/scrape: "true"
kubectl annotate deployment clipsight-api prometheus.io/port: "8080"
```

Grafana will auto-discover dashboards from ConfigMap in `k8s/base/monitoring/`.

---

## Slack/Email Alerts

Configure Alertmanager:

```yaml
receivers:
- name: slack-alerts
  slack_configs:
  - api_url: https://hooks.slack.com/services/YOUR/WEBHOOK/URL
    channel: '#alerts'
    send_resolved: true
- name: email-team
  email_configs:
  - to: ops@clipsight.com
    from: alertmanager@clipsight.com
    smarthost: smtp.gmail.com:587
    auth_username: alertmanager@clipsight.com
    auth_password: APP_PASSWORD
```

---

## Troubleshooting Monitoring

**Metrics not appearing in Prometheus?**
- Check ServiceMonitor selector matches labels
- Verify `/metrics` endpoint returns 200
- Check Prometheus target status in UI (`http://prometheus:9090/targets`)

**Alerts not firing?**
- Check Alertmanager is running and routing rules correct
- Verify `for:` duration elapsed
- Test with `curl -d '' http://alertmanager:9093/api/v2/alerts/test`

**Grafana dashboards blank?**
- Verify Prometheus data source configured
- Check time range (last 1 hour vs last 6 hours)
- Query in Explore to debug panel queries

---

## Further Reading

- [Backup & restore](../backup-restore.md)
- [Troubleshooting](../troubleshooting.md)
- [Production checklist](../checklists/production.md)
- [Security hardening](../operations/security-hardening.md)
