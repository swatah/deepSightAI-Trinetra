# Installation: Kubernetes (k3s, EKS, GKE, AKS)

**Best for**: Production deployments with 100+ videos/day, need for scalability and high availability

This guide covers deploying deepSightAI Trinetra on Kubernetes using vendor-neutral manifests. Works on:
- **k3s** (lightweight, edge/on-premise)
- **k3d** (local development cluster)
- **EKS** (AWS), **GKE** (Google Cloud), **AKS** (Azure)
- Any CNCF-conformant Kubernetes distribution

---

## Architecture (Kubernetes)

```
┌─────────────────────────────────────────────────────────────┐
│                     Ingress (TLS termination)               │
│                  (Istio/Nginx/Traefik)                     │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTP/HTTPS
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                 API Deployment (ReplicaSet)                 │
│              HPA: 2-10 pods based on CPU                    │
└─────────────────────────┬───────────────────────────────────┘
                          │ Dispatches to
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Extractor Deployment (ReplicaSet)              │
│              HPA: 1-50 pods based on queue depth           │
└─────────────────────────┬───────────────────────────────────┘
                          │ Frames → S3-like storage
                          ▼
┌─────────────────────────────────────────────────────────────┐
│            MinIO StatefulSet (distributed mode)            │
│              3+ nodes with replication                     │
└─────────────────────────┬───────────────────────────────────┘
                          │ Polls for new frames
                          ▼
┌─────────────────────────────────────────────────────────────┐
│            Embedder Deployment (ReplicaSet)                │
│              HPA: 1-10 pods based on GPU availability      │
└─────────────────────────┬───────────────────────────────────┘
                          │ Vectors →
                          ▼
┌─────────────────────────────────────────────────────────────┐
│               Milvus Cluster (3+ nodes)                    │
│         Query/Index/Proxy nodes with RAFT consensus        │
└─────────────────────────────────────────────────────────────┘
```

Also includes:
- **PostgreSQL** (StatefulSet with streaming replication)
- **Redis** (Cluster mode or Sentinel)
- **Kafka** (Strimzi operator, 3 brokers with replication)
- **Prometheus + Grafana** for monitoring
- **ArgoCD** for GitOps deployment

---

## Prerequisites

1. **Kubernetes cluster** (v1.24+)
   - k3s: `curl -sfL https://get.k3s.io | sh -`
   - k3d (local): `k3d cluster create deepSightAI-Trinetra`
   - EKS/GKE/AKS: Use cloud provider console/CLI

2. **kubectl** configured with cluster context

3. **Helm 3+** (for some components)

4. **ArgoCD** installed (for GitOps - optional but recommended)

5. **At least 3 worker nodes** for production HA (1 node OK for dev)

6. **Resource requirements per node**:
   - 8 vCPU minimum (16+ recommended)
   - 32 GB RAM minimum (64+ for GPU embedder)
   - 500 GB SSD (NVMe preferred)
   - Linux kernel 5.4+

7. **LoadBalancer** support (or NodePort + Ingress):
   - Cloud: Automatic (ELB, GCLB, ALB)
   - k3s: Use ` Metallb` (Metal LoadBalancer)
   - Bare metal: Use NodePort + external LB (HAProxy, Nginx)

---

## Deployment Options

### Option A: GitOps with ArgoCD (Recommended)

ArgoCD continuously syncs your Git repo to the cluster. Changes to manifests automatically deployed.

**Setup** (one time):

```bash
# Install ArgoCD (if not already)
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for ArgoCD to be ready
kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=300s

# Access ArgoCD UI
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Login with admin / (get password from secret)
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

Then create ArgoCD Application pointing to your Git repo:

```bash
kubectl apply -f argocd-apps/deepSightAI-Trinetra-main.yaml
```

ArgoCD will sync and deploy all components. Status visible in UI or:

```bash
argocd app get deepSightAI-Trinetra
```

**To update**: Commit changes to Git → ArgoCD auto-deploys (or manual sync).

---

### Option B: Direct kubectl apply

For quick testing or if you don't want GitOps:

```bash
# Create namespace
kubectl create namespace deepSightAI-Trinetra

