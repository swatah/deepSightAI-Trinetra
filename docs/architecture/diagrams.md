# Architecture Diagrams

This page provides visual representations of deepSightAI Trinetra architecture for quick understanding.

---

## High-Level System Overview

```mermaid
graph TB
    subgraph "External"
        UI[Streamlit UI]
        Admin[Admin CLI]
    end
    
    subgraph "deepSightAI Trinetra API Layer"
        API[Main API<br/>FastAPI 8080]
        Auth[AuthService<br/>JWT Validation]
    end
    
    subgraph "Processing Layer"
        Extract[Extractor<br/>Scalable Workers]
        Embed[Embedder<br/>ONNX/PyTorch]
    end
    
    subgraph "Storage Layer"
        MinIO[(MinIO<br/>S3 Compatible)]
        Milvus[(Milvus<br/>Vector DB)]
        PG[(PostgreSQL<br/>Metadata)]
        Redis[(Redis<br/>Registry)]
    end
    
    subgraph "Observability"
        Prometheus[Prometheus]
        Loki[Loki/ELK]
        Grafana[Grafana]
    end
    
    UI --> API
    Admin --> API
    API --> Auth
    API --> Extract
    API --> MinIO
    Extract --> MinIO
    MinIO --> Embed
    Embed --> Milvus
    API --> PG
    API --> Redis
    
    Extract --> Prometheus
    Embed --> Prometheus
    API --> Loki
    Extract --> Loki
    Embed --> Loki
    Prometheus --> Grafana
    Loki --> Grafana
    
    style API fill:#2196f3
    style MinIO fill:#4caf50
    style Milvus fill:#ff9800
    style PG fill:#9c27b0
    style Redis fill:#e91e63
```

---

## Data Flow: Video Upload & Processing

```mermaid
sequenceDiagram
    participant User
    participant API
    participant MinIO
    participant PG as PostgreSQL
    participant Reg as Registry
    participant Extract
    participant Embed
    participant Milvus
    
    User->>API: POST /process_video (file)
    API->>MinIO: Store video in bucket
    API->>PG: Insert video metadata
    API->>MinIO: List objects (check existing)
    API->>MinIO: Create segment directories
    API->>Reg: Get available extractor
    Reg-->>API: Return extractor URL
    API->>Extract: POST /extract (segment)
    Extract->>MinIO: Download segment
    Extract->>MinIO: Upload frames (1 FPS)
    Extract->>MinIO: Mark segment complete
    Extract-->>API: Status update
    API->>PG: Update segment status
    
    Note over Embed: Background polling...
    Embed->>MinIO: Scan for new frames
    Embed->>MinIO: Download batch (32 frames)
    Embed->>Embed: Generate embeddings
    Embed->>Milvus: Insert vectors
    Embed->>MinIO: Delete frames (cleanup)
    Embed->>PG: Update video status=ready
```

---

## Data Flow: Search Query

```mermaid
sequenceDiagram
    participant User
    participant API
    participant Auth
    participant Milvus
    participant MinIO
    
    User->>API: POST /search (query)
    API->>Auth: Validate JWT (tenant_id)
    Auth-->>API: Valid (tenant=acme)
    API->>API: Encode query to vector (CLIP)
    API->>Milvus: Search with partition filter (tenant=acme)
    Milvus-->>API: Return top_k vectors + distances
    API->>MinIO: Fetch thumbnails for results
    MinIO-->>API: Return thumbnail URLs
    API-->>User: Return JSON results
```

---

## Kubernetes Deployment

```mermaid
graph TB
    subgraph "K8s Cluster: deepSightAI-Trinetra"
        subgraph "Namespace: deepSightAI-Trinetra"
            API[API Deployment<br/>Replicas: 3]
            Extract[Extractor<br/>Replicas: 10-50 (HPA)]
            Embed[Embedder<br/>Replicas: 1-5 (GPU)]
            PG[PostgreSQL<br/>StatefulSet]
            MinIO[MinIO<br/>StatefulSet - 4 nodes]
            Milvus[Milvus<br/>Cluster]
            Redis[Redis<br/>Sentinel]
            Kafka[Kafka<br/>Strimzi]
        end
    end
    
    subgraph "Monitoring"
        Prom[Prometheus]
        Graf[Grafana]
    end
    
    subgraph "External"
        LB[Load Balancer<br/>ELB/GCLB/ALB]
    end
    
    LB --> API
    API --> MinIO
    API --> PG
    API --> Redis
    API --> Kafka
    Extract --> MinIO
    Extract --> Redis
    Embed --> MinIO
    Embed --> Milvus
    Prom --> API
    Prom --> Extract
    Prom --> Embed
    Prom --> PG
    Prom --> Milvus
    Prom --> MinIO
    Prom --> Kafka
    Graf --> Prom
    
    style API fill:#2196f3
    style MinIO fill:#4caf50
    style Milvus fill:#ff9800
```

---

## Security Architecture

