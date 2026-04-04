# deepSightAI Trinetra Enterprise Roadmap & Deployment Guide

## Executive Summary

Transforming deepSightAI Trinetra from a single-tenant prototype to an enterprise-grade, multi-tenant SaaS platform serving millions of videos for diverse sectors (law enforcement, commercial, logistics) with security-first architecture.

---

## Current State Analysis

### Existing Capabilities
- **Functional video processing pipeline** (upload → extract → embed)
- **Modular microservices** (API, extractor, embedder, registry)
- **Containerized deployment** with Docker Compose
- **Vector search** via Milvus with CLIP embeddings
- **Scalable extractor workers** (horizontal scaling possible)
- **Service discovery** via Redis registry

### Critical Gaps for Enterprise
| Gap | Impact | Priority |
|-----|--------|----------|
| No authentication/authorization | Security vulnerability, no tenant isolation | **P0 - Critical** |
| Single-tenant architecture | Cannot serve multiple customers | **P0 - Critical** |
| No audit logging | Non-compliant for regulated sectors | **P0 - Critical** |
| No encryption at rest/in-transit | Data breach risk | **P0 - Critical** |
| No tenant data isolation | Data leakage between customers | **P0 - Critical** |
| No user management/subscriptions | Cannot bill customers | **P1 - High** |
| No rate limiting/quotas | Abuse risk, no usage control | **P1 - High** |
| Single Milvus instance | Not horizontally scalable | **P1 - High** |
| No observability (metrics, tracing) | Hard to monitor at scale | **P1 - High** |
| No backup/DR strategy | Data loss risk | **P2 - Medium** |
| No CDN integration | Poor global performance | **P2 - Medium** |
| No API gateway | Direct service exposure | **P2 - Medium** |
| No config management | Manual config edits | **P2 - Medium** |

---

## Target Enterprise Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          API Gateway (Kong/Traefik)                     │
│  - Authentication (JWT/OAuth2)                                          │
│  - Rate Limiting per tenant                                            │
│  - Request Routing                                                    │
│  - TLS Termination                                                    │
│  - API Key management                                                 │
└────────────┬────────────────────────────────────────────────────────────┘
             │
    ┌────────┴─────────────────────────────────────────────┐
    │                                                       │
    ▼                                                       ▼
┌─────────────────┐                              ┌──────────────────┐
│  Auth Service   │                              │   Tenant Service │
│  (OAuth2/Keycloak)│                              │  (User/Role Mgmt)│
└─────────────────┘                              └──────────────────┘
             │                                               │
             └───────────┬───────────────────────────────────┘
                         │
    ┌────────────────────▼────────────────────────────────────────────┐
    │              Main API Router (Multi-tenant)                    │
    │  - Tenant context from JWT/API key                              │
    │  - Quota enforcement                                            │
    │  - Audit logging                                               │
    └────────────┬─────────────────────────────────────────────────────┘
                 │
        ┌────────┴──────────────────────────────────────────┐
        │                                                   │
        ▼                                                   ▼
┌──────────────────┐                              ┌──────────────────┐
│ Video Ingestion  │                              │   Search API     │
│   Service        │                              │   (FastAPI)      │
│  - Multi-tenant  │                              │  - Custom models │
│    storage paths │                              │    per sector    │
│  - Quota checks  │                              │  - Filtering by  │
└──────────────────┘                              │    tenant        │
                 │                                └──────────────────┘
                 │                                       │
    ┌────────────▼────────────────────────────────────────┴───────┐
    │                   Shared Infrastructure                     │
    │  - MinIO (tenant-prefixed buckets)                         │
    │  - Milvus (tenant-prefixed collections + metadata)         │
    │  - Redis (tenant-scoped keys)                              │
    │  - PostgreSQL (tenant metadata, users, subscriptions)      │
    └─────────────────────────────────────────────────────────────┘
                         │
        ┌────────────────┴───────────────────┐
        │                                    │
        ▼                                    ▼