# Apply all base manifests
kubectl apply -k k8s/overlays/development -n deepSightAI-Trinetra

# Or production:
kubectl apply -k k8s/overlays/production -n deepSightAI-Trinetra
```

Use Kustomize overlays to customize per environment (different resource limits, replica counts, image tags).

---

## Kustomize Structure

```
k8s/
├── base/
│   ├── namespace.yaml
│   ├── postgres/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── pvc.yaml
│   │   └── configmap.yaml
│   ├── redis/
│   ├── minio/
│   ├── milvus/
│   ├── kafka/
│   ├── api/
│   ├── extractor/
│   ├── embedder/
│   ├── ingress/
│   └── network-policies/
├── overlays/
│   ├── development/
│   │   ├── kustomization.yaml
│   │   └── patches/
│   │       ├── api-replicas.yaml  (replicas: 1)
│   │       └── resources-dev.yaml (lower limits)
│   ├── staging/
│   └── production/
│       ├── kustomization.yaml
│       └── patches/
│           ├── api-replicas.yaml  (replicas: 3)
│           ├── hpa.yaml
│           └── resources-prod.yaml
└── secrets/  # External Secrets references (not in Git!)
    ├── cluster-secrets.yaml
    └── database-password.yaml
```

---

## Detailed Setup Steps

### 1. Prepare Cluster

Ensure nodes are labeled appropriately:

```bash
# Label GPU nodes (if using GPU embedder)
kubectl label nodes <gpu-node-name> accelerator=nvidia-tesla-v100

# Label stateful nodes (for DBs)
kubectl label nodes <node-name> node-role.kubernetes.io/database=true
```

Create namespace:

```bash
kubectl apply -f k8s/base/namespace.yaml
```

---

### 2. Configure Secrets (DO NOT COMMIT TO GIT!)

Use **HashiCorp Vault + External Secrets Operator** or **Sealed Secrets**:

```bash
# Option A: Sealed Secrets (simpler for small deployments)
# Encrypt secret, commit encrypted version
kubeseal --controller-name sealed-secrets --format=yaml < secret.yaml > sealed-secret.yaml

# Option B: External Secrets (for Vault integration)
# Create ExternalSecret manifests referencing Vault paths
kubectl apply -f kubernetes/external-secrets/
```

Minimum secrets needed:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: deepSightAI-Trinetra-secrets
  namespace: deepSightAI-Trinetra
type: Opaque
stringData:
  postgres-password: "CHANGE-ME-TO-STRONG-PASSWORD"
  redis-password: "ANOTHER-STRONG-PASSWORD"
  minio-root-user: "minioadmin"
  minio-root-password: "MINIO-ADMIN-PASSWORD-CHANGE-ME"
  jwt-secret-key: "YOUR-RSA-PRIVATE-KEY-BASE64"
  kafka-broker-password: "KAFKA-PASSWORD"
  aws-access-key-id: "S3-COMPATIBLE-ACCESS-KEY"
  aws-secret-access-key: "S3-COMPATIBLE-SECRET-KEY"
```

---

### 3. Apply Manifests

```bash
# Check all manifests are valid
kubeval k8s/base/**/*.yaml
kube-score score k8s/base/

# Apply with Kustomize
kubectl apply -k k8s/overlays/development -n deepSightAI-Trinetra

# Wait for all pods to be ready
kubectl wait --for=condition=ready pod --all -n deepSightAI-Trinetra --timeout=600s

# Check status
kubectl get all -n deepSightAI-Trinetra
```

Expected output:

```
NAME                              READY   STATUS    RESTARTS   AGE
pod/deepSightAI-Trinetra-api-xxxx            1/1     Running   0          2m
pod/deepSightAI-Trinetra-extractor-xxxx      1/1     Running   0          2m
pod/deepSightAI-Trinetra-embedder-xxxx       1/1     Running   0          2m
pod/deepSightAI-Trinetra-postgres-0          1/1     Running   0          3m
pod/deepSightAI-Trinetra-redis-xxxx          1/1     Running   0          3m
pod/deepSightAI-Trinetra-minio-0             1/1     Running   0          3m
pod/deepSightAI-Trinetra-milvus-xxxx         1/1     Running   0          3m
pod/deepSightAI-Trinetra-kafka-0             1/1     Running   0          3m
```

---

### 4. Configure Ingress

If you have an Ingress Controller (nginx, traefik, istio):

```bash
kubectl apply -f k8s/ingress/deepSightAI-Trinetra-ingress.yaml -n deepSightAI-Trinetra
```

For k3s with **Traefik** (built-in):

```bash
# Traefik is already running; just create IngressRoute
kubectl apply -f k8s/ingress/traefik-ingressroute.yaml -n deepSightAI-Trinetra
```

Then access:
- API: http://api.deepSightAI-Trinetra.local (or your domain)
- UI: http://ui.deepSightAI-Trinetra.local

For local testing, add to `/etc/hosts`:

```
127.0.0.1 api.deepSightAI-Trinetra.local
127.0.0.1 ui.deepSightAI-Trinetra.local
```

Or use port-forward:

```bash
kubectl port-forward svc/deepSightAI-Trinetra-api 8080:8080 -n deepSightAI-Trinetra
kubectl port-forward svc/streamlit-ui 8501:8501 -n deepSightAI-Trinetra
```

---

### 5. Verify Deployment

```bash
# Test API health
curl http://localhost:8080/health

# Should return:
# {"status":"healthy","version":"1.0.0","timestamp":"..."}

# Check logs of each component
kubectl logs -f deployment/deepSightAI-Trinetra-api -n deepSightAI-Trinetra
kubectl logs -f deployment/deepSightAI-Trinetra-extractor -n deepSightAI-Trinetra
kubectl logs -f deployment/deepSightAI-Trinetra-embedder -n deepSightAI-Trinetra

# Check metrics (if Prometheus installed)
kubectl port-forward svc/prometheus-operated 9090:9090 -n monitoring
# Browse to http://localhost:9090/targets
```

---

## Scaling

### Horizontal Pod Autoscaling

HPA configured for API and Extractor:

```bash
# View metrics
kubectl get hpa -n deepSightAI-Trinetra

# Manual scaling
kubectl scale deployment deepSightAI-Trinetra-extractor --replicas=10 -n deepSightAI-Trinetra
```

### Cluster Autoscaling (cloud)

On EKS/GKE, enable Cluster Autoscaler to add nodes when Pods don't fit.

---

## Backup & Restore

### PostgreSQL

```bash
# Backup
kubectl exec -n deepSightAI-Trinetra deployment/deepSightAI-Trinetra-postgres -- \
  pg_dump -U postgres deepSightAI-Trinetra > backup-$(date +%Y%m%d).sql

# Restore
kubectl exec -i -n deepSightAI-Trinetra deployment/deepSightAI-Trinetra-postgres -- \
  psql -U postgres deepSightAI-Trinetra < backup-20250403.sql
```

For production, use **Velero** or cloud provider snapshots.

### MinIO

```bash
# mc (MinIO Client) must be installed locally
mc alias set deepSightAI-Trinetra http://minio.deepSightAI-Trinetra.local ACCESS_KEY SECRET_KEY
mc mirror deepSightAI-Trinetra/videos ./backup-minio-videos
```

Enable MinIO's built-in tiering to S3 for durability.

---

## Upgrading

