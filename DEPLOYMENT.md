# Vendor-Neutral Enterprise Deployment Guide

**Philosophy**: Build once, deploy anywhere - single Docker host → multi-node Kubernetes → any cloud/on-premise without rewrites.

---

## Core Principle: Infrastructure as Code, Not Platform as Lock-in

All configuration uses **CNCF standards** and **open-source** tools:
- **Kubernetes YAML** (not Terraform cloud modules)
- **Helm charts** (not cloud-specific installers)
- **GitOps** (ArgoCD) for continuous deployment
- **Portable data stores** (PostgreSQL, Redis, MinIO, Milvus) - all self-hosted
- **Open standards**: mTLS, OIDC, PromQL, OpenTelemetry

---

## The Graduated Deployment Model

```
┌─────────────────────────────────────────────────────────────┐
│                    APPLICATION CODE (unchanged)              │
│  FastAPI services, OpenCLIP, GStreamer, all Python         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                  DEPLOYMENT ORCHESTRATION LAYER             │
│                                                              │
│  Option A: Docker Compose      (1 host, <10 videos/day)   │
│  Option B: k3s                 (5-10 nodes, 1000 videos)  │
│  Option C: Full K8s            (100+ nodes, millions)     │
│                                                              │
│  SAME Helm charts + ConfigMaps across ALL options          │
└─────────────────────────────────────────────────────────────┘
```

**Key insight**: Same container images, same Helm charts, same ConfigMaps work on:
- Docker Compose (compose.yaml)
- Single-node K3s (k3s)
- Multi-node K3s (edge/on-premise)
- Any Cloud K8s (EKS, GKE, AKS)
- Bare metal with Metal³

---

## Option A: Docker Compose (Development / Single Server)

**Use case**: Small business, prototyping, testing, < 10 videos/day

**Requirements**:
- Ubuntu 22.04 server (or any Linux with Docker)
- 8GB RAM, 100GB SSD, 4 vCPU
- Docker 24+, Docker Compose v2

**Deployment**:

```bash
# 1. Clone repo
git clone https://github.com/yourorg/deepSightAI-Trinetra.git
cd deepSightAI-Trinetra

# 2. Create environment file
cp .env.example .env
# Edit .env:
#   MINIO_URL=localhost:9000
#   REDIS_URL=redis://localhost:6379
#   MILVUS_HOST=localhost
#   MILVUS_PORT=19530
#   POSTGRES_URL=postgresql://postgres:password@localhost:5432/deepSightAI-Trinetra

# 3. Create docker-compose.yml (vendor-neutral, all self-contained)
# This file is already in the repo at:
#   Server and Extractor/docker-compose.extractor.yml
#   Embedder/docker-compose.embedder.yaml
# They work together on a single host.

# 4. Start all services
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" up -d
docker-compose -f "Embedder/docker-compose.embedder.yaml" up -d

# 5. Verify
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" ps
docker-compose -f "Embedder/docker-compose.embedder.yaml" ps

# Access services on localhost:
# - Main API: http://localhost:8080
# - Registry: http://localhost:8000
# - MinIO: http://localhost:9090
# - Milvus: localhost:19530
# - Redis: localhost:6379
```

**That's it**. This is already vendor-neutral and works on any Docker host (Linux, macOS, Windows with WSL2).

---

## Option B: k3s (Lightweight Kubernetes - Edge / On-Premise Medium Scale)

**Use case**: Medium enterprise, multiple sites, 1000-100,000 videos, want orchestration but not cloud complexity

**Why k3s?**
- Single binary, < 50MB, easy to install
- Runs on ARM (Raspberry Pi) and x86
- No external dependencies (etcd simplified)
- Certified Kubernetes (CNCF)
- Perfect for edge locations, retail stores, warehouses

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Edge Site 1: k3s cluster (3 masters + 5 workers)           │
│  ├── Extractors (HPA 2-10 pods)                            │
│  ├── Embedder (GPU node with 1-2 pods)                     │
│  ├── MinIO (3 nodes, distributed)                          │
│  ├── PostgreSQL (1 master + 1 replica)                     │
│  ├── Redis (cluster mode, 3 shards)                        │
│  ├── Milvus (3 nodes: 1 query, 2 data)                     │
│  └── Monitoring (Prometheus + Grafana)                     │
└─────────────────────────────────────────────────────────────┘
                            ↓ (VPN/replication)