┌──────────────┐                    ┌──────────────┐
│  Extractor   │                    │   Embedder   │
│  Workers     │                    │   Pool       │
│  (K8s HPA)   │                    │  (K8s HPA)   │
└──────────────┘                    └──────────────┘
```

---

## Feature Roadmap (6-12 Months)

### Phase 1: Foundation (Months 1-2) - **CRITICAL**
**Goal**: Secure, Multi-tenant core infrastructure with vendor-neutral deployment

#### 1.1 Kubernetes-Native Architecture (P0)

**Before Phase 1 begins**, migrate from Docker Compose to Kubernetes using **vendor-neutral, portable manifests**:

- Create `k8s/base/` with common manifests (Deployments, Services, ConfigMaps, Secrets)
- Use `kustomize` overlays for different environments:
  - `overlays/development/` - Single node, minimal resources (for testing)
  - `overlays/production/` - Full enterprise with HPA
- Package applications as **Helm charts** for reusability
- Ensure all services run identically on:
  - k3s (edge/on-premise)
  - Full K8s (EKS/GKE/AKS/OpenShift)
  - Docker Compose (via Kompose conversion for local dev)

**Deliverables**:
- All services have Kubernetes manifests
- Local development uses `k3d` (k3s in Docker) or `minikube` for parity
- CI pipeline tests K8s manifests with `kubeval` and `kube-score`
- GitOps ready: ArgoCD can deploy any environment from same Git repo

**Why Kubernetes first?**
- Docker Compose cannot scale to enterprise (no orchestration, no HPA, no service mesh)
- K8s provides deployment portability across ALL infrastructures
- Enables cloud-agnostic strategy from day 1
- Industry standard for enterprise

#### 1.2 Multi-Tenancy Architecture (P0)
**Strategy**: Schema-based isolation (separate PostgreSQL schemas per tenant) + Namespace isolation in object storage

**Data Isolation**:
- **PostgreSQL**: Each tenant gets separate schema (`tenant_<id>`)
- **MinIO**: Bucket prefixes: `{tenant_id}/videos/`, `{tenant_id}/frames/`
- **Milvus**: Collection per tenant: `video_frames_{tenant_id}` OR single collection with tenant_id field + index
- **Redis**: Key prefixes: `{tenant_id}:extractor:*`

**Tenant Lifecycle Management**:
- Tenant provisioning (create schema, initialize Milvus collection)
- Tenant suspension/reactivation
- Tenant deletion (cascade with approval workflow)

**Implementation**:
- Database connection pooler that switches schema based on JWT claim
- Middleware to inject `tenant_id` into all request contexts
- Tenant-aware repository pattern

#### 1.3 Encryption & Security (P0)
- **In-Transit**: TLS 1.3 everywhere (API, service mesh, DB connections)
- **At-Rest**: Encrypted MinIO buckets (SSE-S3 or SSE-KMS)
- **Milvus**: Encrypted storage (disk encryption + field-level for sensitive metadata)
- **Database**: Transparent Data Encryption (TDE) for PostgreSQL
- **Secrets Management**: HashiCorp Vault or AWS Secrets Manager integration
- **Network**: Private networking, no public exposure except API Gateway

#### 1.4 Audit Logging (P0)
Immutable audit trail for all operations:

**Log Schema**:
```json
{
  "tenant_id": "tenant_123",
  "user_id": "user_456",
  "timestamp": "2025-04-01T10:23:45Z",
  "action": "video.upload",
  "resource_type": "video",
  "resource_id": "vid_789",
  "ip_address": "192.168.1.1",
  "user_agent": "Mozilla/...",
  "metadata": {"file_size": 104857600, "duration": 3600},
  "outcome": "success|failure",
  "failure_reason": "..."
}
```

**Implementation**:
- Centralized audit service (append-only PostgreSQL table)
- Immutable logs (WORM storage or append-only with retention policies)
- Audit log export to SIEM (Splunk, Datadog, Elastic)
- Compliance reports (GDPR, SOC2, CJIS for law enforcement)

---

### Phase 2: Multi-Sector Analytics (Months 3-4)

#### 2.1 Sector-Specific Search Models

**Implementation Strategy**: Plugin architecture for detection models:
```
embedder/
├── models/
│   ├── base_embedder.py    # CLIP base
│   ├── plugins/
│   │   ├── law_enforcement/
│   │   │   ├── __init__.py
│   │   │   ├── lpr.py       # License plate recognition
│   │   │   ├── weapon_detection.py
│   │   │   ├── face_blur.py
│   │   │   └── chain_of_custody.py
│   │   ├── commercial/
│   │   │   ├── demographics.py
│   │   │   ├── heatmap.py
│   │   │   ├── queue_detection.py
│   │   │   └── brand_detection.py
│   │   └── logistics/
│   │       ├── asset_tracking.py
│   │       ├── ppe_detection.py
│   │       └── damage_detection.py
│   └── plugin_loader.py      # Dynamic loading based on tenant.sector
```

**Law Enforcement**:
- Person/vehicle re-identification (custom CLIP fine-tuned on surveillance)
- License plate recognition (LPR) integration (OpenALPR or custom)
- Weapon detection flagging (YOLOv7/v8)
- Suspicious behavior patterns (loitering, running)
- Face detection with privacy blur option (GDPR compliant)
- Chain of custody tracking for evidence (audit trail for evidence handling)
- **Retention**: Configurable (7 years for criminal investigations)

**Commercial / Retail**:
- Customer demographics (age/gender estimation - opt-in, privacy-first)
- Dwell time analysis per shelf/display
- Heatmap generation (foot traffic patterns)
- Queue length detection
- Conversion attribution (view → purchase)
- Brand logo detection
- **Retention**: 30-90 days (privacy-focused, GDPR compliant)

**Logistics / Supply Chain**:
- Asset tracking (forklifts, pallets, containers)
- Package counting in loading docks
- Vehicle/container ID recognition
- Damage detection (package condition)
- Dock door utilization
- Employee safety compliance (PPE detection - hard hats, safety vests)
- **Retention**: 1-2 years for operations

**Implementation**:
- Detection models as **pluggable Python modules**
- Configuration per tenant: `sector: law_enforcement|commercial|logistics`
- Model routing in embedder: load plugin based on tenant metadata
- Metadata tagging: `detections: [{type: "person", confidence: 0.92, bbox: [...]}]`
- All detection models **containerized separately** for GPU sharing
- Consider separate "DetectionService" if models become too heavy for embedder

**Testing**: Each plugin has unit tests with synthetic images and integration tests against sample videos.

#### 2.2 Custom Model Training Pipeline (Optional Premium)
Allow enterprise customers to fine-tune CLIP on their own data:
- Upload labeled dataset via UI
- Training orchestration (Kubernetes jobs)
- Model registry (MLflow)
- A/B testing between models
- Model versioning and rollback

---

### Phase 3: Subscription & Billing (Months 5-6)

#### 3.1 Tiered Subscription Model

| Tier | Price | Videos/Month | Users | Storage | Search QPS | SLA | Features |
|------|-------|--------------|-------|---------|------------|-----|----------|
| Starter | $99 | 1,000 | 3 | 100 GB | 10 | 99.5% | Basic search, 7-day retention |
| Professional | $499 | 10,000 | 10 | 1 TB | 100 | 99.9% | + Sector analytics, custom models |
| Enterprise | Custom | Unlimited | Unlimited | Unlimited | Custom | 99.99% | + On-premise, audit logs, compliance |
| Government | Custom | Unlimited | Unlimited | Unlimited | Custom | 99.99% | + CJIS compliance, air-gapped |

#### 3.2 Usage Metering
- **Video minutes processed** (ingestion to embedding)
- **Storage consumed** (raw video + extracted frames, before deletion)
- **Search queries** (per month)
- **Concurrent extractors** (parallel processing slots)
- **Retention period** (days)
- **API calls** (per endpoint)

**Implementation**:
- Metering service that aggregates usage events from:
  - Video upload completion
  - Frame extraction counts
  - Search query logging
  - Storage scanner (periodic)
- Usage counters in PostgreSQL per tenant
- Billing integration (Stripe, Paddle, or custom)
- Overage detection → soft/hard limits

#### 3.3 Quota Enforcement
- Per-tenant limits in database
- Middleware checks before accepting uploads/search
- Soft limits: warn at 80%, reject at 100% (or allow overage with charge)
- Real-time usage dashboards for admins

---

### Phase 4: Scalability & Performance (Months 7-8)

#### 4.1 Horizontal Scaling
- **Extractors**: Kubernetes Horizontal Pod Autoscaler (HPA) based on queue length
- **Embedders**: GPU node pool with HPA based on GPU utilization
- **API**: HPA based on CPU/RPS
- **Database**: Connection pool sizing, read replicas for queries

#### 4.2 Milvus Sharding
- Replace single Milvus with **Milvus cluster** (distributed mode)
- Shard by `tenant_id` (each tenant on specific nodes) OR by `video_id`
- Load balancing via query routers
- Increased `INSERT_BATCH_SIZE` for throughput
- Partition pruning: queries filter by partition (tenant)

#### 4.3 Video Storage Tiering
- **Hot tier**: Recent videos (last 30 days) on SSD-backed MinIO
- **Warm tier**: 30-90 days on HDD
- **Cold tier**: >90 days to S3 Glacier / Azure Archive (or deletion)
- Lifecycle policies in MinIO

#### 4.4 Content Delivery Network (CDN)
- Integrate CloudFront / Cloudflare for frame image delivery
- Cache public presigned URLs (short-lived signed URLs anyway)
- Edge caching reduces load on MinIO

#### 4.5 Async Processing with Message Queue
Replace polling with event-driven architecture:
- **RabbitMQ / Apache Pulsar / Kafka** as backbone
- Events: `video.uploaded`, `frames.extracted`, `embeddings.ready`
- Workers consume events instead of polling MinIO
- Better scaling, lower latency

---

### Phase 5: Advanced Features (Months 9-12)

#### 5.1 Advanced Search Capabilities
- **Temporal search**: "Find all videos with person between 2:30-3:15"
- **Spatial search**: "Show all red cars in top-left quadrant"
- **Similarity chains**: "Find videos similar to this video" (aggregate frame similarities)
- **Hybrid search**: Combine semantic + metadata (date, camera ID, detection labels)
- **Fuzzy timestamp matching**: "Around 5 minutes in"

#### 5.2 Collaboration Features
- Shared workspaces within tenant
- Annotation tools (draw bounding boxes, label objects)
- Export results (CSV, JSON, PDF reports)
- Alerting: "Notify me when X is detected"
- Scheduled reports (daily/weekly email digests)

#### 5.3 AI-Powered Analytics Dashboard
- Per-tenant analytics:
  - Top detected objects
  - Peak hour traffic
  - Storage growth trends
  - Search popularity
  - Processing latency metrics
- Export to BI tools (Looker, PowerBI)

#### 5.4 Mobile Apps
- iOS/Android apps for field officers (law enforcement) or managers (commercial)
- Real-time alerts push notifications
- Offline mode with sync

---

## Deployment Strategies

### A. Cloud-Native (Vendor-Neutral Kubernetes)

**Architecture**: Deploy to ANY Kubernetes cluster (EKS, GKE, AKS, OpenShift) using **same manifests**

```
Kubernetes Cluster (any cloud provider)
├── Namespace: platform (auth, registry, api-gateway)
├── Namespace: extractors (HPA workers)
├── Namespace: embedders (GPU node group, separate node pool)
├── Namespace: data (PostgreSQL, Redis, Milvus, MinIO - all self-hosted)
├── Namespace: monitoring (Prometheus, Grafana, Loki)
└── Ingress: NGINX Ingress Controller (vendor-agnostic)
```

**Infrastructure as Code**: Kubernetes YAML + Helm + Kustomize (NOT cloud-specific Terraform)
- All manifests in `k8s/base/` and `k8s/overlays/{env}/`
- Works identically on AWS EKS, Google GKE, Azure AKS, or on-premise K8s
- Single Git repository deploys everywhere

**CI/CD**: GitHub Actions / GitLab CI → Container Registry → **ArgoCD GitOps**

**Observability**: CNCF stack (Prometheus + Grafana + Loki + Jaeger)

**Cost Optimization**:
- Spot/preemptible instances for extractors (fault-tolerant)
- Reserved/committed instances for stateful workloads
- Cluster autoscaler for elastic capacity
- Same strategy works on bare metal (different VM provisioning)

**Key Differences from AWS Example**:
- **No RDS**: Self-hosted PostgreSQL on K8sStatefulSet
- **No ElastiCache**: Self-hosted Redis Cluster
- **No S3**: Self-hosted MinIO distributed mode
- **No Secrets Manager**: HashiCorp Vault or sealed-secrets
- **No CloudFront**: Use MinIO directly or any CDN of choice
- **No Cloud WAF**: Use ingress controller WAF or cloud provider's WAF (optional)

**Advantage**: You can switch from AWS to Google in 1 hour by pointing ArgoCD to GKE cluster. No code changes, no manifest changes (mostly). Data migration separate.

### B. On-Premise / Air-Gapped (Government/Law Enforcement)

```
Data Center
├── Kubernetes Cluster (Rancher/K3s)
│   ├── Air-gapped registry (Harbor)
│   ├── All images pre-pulled and signed
│   └── Network policies: strict pod-to-pod
├── Storage: Ceph or Pure Storage (encrypted)
├── PostgreSQL (Patroni HA cluster)
├── Redis (Redis Cluster with AUTH)
├── MinIO (distributed mode, 4+ nodes, erasure coding)
├── Milvus on bare metal servers with GPUs (NVIDIA T4/A10)
├── Hardware Security Modules (HSM) for key management
├── Vault for secrets (air-gapped mode)
├── SIEM integration (Splunk/IBM QRadar)
├── Backup: Veeam / Commvault with air-gap
└── Network: DMZ for API Gateway, internal for services
```

**Requirements**:
- No outbound internet connectivity after deployment
- Bring-your-own-license (BYOL) for all software
- Hardware specification sheet provided
- Installation playbooks (Ansible)
- Offline update mechanism (USB/ISO)

**Compliance**:
- CJIS (Criminal Justice Information Systems) for US law enforcement
- FedRAMP Moderate/High
- ISO 27001
- NIST 800-53

### C. Hybrid / Edge Deployment

For logistics/retail with multiple store locations:

```
Cloud Region (Central)
├── Platform services (auth, billing, management)
├── ML model training
├── Global analytics aggregation
└── Customer support portal