```bash
# Pull new images (if changed in manifests)
kubectl rollout restart deployment/deepSightAI-Trinetra-api -n deepSightAI-Trinetra
kubectl rollout restart deployment/deepSightAI-Trinetra-extractor -n deepSightAI-Trinetra
kubectl rollout restart deployment/deepSightAI-Trinetra-embedder -n deepSightAI-Trinetra

# Monitor rollout
kubectl rollout status deployment/deepSightAI-Trinetra-api -n deepSightAI-Trinetra
```

Database migrations run automatically as init containers or on startup.

---

## Monitoring & Alerting

### Prometheus Metrics

All services expose Prometheus metrics on `/metrics` endpoint.

Create ServiceMonitor:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: deepSightAI-Trinetra-metrics
  namespace: deepSightAI-Trinetra
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: deepSightAI-Trinetra
  endpoints:
  - port: metrics
    interval: 30s
```

### Recommended Alerts (PrometheusRule)

- `APIDown` - API unavailable > 2 minutes
- `ExtractorQueueBacklog` - > 1000 pending segments
- `MilvusHighMemory` - > 80% memory usage
- `PostgresReplicationLag` - > 60 seconds

Full Prometheus rules in `k8s/base/monitoring/` (to be created).

---

## Security Hardening

### Pod Security Standards

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: ...
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000
  containers:
  - name: ...
    securityContext:
      readOnlyRootFilesystem: true
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
```

### Network Policies

Limit inter-pod communication:

```bash
kubectl apply -f k8s/network-policies/ -n deepSightAI-Trinetra
```

Only allow:
- API → PostgreSQL/Redis/MinIO/Milvus
- Extractor → MinIO
- Embedder → MinIO/Milvus

---

## Troubleshooting

### Pods stuck in Pending

```bash
kubectl describe pod <pod-name> -n deepSightAI-Trinetra
# Look for: insufficient resources, node selectors, taints
```

Common causes:
- Not enough CPU/memory on nodes
- No nodes matching nodeSelector/affinity rules
- PersistentVolumeClaim not bound (storage class missing)

### CrashLoopBackOff

Check logs:

```bash
kubectl logs <pod-name> -n deepSightAI-Trinetra --previous
```

Common issues:
- Database connection string wrong
- Secrets missing
- Image pull error (check imagePullPolicy, registry credentials)

### Services can't talk to each other

Check DNS:

```bash
kubectl exec -it <pod-name> -n deepSightAI-Trinetra -- nslookup postgres.deepSightAI-Trinetra.svc.cluster.local
```

Check NetworkPolicy:

```bash
kubectl get networkpolicy -n deepSightAI-Trinetra
```

---

## Production Checklist

Before going live:

- [ ] All services have resource limits and requests defined
- [ ] HPA configured for auto-scaling
- [ ] Ingress TLS configured (cert-manager with Let's Encrypt)
- [ ] Secrets stored in Vault (not in Git)
- [ ] Backup schedule configured (PostgreSQL + MinIO)
- [ ] Monitoring alerts active (Prometheus + Alertmanager)
- [ ] Log aggregation (Loki/ELK stack)
- [ ] Disaster recovery plan tested
- [ ] Load testing completed (Locust script)
- [ ] Security scan completed (Trivy, Kube-score)
- [ ] Network Policies enforced
- [ ] Pod Security Standards applied
- [ ] Audit logging enabled (WORM storage)

See [Operations Guide](operations/monitoring.md) for details on each item.

---

## Uninstall

```bash
# Delete namespace (removes all resources)
kubectl delete namespace deepSightAI-Trinetra

# Delete persistent volumes (WARNING: deletes all data!)
kubectl delete pvc -n deepSightAI-Trinetra --all

# If using Helm charts:
helm uninstall deepSightAI-Trinetra -n deepSightAI-Trinetra
```

---

## Next Steps

- Configure authentication: [User Guide → Auth](user-guide/auth.md)
- Set up monitoring: [Operations → Monitoring](operations/monitoring.md)
- Enable TLS: [Architecture → Security](architecture/security.md)
- Scale horizontally: [Operations → Scaling](operations/scaling.md)