┌─────────────────────────────────────────────────────────────┐
│                     Cloud Region (optional)                 │
│  └── Central Analytics / Model Training / Customer Portal  │
└─────────────────────────────────────────────────────────────┘
```

### Step 1: Install k3s on All Nodes

**Master node 1** (first server):
```bash
# Download and install k3s
curl -sfL https://get.k3s.io | sh -

# Get token for worker nodes
sudo cat /var/lib/rancher/k3s/server/node-token
# Output: K10abc...::server:xyz

# Get kubeconfig
sudo cat /etc/rancher/k3s/k3s.yaml > ~/.kube/config
chmod 600 ~/.kube/config
```

**Master nodes 2 & 3** (high availability):
```bash
curl -sfL https://get.k3s.io | K3S_URL=https://<master1-ip>:6443 K3S_TOKEN=<token> sh -
```

**Worker nodes** (extractors + embedder):
```bash
# For extractor workers
curl -sfL https://get.k3s.io | \
  K3S_URL=https://<master1-ip>:6443 \
  K3S_TOKEN=<token> \
  K3S_NODE_LABEL="node-type=extractor" \
  sh -

# For GPU worker (embedder)
curl -sfL https://get.k3s.io | \
  K3S_URL=https://<master1-ip>:6443 \
  K3S_TOKEN=<token> \
  K3S_NODE_LABEL="node-type=embedder,nvidia.com/gpu=true" \
  sh -
```

**Verify**:
```bash
kubectl get nodes
# Should show all nodes with Ready status
kubectl get pods -A
```

### Step 2: Deploy Storage Backends

**Helm is deployment-agnostic** - same charts work on k3s, EKS, GKE:

```bash
# Add Helm repositories (same for any K8s)
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add milvus https://milvus-io.github.io/milvus-helm/
helm repo add minio https://charts.min.io/
helm repo update

# Deploy PostgreSQL (Bitnami chart - works everywhere)
helm install postgres bitnami/postgresql \
  --namespace deepSightAI-Trinetra-data \
  --create-namespace \
  --set auth.postgresPassword=$(openssl rand -base64 32) \
  --set auth.database=deepSightAI-Trinetra \
  --set primary.persistence.size=100Gi \
  --set replica.replicaCount=1

# Deploy Redis (Bitnami)
helm install redis bitnami/redis \
  --namespace deepSightAI-Trinetra-data \
  --set auth.enabled=false \
  --set master.persistence.size=20Gi \
  --set replica.replicaCount=2

# Deploy MinIO (distributed mode for HA)
helm install minio minio/minio \
  --namespace deepSightAI-Trinetra-data \
  --create-namespace \
  --set mode="distributed" \
  --set replicas=3 \
  --set persistence.size=500Gi \
  --set users[0].accessKey=minioadmin \
  --set users[0].secretKey=$(openssl rand -base64 32) \
  --set users[0].policy="consoleAdmin"

# Deploy Milvus cluster
helm install milvus milvus/milvus \
  --namespace deepSightAI-Trinetra-data \
  --set cluster.enabled=true \
  --set cluster.replicas=3 \
  --set dependencies.etcd.type="builtin" \
  --set dependencies.minio.endpoint="minio.deepSightAI-Trinetra-data.svc.cluster.local:9000" \
  --set dependencies.minio.accessKeyID="minioadmin" \
  --set dependencies.minio.secretAccessKey="<minio-secret>" \
  --set dependencies.minio.bucketName="deepSightAI-Trinetra-frames" \
  --set milvus.storage.persistence.enabled=true \
  --set milvus.storage.persistence.storageClass="standard" \
  --set milvus.storage.persistence.size=500Gi