Edge Locations (Store/Warehouse)
├── Mini cluster (1-2 nodes)
│   ├── Local extractor + embedder
│   ├── MinIO (local cache)
│   └── Optional Milvus read-replica
├── Internet gateway (VPN to cloud)
└── Offline mode: store videos locally if WAN fails, sync when back

Edge Orchestration:
- Central cluster manages edge deployments via GitOps
- Config rollout to all edges
- Edge health monitoring from cloud
```

---

## Security by Design

### 1. Defense-in-Depth

```
┌─────────────────────────────────────────────┐
│ Layer 7: API Gateway (WAF, DDoS)           │
├─────────────────────────────────────────────┤
│ Layer 6: AuthN/AuthZ (JWT, RBAC)           │
├─────────────────────────────────────────────┤
│ Layer 5: Network Policies (K8s NetworkPol)│
├─────────────────────────────────────────────┤
│ Layer 4: Service Mesh (Istio mTLS)         │
├─────────────────────────────────────────────┤
│ Layer 3: Encrypted Storage (TDE, SSE)      │
├─────────────────────────────────────────────┤
│ Layer 2: Secrets Management (Vault)        │
├─────────────────────────────────────────────┤
│ Layer 1: OS/Hardware (SELinux, TPM, HSM)  │
└─────────────────────────────────────────────┘
```

### 2. Data Security Controls

**Encryption**:
- All data at rest: AES-256 (MinIO SSE-KMS, PostgreSQL TDE, Milvus disk encryption)
- All data in transit: TLS 1.3 with mutual TLS (mTLS) for service-to-service
- Secrets: Vault with auto-rotation (DB passwords, API keys)

**Access Control**:
- **Zero Trust**: Always authenticate, always authorize
- **Least Privilege**: JWT claims → RBAC → resource-level ACLs
- **Just-in-Time Access**: Temporary elevated privileges with audit
- **Break-glass accounts**: Emergency access with MFA and approval workflow

**Audit & Compliance**:
- Immutable audit logs (append-only, WORM storage)
- Log integrity: cryptographic signing or blockchain-style hash chaining
- Real-time SIEM alerts for anomalous patterns:
  - Bulk data export
  - Access from unusual IPs
  - Failed auth storms
  - Privilege escalation
- Regular penetration testing (quarterly)
- Vulnerability scanning (daily,自动)

**Privacy by Design**:
- Data minimization: frames deleted after embedding (already implemented)
- Purpose limitation: data used only for contracted purpose
- Retention policies: automatic deletion after X days (tenant-configurable)
- Right to be forgotten: GDPR compliance API to delete all tenant data
- Anonymization: Optional face blur for law enforcement privacy

### 3. Compliance Frameworks

**Law Enforcement**:
- CJIS (Criminal Justice Information Systems) compliance
- FBI auditing requirements
- FBI's Criminal Justice Information Services (CJIS) Security Policy
- NIST 800-171 (Controlled Unclassified Information)
- FedRAMP Moderate

**Commercial / Retail**:
- GDPR (EU) - data subject rights, DPO
- CCPA/CPRA (California)
- PCI-DSS if payment data involved
- SOC2 Type II (security, availability, confidentiality)

**Logistics**:
- ISO 27001 (Information Security)
- TISAX (automotive industry)
- GDPR for employee monitoring (different rules)

**Implementation**: Separate compliance modules that enforce:
- Data residency: store data in specific regions only
- Data sovereignty: never cross borders without consent
- Export controls: restrict certain analytics by geography

---

## Subscriber & Tenant Management

### 1. Tenant Onboarding Flow

```
1. Sign-up (self-service or sales-assisted)
   └─> Credit check / contract signing