```mermaid
graph TB
    subgraph "Tenant Isolation"
        T1[Tenant A]
        T2[Tenant B]
    end
    
    subgraph "API Layer"
        Middleware[Tenant Middleware]
        Auth[JWT Validation]
    end
    
    subgraph "Storage Isolation"
        DB[(PostgreSQL<br/>RLS/Schemas)]
        S3[MinIO Bucket<br/>Prefix-per-tenant]
        MV[Milvus<br/>Partition key]
    end
    
    T1 --> Middleware
    T2 --> Middleware
    Middleware --> Auth
    Auth --> DB
    Auth --> S3
    Auth --> MV
    
    DB -->|Filter tenant_id| DB
    S3 -->|Path: /tenant-a/| S3
    MV -->|Partition: tenant-a| MV
    
    style DB fill:#9c27b0
    style S3 fill:#4caf50
    style MV fill:#ff9800
```

---

## Milvus Index Structure

```mermaid
graph LR
    Q[Query Vector<br/>512-dim CLIP]
    
    subgraph "Milvus HNSW Graph"
        subgraph "Layer 0 (Base)"
            N1[Nearest neighbor]
            N2[Nearest neighbor]
            N3[Nearest neighbor]
            N4[Nearest neighbor]
        end
        subgraph "Layer 1"
            N5[Upper layer node]
            N6[Upper layer node]
        end
        subgraph "Layer 2"
            N7[Top layer entry]
        end
    end
    
    Q -->|Greedy search| N1
    N1 -->|Navigate| N5
    N5 -->|Navigate| N7
    N7 -->|Return K nearest| Results[Results]
    
    N1 --> N2
    N2 --> N3
    N3 --> N4
    N5 --> N6
    N6 --> N7
    
    style Results fill:#4caf50
```

HNSW (Hierarchical Navigable Small World) enables sub-linear search: O(log n) complexity vs O(n) brute force.

---

## Docker Compose Layout (Local Dev)

```mermaid
graph TB
    subgraph "Docker Network: deepSightAI-Trinetra_default"
        API[api:8080]
        Extract[extractor:8001]
        Embed[embedder:8002]
        Reg[registry:8000]
        MinIO[minio:9000]
        Milvus[milvus:19530]
        PG[postgres:5432]
        Redis[redis:6379]
    end
    
    subgraph "Volumes"
        V1[postgres_data]
        V2[minio_data]
        V3[redis_data]
        V4[milvus_data]
    end
    
    PG --> V1
    MinIO --> V2
    Redis --> V3
    Milvus --> V4
    
    API --> PG
    API --> Redis
    API --> MinIO
    Extract --> MinIO
    Extract --> Redis
    Embed --> MinIO
    Embed --> Milvus
    
    style API fill:#2196f3
    style MinIO fill:#4caf50
    style Milvus fill:#ff9800
```

---

## CI/CD Pipeline (GitOps)

```mermaid
graph LR
    Dev[Developer Push<br/>to main]
    
    subgraph "GitHub Actions"
        CI[CI / Tests]
        Build[Build & Push Images]
        Deploy[ArgoCD Sync]
    end
    
    subgraph "Registry"
        GHCR[GHCR / Docker Hub]
    end
    
    subgraph "Cluster"
        ArgoCD[ArgoCD<br/>GitOps Sync]
        K8s[K8s Resources]
    end
    
    Dev --> CI
    CI --> Build
    Build --> GHCR
    GHCR --> Deploy
    Deploy --> ArgoCD
    ArgoCD --> K8s
    
    style CI fill:#ff9800
    style ArgoCD fill:#4caf50
```

---

## Message Flow: Audit Events

```mermaid
graph LR
    subgraph "Application"
        API[API]
        Middleware[Audit Middleware]
    end
    
    subgraph "Streaming"
        Kafka[Kafka<br/>audit-logs topic]
        Logstash[Logstash]
    end
    
    subgraph "Storage"
        PG[(PostgreSQL<br/>WORM table)]
        SIEM[Splunk/Elastic]
        S3[S3 Glacier<br/>Long-term]
    end
    
    API --> Middleware
    Middleware -->|Async| Kafka
    Kafka --> Logstash
    Kafka --> PG
    Logstash --> SIEM
    PG -->|Daily| S3
    
    style PG fill:#9c27b0
    style S3 fill:#2196f3
    style SIEM fill:#ff5722
```

---

## Filmstrip: What Did I Build For You?

```mermaid
mindmap
  root((deepSightAI Trinetra))
    1[Phase 1: Foundation]
      1.1[K8s Manifests]
      1.2[Auth Service]
      1.3[Multi-tenancy]
      1.4[Encryption]
      1.5[Audit Logging]
    2[Phase 2: Analytics]
      2.1[Plugin System]
      2.2[Sector Models]
      2.3[Performance]
    3[Phase 3: Operations]
      3.1[Docs]
      3.2[Monitoring]
      3.3[Backup/DR]
    4[Infrastructure]
      Docker
      Kubernetes
      Helm
      GitOps
    5[Security]
      JWT
      mTLS
      RLS
      WORM
    6[Observability]
      Prometheus
      Grafana
      Loki
```

---

## References

- [Mermaid Live Editor](https://mermaid.live) - Edit and preview diagrams
- [PlantUML Alternative](https://plantuml.com/) - More complex diagramming (if needed)
- Generate diagrams automatically: `scripts/generate_diagrams.sh` (uses Graphviz)