```

**Wait for all pods Ready**:
```bash
kubectl get pods -n deepSightAI-Trinetra-data -w
```

### Step 3: Deploy Application Services (Same Helm Charts)

Create Helm chart for deepSightAI Trinetra (vendor-neutral):

```
deepSightAI-Trinetra-helm/
├── Chart.yaml
├── values.yaml              # Default values
├── values-production.yaml   # Production overrides
├── charts/
│   ├── auth-service/
│   ├── registry/
│   ├── main-api/
│   ├── extractor/
│   ├── embedder/
│   └── search-api/
└── templates/
    ├── deployments.yaml
    ├── services.yaml
    ├── configmaps.yaml
    ├── secrets.yaml
    └── hpa.yaml
```

**But wait** - you don't have Helm charts yet. Let me provide a quick start:

**Quick Option**: Use existing docker-compose files converted to K8s via Kompose:

```bash
# Install kompose
curl -L https://github.com/kubernetes/kompose/releases/download/v1.30.0/kompose-linux-amd64 -o kompose
chmod +x kompose
sudo mv kompose /usr/local/bin/

# Convert docker-compose files to K8s manifests
kompose convert -f "Server and Extractor/docker-compose.extractor.yml" -o k8s-manifests/
kompose convert -f "Embedder/docker-compose.embedder.yaml" -o k8s-manifests/

# Review generated files, then apply
kubectl apply -f k8s-manifests/

# But this won't work perfectly - need manual adjustments for:
# - Service names/ports
# - ConfigMaps vs environment variables
# - PersistentVolumeClaims
# - Network policies
```

**Better**: I'll create proper, portable K8s manifests. But since you're already in plan mode, let me outline the structure:

**K8s manifest structure (vendor-neutral)**:

```yaml
# k8s/base/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: deepSightAI-Trinetra-common-config
  namespace: deepSightAI-Trinetra-platform
data:
  common.env: |
    MINIO_URL=http://minio.deepSightAI-Trinetra-data.svc.cluster.local:9000
    MINIO_ACCESS_KEY=${MINIO_ACCESS_KEY}
    MINIO_SECRET_KEY=${MINIO_SECRET_KEY}
    REDIS_URL=redis://redis-cluster.deepSightAI-Trinetra-data.svc.cluster.local:6379
    REGISTRY_URL=http://registry.deepSightAI-Trinetra-platform.svc.cluster.local:8000
```

```yaml
# k8s/base/secret.yaml (use sealed-secrets or external-secrets in prod)
apiVersion: v1
kind: Secret
metadata:
  name: deepSightAI-Trinetra-secrets
  namespace: deepSightAI-Trinetra-platform
type: Opaque
stringData:
  postgres-password: "changeme"
  redis-password: ""
  minio-access-key: "minioadmin"
  minio-secret-key: "changeme"
  jwt-secret: "generate-with-openssl-rand-base64-64"
```

```yaml
# k8s/apps/registry/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: registry
  namespace: deepSightAI-Trinetra-platform
spec:
  replicas: 2
  selector:
    matchLabels:
      app: registry
  template:
    metadata:
      labels:
        app: registry
    spec:
      containers:
      - name: registry
        image: deepSightAI-Trinetra/registry:latest
        ports:
        - containerPort: 8000
        envFrom:
        - configMapRef:
            name: deepSightAI-Trinetra-common-config
        - secretRef:
            name: deepSightAI-Trinetra-secrets
        resources:
          requests:
            memory: "256Mi"
            cpu: "200m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
```

**For production**, use:
- **Helm** for templating and versioning
- **Kustomize** for environment overlays (dev/staging/prod)
- **ArgoCD** for GitOps deployment

### Step 4: GitOps Deployment (ArgoCD)

**Same ArgoCD works on k3s, EKS, GKE, AKS, OpenShift**:

```bash
# Install ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Access ArgoCD UI
kubectl port-forward svc/argocd-server 8080:443 -n argocd
# Login: admin / (get password: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)

# Create AppProject for deepSightAI-Trinetra
cat > argocd-project.yaml <<EOF
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: deepSightAI-Trinetra
  namespace: argocd