2. Tenant Provisioning (automated):
   - Create tenant record in PostgreSQL
   - Create tenant schema
   - Create MinIO bucket prefix
   - Create Milvus collection
   - Create Redis key namespace
   - Create subscription plan in billing system
   - Generate onboarding API keys
   - Send welcome email with credentials
3. Tenant Trial Period (14-30 days)
   - Limited quota (e.g., 100 videos)
   - All features enabled
   - Automated usage tracking
4. Conversion to Paid
   - Auto-billing via Stripe/Paddle
   - Quota increase
   - SLA guarantee
5. Ongoing:
   - Usage metering → invoice
   - Support requests (Jira/Helpdesk)
   - Quarterly business reviews (Enterprise)
```

### 2. Tenant Isolation Implementation

**Database**:
```sql
-- Tenant schema pattern
CREATE SCHEMA tenant_abc123;
GRANT ALL ON SCHEMA tenant_abc123 TO tenant_abc123_user;
-- All tables: tenant_abc123.videos, tenant_abc123.frames, etc.

-- Row-level security alternative (single schema)
CREATE POLICY tenant_isolation ON video_frames
  USING (tenant_id = current_setting('app.current_tenant')::UUID);
```

**Code**:
```python
# Middleware to set tenant context
@app.middleware("http")
async def set_tenant_context(request: Request, call_next):
    tenant_id = extract_tenant_from_jwt(request)
    # Set connection to use tenant schema
    database.set_schema(f"tenant_{tenant_id}")
    # Or set Postgres session variable for RLS
    await database.execute(f"SET app.current_tenant = '{tenant_id}'")
    response = await call_next(request)
    return response