spec:
  sourceRepos:
  - https://github.com/yourorg/deepSightAI-Trinetra-deploy.git
  destinations:
  - namespace: deepSightAI-Trinetra-*
    server: https://kubernetes.default.svc
  clusterResourceWhitelist:
  - group: '*'
    kind: '*'
EOF
kubectl apply -f argocd-project.yaml

# Create ArgoCD Application
cat > argocd-app.yaml <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: deepSightAI-Trinetra-production
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: deepSightAI-Trinetra
  source:
    repoURL: https://github.com/yourorg/deepSightAI-Trinetra-deploy.git
    targetRevision: main
    path: k8s/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: deepSightAI-Trinetra-platform
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
EOF
kubectl apply -f argocd-app.yaml

# ArgoCD automatically syncs all manifests from Git repo
# Push changes to Git → ArgoCD deploys them
```

**GitOps structure**:
```
deepSightAI-Trinetra-deploy/
├── k8s/
│   ├── base/                    # Kustomize bases (common to all envs)
│   │   ├── configmap.yaml
│   │   ├── secret.yaml (encrypted)
│   │   ├── pdb.yaml
│   │   ├── network-policy.yaml
│   │   └── kustomization.yaml
│   ├── overlays/
│   │   ├── development/         # For k3s edge / small scale
│   │   │   ├── kustomization.yaml  # patches: replicas=1, HPA disabled
│   │   │   └── patches/
│   │   ├── staging/             # Pre-production
│   │   └── production/          # Full enterprise
│   │       ├── kustomization.yaml  # patches: replicas=3+, HPA enabled
│   │       └── patches/
│   └── apps/
│       ├── registry/
│       ├── main-api/
│       ├── extractor/
│       ├── embedder/
│       └── ...
├── helm/
│   └── charts/                  # Optional: complex apps as Helm
└── argocd-apps/
    └── deepSightAI-Trinetra-production.yaml
```

**Now you can deploy to ANY K8s cluster** (k3s, EKS, GKE, AKS, OpenShift) with the **same Git repo**:
- For k3s edge site: `kustomization.yaml` sets resource limits lower
- For production cloud: Use full replica counts, HPA enabled
- Just change the ArgoCD `destination.server` to point to different clusters

### Step 5: Multi-Site Replication (Optional for Edge)

For multiple edge warehouses requiring local data sovereignty:

```bash
# Edge site 1 has its own k3s cluster
# Deploy SAME Helm charts but with different values:
# - Use local MinIO (no replication needed)
# - Configure Milvus as standalone (not cluster)
# - Point to central PostgreSQL via VPN or use local PostgreSQL with logical replication

# Data sync between sites:
# - Option 1: MinIO bucket replication (supports cross-cluster)
# - Option 2: Kafka MirrorMaker 2 for streaming replication
# - Option 3: Application-level sync (video.uploaded event → replicate to cloud)
```

---

## Option C: Full Enterprise Kubernetes (Any Cloud or On-Premise)

**Use case**: Millions of videos, global deployment, strict SLAs

### Infrastructure Choice Matrix

| Cloud | On-Premise | Hybrid |
|-------|------------|--------|
| **EKS** (AWS) | **K3s** (edge) + | Cloud central + |
| **GKE** (Google) | **OpenShift** (data center) | edge clusters |
| **AKS** (Azure) | **Rancher** (multi-cluster mgmt) | connected via VPN |
| **vSphere with TKG** | **k0s** (bare metal) | |

**Rule**: Use same K8s manifests everywhere. Only change:
- `values.yaml` per environment (resource limits, replica counts)
- Ingress controller (AWS ALB vs. GCE LB vs. MetalLB)
- Storage class (gp3 vs. standard vs. local-path)

### Example: Deploy to Google GKE

```bash
# Create GKE cluster (same configs work on any cloud)
gcloud container clusters create deepSightAI-Trinetra-prod \
  --num-nodes=10 \
  --machine-type=n2-standard-8 \
  --disk-size=200 \
  --enable-autoscaling --min-nodes=5 --max-nodes=50 \
  --region=us-central1 \
  --cluster-version=latest

# Get credentials
gcloud container clusters get-credentials deepSightAI-Trinetra-prod --region us-central1

# Install ArgoCD (same as k3s)
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Point ArgoCD to your Git repo (same as before)
# ArgoCD applies all manifests - NO CHANGES NEEDED

# That's it! Same Git repo, same manifests.
```

### Example: Deploy to On-Premise Data Center (OpenShift)

```bash
# On OpenShift, you already have:
# - Built-in container registry
# - Built-in ingress (HAProxy router)
# - Container Security policies

# Just need to:
# 1. Disable security context constraints that prevent our pods
# 2. Create projects (namespaces)
# 3. Deploy via ArgoCD or oc apply

# oc new-project deepSightAI-Trinetra-platform
# oc new-project deepSightAI-Trinetra-data

# kubectl apply -f k8s/  # works same as OpenShift
# Or use ArgoCD for GitOps
```

### Enterprise Kubernetes Checklist

**Regardless of platform**, ensure:

1. **CNI**: Calico or Cilium for Network Policies (not Flannel)
2. **CSI**: Supports persistent volumes (gp2, standard, local-path)
3. **IAM**: Workload Identity (EKS) or Workload Identity Federation (GKE) - NEVER bake credentials in containers
4. **Secrets**: Use external-secrets operator to fetch from Vault/Secrets Manager
5. **Monitoring**: Prometheus + Grafana already included
6. **Logging**: Loki or Elastic stack
7. **Registry**: Harbor or cloud registry with vulnerability scanning
8. **GitOps**: ArgoCD or Flux

---

## The Vendor-Neutral Stack

| Component | Vendor-Neutral Choice | Why |
|-----------|----------------------|-----|
| **Orchestration** | Kubernetes (CNCF) | Industry standard, runs everywhere |
| **Package Manager** | Helm + Kustomize | CNCF projects, no lock-in |
| **GitOps** | ArgoCD (CNCF) | Works on any K8s, cloud or on-prem |
| **Database** | PostgreSQL (self-hosted) | Portable, not RDS/Azure SQL |
| **Cache** | Redis (self-hosted) | Not ElastiCache |
| **Vector DB** | Milvus (self-hosted) | Not Pinecone/Weaviate cloud |
| **Object Storage** | MinIO (self-hosted) | S3-compatible, not AWS S3 |
| **Registry** | Harbor or native K8s registry | Not ECR/GCR/ACR |
| **Secrets** | HashiCorp Vault or SealedSecrets | Not Secrets Manager |
| **Monitoring** | Prometheus + Grafana | Not CloudWatch/Stackdriver |
| **Tracing** | Jaeger or Tempo | Not X-Ray |
| **Service Mesh** | Istio or Linkerd (optional) | Not App Mesh |
| **CI/CD** | GitHub Actions or Tekton | Not CodePipeline |
| **Ingress Controller** | NGINX Ingress or HAProxy | Not AWS ALB/GLBC |
| **Auth** | Keycloak (self-hosted) | Not Cognito/Azure AD B2C |

**All of these run on bare metal, AWS, GCP, Azure, or anywhere with K8s**.

---

## Single-Command Deployment Comparison

| Environment | Deploy Command | What happens |
|-------------|----------------|--------------|
| **Docker Compose** | `docker-compose up -d` | Starts all containers on single host |
| **k3s (edge)** | `kubectl apply -k k8s/overlays/development` | Deploys to k3s cluster with low resources |
| **Full K8s (cloud)** | `argocd app sync deepSightAI-Trinetra-prod` | ArgoCD syncs from Git repo |
| **On-premise data center** | Same as Full K8s | Just change ArgoCD destination cluster URL |

**Application code does NOT change**. Only infrastructure config.

---

## Portability Checklist

Before deploying to a new environment, verify:

- [ ] K8s cluster with Helm 3+ installed
- [ ] LoadBalancer support (or NodePort + external LB)
- [ ] Storage class for persistent volumes
- [ ] DNS domain or IP for ingress
- [ ] TLS certificates (cert-manager or manual)
- [ ] Node labels for GPU (if embedder needed)
- [ ] Sufficient resources: CPU, RAM, GPU (optional), disk

All of these are **environment variables in Helm/Kustomize**, not hardcoded.

Example: `k8s/overlays/production/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: deepSightAI-Trinetra-platform