# Repository pattern
class VideoRepository:
    async def create(self, video: Video, tenant_id: UUID):
        # All queries automatically filter by tenant_id
        query = """
            INSERT INTO videos (tenant_id, ...)
            VALUES (:tenant_id, ...)
        """
        await database.execute(query, {"tenant_id": tenant_id, ...})
```

**MinIO**:
```python
def get_tenant_bucket_path(tenant_id: str, bucket_type: str) -> str:
    return f"{tenant_id}/{bucket_type}"
    # e.g., "tenant_abc123/videos/myvideo.mp4"
```

**Milvus**:
```python
# Option 1: Separate collection per tenant
collection_name = f"video_frames_{tenant_id}"

# Option 2: Single collection with partition key
collection.create_partition(partition_name=tenant_id)
insert_data = [{"tenant_id": tenant_id, ...}]
collection.insert(data, partition_name=tenant_id)
search_expr = f"tenant_id == '{tenant_id}'"
results = collection.search(data, expr=search_expr)
```

### 3. Usage Tracking & Billing

**Metering Events** (published to Kafka/Pulsar):
```json
{
  "event_id": "uuid",
  "tenant_id": "tenant_abc",
  "user_id": "user_def",
  "type": "video.uploaded|video.processed|search.performed|storage.allocated",
  "quantity": 1,  // or bytes, seconds, etc.
  "unit": "count|bytes|seconds",
  "timestamp": "2025-04-01T10:00:00Z",
  "metadata": {}
}
```

**Aggregation**:
```sql
-- Daily rollup table
INSERT INTO tenant_usage_daily (tenant_id, date, videos_uploaded, minutes_processed, searches_count, storage_gb)
SELECT
    tenant_id,
    DATE(timestamp),
    COUNT(DISTINCT video_id) FILTER (WHERE type='video.uploaded'),
    SUM(seconds_processed) FILTER (WHERE type='video.processed'),
    COUNT(*) FILTER (WHERE type='search.performed'),
    MAX(storage_bytes) / 1024^3