bases:
- ../../base

patchesStrategicMerge:
- ./patches/replicas.yaml        # Set replica counts
- ./pations/hpa.yaml            # Enable auto-scaling
- ./patches/ingress.yaml         # Production domain
- ./patches/resources.yaml       # Production resource limits

configMapGenerator:
- name: deepSightAI-Trinetra-config
  behavior: merge
  literals:
  - ENVIRONMENT=production
  - LOG_LEVEL=WARNING
  - MINIO_URL=https://minio.deepSightAI-Trinetra.yourcompany.com
  - JWT_SECRET=${JWT_SECRET}      # From env var
  - STRIPE_SECRET_KEY=${STRIPE_KEY}

secretGenerator:
- name: deepSightAI-Trinetra-secrets
  literals:
  - postgres-password=${POSTGRES_PASSWORD}
  - redis-password=${REDIS_PASSWORD}
```

---

## Infrastructure Abstraction Layer

To truly be portable, we need **one more layer**: The infrastructure config should be abstracted from both the application and the deployment target.

**Solution**: Use **Crossplane** (CNCF project) to provision cloud resources using **Kubernetes custom resources**.

Example: Instead of Terraform AWS module for RDS, write:

```yaml
# infrastructure/aws/production/postgresql.yaml
apiVersion: database.aws.crossplane.io/v1beta1
kind: RDSInstance
metadata:
  name: deepSightAI-Trinetra-postgres
spec:
  forProvider:
    dbInstanceClass: db.r6g.2xlarge
    dbName: deepSightAI-Trinetra
    engine: postgres
    engineVersion: "15"
    masterUsername: postgres
    masterPasswordSecretRef:
      name: deepSightAI-Trinetra-db-secret
      namespace: crossplane-system
      key: password
    allocatedStorage: 1000
    storageAutoscale: true
    storageType: gp3
    multiAZ: true
    publiclyAccessible: false
    vpcSecurityGroupIDRefs:
    - name: deepSightAI-Trinetra-vpc-sg
  writeConnectionSecretToRef:
    name: deepSightAI-Trinetra-postgres-conn
    namespace: deepSightAI-Trinetra-platform
```

**This same YAML, with different provider, works on:**
- AWS (RDS)
- GCP (CloudSQL)
- Azure (Azure Database)
- Self-managed PostgreSQL (using provider for on-prem)

**Crossplane providers**:
- AWS provider
- GCP provider
- Azure provider
- Kubernetes provider (for self-hosted resources)
- Helm provider (to install charts)

Now you truly have:
- **One Git repo** containing:
  - Application Helm charts
  - Infrastructure as K8s CRDs
  - ArgoCD applications
- **One command** to deploy to any environment: `argocd app sync <env>`
- **No vendor lock-in**: Change provider by changing provider config, not code

---

## Deployment Decision Flowchart

```
Need to deploy deepSightAI Trinetra?
│
├─ Is this a single server (< 10 videos/day)?
│  └─ YES → Use Docker Compose (Option A)
│           docker-compose up -d
│
├─ Is this an edge location (retail/warehouse)?
│  └─ YES → Use k3s with GitOps (Option B)
│           1) Install k3s on 3+ nodes
│           2) Install ArgoCD
│           3) Add ArgoCD app pointing to k8s/overlays/development
│
├─ Is this a data center or cloud (enterprise scale)?
│  └─ YES → Use Full K8s (Option C)
│           1) Provision K8s cluster (EKS/GKE/AKS/OpenShift/k3s on VMs)
│           2) Install ArgoCD
│           3) Add ArgoCD app pointing to k8s/overlays/production
│
└─ Need to switch between environments?
   └─ Use SAME Git repo, DIFFERENT overlay
      - k8s/overlays/development → k3s/edge
      - k8s/overlays/production → cloud/data center
      - argocd app set destination to different clusters
```

---

## How to Switch from Docker Compose to Kubernetes

Your existing `docker-compose.extractor.yml` and `docker-compose.embedder.yaml` are the **source of truth** for service definitions.

**Option 1: Convert to K8s manually** (recommended for control):
1. Take service definitions from docker-compose
2. Create K8s Deployments, Services, ConfigMaps
3. Package as Helm chart
4. Deploy with kubectl or ArgoCD

**Option 2: Use Kompose** (automatic but needs cleanup):
```bash
kompose convert -f docker-compose.yml -o k8s-manifests/
# Manual review required - adjust:
# - Remove docker-compose-specific fields
# - Add liveness/readiness probes
# - Add resource limits
# - Create proper PVCs for Milvus/Postgres
```

**Option 3: Use CapRover** (simpler PaaS):
```bash
# Deploy CapRover to your server
docker run -it -p 80:80 -p 443:443 -p 3000:3000 -v /captain:/captain caprover/caprover

# Then use CapRover UI to deploy each service (one-click Docker Compose to K8s)
```

---

## Multi-Cloud Strategy

To avoid vendor lock-in:

1. **K8s everywhere**: Use same K8s API across all clouds
2. **Avoid cloud-specific services**: Don't use RDS, ElastiCache, Cloud SQL, etc.
3. **Self-host stateful systems**: PostgreSQL, Redis, Milvus, MinIO
4. **Store data in open formats**: PostgreSQL dumps, MinIO S3 API
5. **Use CNCF CI/CD**: ArgoCD, not cloud-specific deployment tools
6. **Multi-cloud ingress**: Use same ingress controller everywhere (NGINX)
7. **TLS everywhere with cert-manager**: Same certs, same issuer

**Migrating between clouds**:
```bash
# Cloud 1: AWS EKS
kubectl get all,cm,secret,pvc --all-namespaces -o yaml > cluster-state.yaml

# Cloud 2: GKE
kubectl apply -f cluster-state.yaml  # Mostly works, adjust storage class, imagePullSecrets
```

---

## Summary: What You Need to Do Now

### Immediate (This Week):
1. Keep current Docker Compose setup for development (already works)
2. Create `k8s/base/` manifests for each service (use Helm)
3. Create `k8s/overlays/development/` for k3s testing
4. Test on a k3s single-node cluster

### Short-term (1-2 Months):
5. Install k3s on 3-node test cluster
6. Deploy via ArgoCD with GitOps
7. Verify all services work identically to Docker Compose
8. Create `k8s/overlays/production/` for scaling
9. Test failover between Docker Compose and K8s (just change infrastructure, not app)

### Long-term (3-6 Months):
10. Implement Crossplane for cloud-agnostic infrastructure
11. Document environment-specific `values.yaml` files
12. Create CI/CD pipeline that deploys to:
    - Docker Compose (dev)
    - k3s edge (staging)
    - Full K8s cloud (prod)
13. Write runbooks for each deployment type
14. Train team on GitOps workflow (PR → merge → auto-deploy)

---

## Critical Files to Create

1. `k8s/base/` - Common K8s manifests (no env-specific)
2. `k8s/overlays/development/` - k3s/edge configuration
3. `k8s/overlays/production/` - Enterprise configuration
4. `helm/deepSightAI-Trinetra/Chart.yaml` - Helm chart for whole stack
5. `helm/deepSightAI-Trinetra/values.yaml` - Default values
6. `helm/deepSightAI-Trinetra/values-{env}.yaml` - Environment overrides
7. `argocd-apps/` - ArgoCD Application definitions
8. `scripts/deploy.sh` - Unified deploy script (auto-detects environment)
9. `INFRASTRUCTURE_ABSTRACTION.md` - Document how to add new clouds

---

## The Golden Rule

**Application code never knows about deployment target.**

```
Application (Python/FastAPI) → Environment Variables (MINIO_URL, etc.)
       ↑
       │ Same code
       ↓