FROM metering_events
WHERE date = CURRENT_DATE - 1
GROUP BY tenant_id;
```

**Billing**:
- Stripe usage-based billing:
  ```python
  stripe.InvoiceItem.create(
      customer=tenant.stripe_customer_id,
      amount=calculate_usage_charge(tenant_id, month),
      description="Video processing - April 2025"
  )
  ```
- Or manual invoice generation (PDF) sent via email
- Proration for mid-month upgrades/downgrades

### 4. Quota Management

**Per-Tenant Limits Table**:
```sql
CREATE TABLE tenant_quotas (
    tenant_id UUID PRIMARY KEY,
    max_videos_per_month INTEGER,
    max_storage_gb INTEGER,
    max_concurrent_extractors INTEGER,
    max_search_qps INTEGER,
    max_retention_days INTEGER,
    max_api_keys INTEGER,
    custom_models_allowed BOOLEAN
);
```

**Enforcement Points**:
1. Upload endpoint: Check current month count < limit
2. Search endpoint: Token bucket rate limiting
3. Background workers: Respect max_concurrent_extractors (via semaphore in Redis)
4. Retention worker: Auto-delete videos older than `max_retention_days`

---

## Hosting Decision Matrix

| Requirement | Cloud (AWS/GCP/Azure) | On-Premise | Hybrid |
|-------------|----------------------|------------|--------|
| **Time to market** | Fast (weeks) | Slow (months) | Medium |
| **CAPEX vs OPEX** | OPEX (pay-as-you-go) | High CAPEX | Mixed |
| **Compliance** | FedRAMP, SOC2 available | Complete control | Sensitive data on-prem, analytics in cloud |
| **Scalability** | Near-infinite | Limited by hardware | Moderate |
| **Data Sovereignty** | Region selection | Physical control | Sensitive data local |
| **Cost at Scale** | ~$10-50k/mo for 1M videos | $500k+ initial, then lower | $10-30k/mo + CAPEX |
| **Maintenance** | Managed services | Full-time staff | Mixed |
| **Ideal For** | Commercial/SaaS startups | Gov/Law enforcement | Retail logistics with HQ |

### Recommended by Sector:

1. **Law Enforcement** → **On-Premise / Air-Gapped**
   - CJIS compliance requires physical control
   - Data cannot leave jurisdiction
   - Long-tail retention (7+ years)

2. **Commercial / Retail** → **Cloud-Native**
   - Fast scaling for seasonal peaks
   - Global CDN for store locations
   - Pay-per-use pricing

3. **Logistics** → **Hybrid Edge**
   - Warehouses with spotty connectivity
   - Edge processing critical
   - Central analytics in cloud

---

## Detailed Implementation Checklist

### Phase 1 (Months 1-2)
- [ ] Set up Keycloak for OAuth2/OIDC
- [ ] Create `AuthService` with user/role/tenant endpoints
- [ ] Implement JWT middleware for all APIs
- [ ] Refactor all services to use tenant-scoped repositories
- [ ] Create tenant provisioning script (database schema, Milvus collection)
- [ ] Update MinIO client to use tenant-prefixed paths
- [ ] Implement audit logging service
- [ ] Set up Vault for secrets management
- [ ] Enable TLS everywhere (self-signed for Phase 1)
- [ ] Create API Gateway (Kong) with rate limiting
- [ ] Write security audit (internal review)
- [ ] Deploy to staging environment (cloud or local k8s)

### Phase 2 (Months 3-4)
- [ ] Research and select LPR library (OpenALPR, Plate Recognizer)
- [ ] Fine-tune CLIP on surveillance dataset (optional)
- [ ] Implement weapon detection model (YOLO)
- [ ] Add metadata tagging for detections
- [ ] Create sector-specific search profiles in UI
- [ ] Implement exitR fallacy filter for law enforcement (avoid bias)
- [ ] GDPR privacy features: consent tracking, data deletion API
- [ ] Testing with real datasets from each sector
- [ ] Performance benchmarking (FPS, latency) per sector

### Phase 3 (Months 5-6)
- [ ] Design billing schema (Stripe/Paddle integration)
- [ ] Implement usage metering across all services
- [ ] Build admin dashboard for tenant management (quotas, users, billing)
- [ ] Subscription upgrade/downgrade flows
- [ ] Overage detection and soft/hard limits
- [ ] Automated invoicing (PDF generation)
- [ ] Trial → paid conversion flow
- [ ] Sales portal for new customers
- [ ] Customer self-service portal (usage, billing, support)
- [ ] Payment reconciliation and dunning workflow

### Phase 4 (Months 7-8)
- [ ] Deploy Milvus cluster (3+ nodes, sharded)
- [ ] Implement Milvus tenant isolation (collections or partitions)
- [ ] Deploy Kafka cluster for event streaming
- [ ] Refactor poll-based to event-driven (optional, parallel run)
- [ ] Configure HPA for all stateless services
- [ ] Set up GPU node pool with cluster autoscaler
- [ ] Implement MinIO lifecycle policies (hot→warm→cold)
- [ ] Integrate CloudFront CDN
- [ ] Load testing with 100K+ videos
- [ ] Capacity planning doc (cost per million videos)

### Phase 5 (Months 9-12)
- [ ] Temporal search UI (timeline slider)
- [ ] Spatial search implementation (filter by region of frame)
- [ ] Hybrid search ranking algorithm
- [ ] Collaboration features (shared workspaces, annotations)
- [ ] Annotation storage model and UI
- [ ] Alerting rules engine
- [ ] Scheduled report generation (cron + email)
- [ ] Mobile app backend APIs
- [ ] React Native / Flutter app UI
- [ ] Push notification service (Firebase Cloud Messaging / APNS)
- [ ] ML model fine-tuning UI (upload dataset, trigger training)
- [ ] A/B testing framework for model versions
- [ ] Advanced analytics dashboard (Grafana embedded)
- [ ] Export to BI tools (REST API, direct DB access read-only)

### Launch Preparation
- [ ] Penetration test (external firm)
- [ ] SOC2 Type I audit
- [ ] Disaster recovery drill (restore from backup, RTO < 4h)
- [ ] Load test to 1M videos, 1000 concurrent users
- [ ] Documentation for customers (user guides, API docs)
- [ ] Customer support training
- [ ] SLA contracts with legal
- [ ] Marketing website with pricing
- [ ] Beta customer onboarding (5-10 pilots)

---

## Success Metrics (KPIs)

**Technical**:
- API latency: p95 < 200ms (search), p95 < 2s (upload complete)
- System uptime: 99.99% (52min downtime/year)
- Embedding throughput: 1000 frames/sec
- Search QPS: 1000+ at p50 < 100ms
- Store/forward latency: < 1min from upload to searchable

**Business**:
- Tenant count: 10+ by month 6, 50+ by month 12
- Videos processed: 1M by month 12
- MRR: $50k+ by month 12
- Churn: < 2% monthly
- NPS: > 40
- Compliance: SOC2 Type II certified, CJIS validated

---

## Risks & Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Data breach / leak | Low | Critical | Pen tests, encryption, audit logs, MFA, zero trust |
| Performance degrades with scale | High | High | Load testing early, Milvus sharding, CDN |
| Cost overruns (cloud bill shock) | Medium | High | Cost alerts, reserved instances, auto-scaling |
| Compliance failure (CJIS/GDPR) | Medium | Critical | Compliance officer, legal review, third-party audit |
| Vendor lock-in (cloud) | Medium | Medium | Use CNCF projects, avoid proprietary services |
| Model degradation over time | Medium | Medium | Model performance monitoring, retraining pipeline |
| Tenant data leakage | Low | Critical | Thorough testing of schema isolation, RLS, pen tests |
| GPU shortage / pricing | Medium | High | Multi-cloud strategy, spot instances, scheduling |

---

## Conclusion

This roadmap transforms deepSightAI Trinetra from a functional prototype to an enterprise SaaS platform capable of:

- ✅ Multi-tenancy with strict data isolation
- ✅ Enterprise-grade security (encryption, audit, compliance)
- ✅ Sector-specific analytics (law enforcement, commercial, logistics)
- ✅ Subscription management and billing
- ✅ Cloud-native scalability (or on-premise for regulated sectors)
- ✅ Subscriber management with quotas and SLAs
- ✅ Global deployment with edge computing
- ✅ Compliance with CJIS, GDPR, SOC2

**Estimated Timeline**: 12-18 months for full implementation
**Team Required**: 8-12 engineers (backend, frontend, ML, DevOps, security)
**Budget**: $1.5-2M (cloud infrastructure, licenses, compliance)

---

## Appendix: Migration Path from Current System

**Option 1: Greenfield Rewrite (Recommended)**
- Build new `v2` services alongside
- Feature-flag gradually switch traffic
- Export/import data from old to new (one-time migration)
- Decommission old after 3 months

**Option 2: Incremental Refactoring**
- Month 1-2: Add auth + multitenancy on top of existing
- Month 3-4: Refactor one service at a time
- Higher risk, longer timeline, technical debt accumulated

**Recommended**: Greenfield with parallel operation, then cutover.

---

## Next Steps

1. **Secure executive buy-in** for 12-month roadmap and budget
2. **Hire/assign** architect and lead engineer
3. **Complete Phase 1 design review** with security team
4. **Prototype** multi-tenancy in staging within 2 weeks
5. **Begin compliance engagement** (assess CJIS requirements if pursuing law enforcement)