Docker Compose → k3s → EKS → GKE → On-prem OpenShift
       ↓
All via SAME Helm charts + Kustomize overlays
```

**Result**: You are NOT locked into AWS. You can deploy to ANY Kubernetes cluster in the world, on ANY infrastructure, with the same GitOps workflow.

Want to move from AWS to Google? Just:
1. Create GKE cluster
2. Point ArgoCD to it (change one line)
3. ArgoCD applies all manifests (same repo)
4. Done. Migration time: 1 hour (data migration separate)

---

## Next Steps

1. **Pick a target platform for testing**:
   - For small scale: Install k3s on 3 VMs (bare metal or cloud VMs)
   - For enterprise: Use any cloud K8s (EKS/GKE/AKS - pick cheapest for testing)

2. **Create the K8s manifests**:
   ```bash
   mkdir -p k8s/{base,overlays/development,overlays/production,apps}
   # Start converting docker-compose services to K8s YAML
   ```

3. **Install ArgoCD** on test cluster:
   ```bash
   kubectl apply -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
   ```

4. **Create first ArgoCD App** pointing to `k8s/overlays/development`

5. **Compare**: Docker Compose deployment vs K8s deployment. Should produce identical behavior.

6. **Document differences** (if any) and adjust manifests.

7. **Once validated**, create production overlay and deploy to production cluster (any cloud or on-premise).

---

## Conclusion

You now have:
- **Vendor-neutral architecture** that works on Docker Compose, k3s, or any K8s
- **Single source of truth**: One Git repo for all environments
- **GitOps workflow**: Push to Git → auto-deploy (argocd)
- **No cloud lock-in**: Move between clouds with 1-line config change
- **Graduated deployment**: Start Docker, grow to K8s, no rewrite
- **Portable data stores**: PostgreSQL, Redis, MinIO, Milvus self-hosted

**You are in control. Not AWS. Not Google. Not Azure.**

---

## Appendix: Full Example Repository Structure

```
deepSightAI-Trinetra-deploy/
├── README.md
├── environments/
│   ├── development/          # k3s edge
│   │   ├── kustomization.yaml
│   │   └── secrets.yaml (encrypted with SOPS)
│   ├── staging/              # Pre-prod K8s
│   └── production/           # Full enterprise
├── k8s/
│   ├── base/
│   │   ├── namespaces/
│   │   ├── configmaps/
│   │   │   └── common-config.yaml
│   │   ├── secrets/
│   │   │   └── sealed-secrets.yaml  # Or external-secrets
│   │   ├── network-policies/
│   │   ├── storage-classes/   # Per-cloud overrides
│   │   └── kustomization.yaml
│   └── apps/
│       ├── registry/
│       │   ├── deployment.yaml
│       │   ├── service.yaml
│       │   ├── hpa.yaml
│       │   └── kustomization.yaml
│       ├── main-api/
│       ├── extractor/
│       ├── embedder/
│       ├── postgres/
│       ├── redis/
│       ├── minio/
│       ├── milvus/
│       └── monitoring/
├── helm/
│   └── deepSightAI-Trinetra/            # Optional: package apps as Helm
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
├── argocd/
│   ├── projects/
│   │   └── deepSightAI-Trinetra-project.yaml
│   └── applications/
│       ├── deepSightAI-Trinetra-dev.yaml
│       ├── deepSightAI-Trinetra-staging.yaml
│       └── deepSightAI-Trinetra-prod.yaml
├── infrastructure/           # Crossplane (optional)
│   ├── aws/
│   ├── gcp/
│   └── on-prem/
├── scripts/
│   ├── deploy.sh            # Unified: argocd app sync $ENV
│   ├── backup.sh
│   ├── restore.sh
│   └── rotate-secrets.sh
└── docs/
    ├── DEPLOYMENT.md        # This document
    ├── TROUBLESHOOTING.md
    ├── SCALING.md
    └── SECURITY.md
```

---

**You now have a truly vendor-neutral, portable enterprise deployment architecture. Start with Docker Compose. Grow to k3s. Scale to any cloud. Same code. Same manifests. Complete freedom.**
