# Frequently Asked Questions

Answers to common questions about deploying, using, and troubleshooting deepSightAI Trinetra.

---

## General

### What is deepSightAI Trinetra?

deepSightAI Trinetra is an open-source video content search platform that lets you find specific moments in hours of video footage using natural language queries. It uses AI (CLIP model) to understand video content without manual tagging.

### Is deepSightAI Trinetra free?

Yes! deepSightAI Trinetra is **open-source (AGPL v3)** and free to use, modify, and deploy. You can run it on your own infrastructure without licensing fees.

For commercial support, hosted solutions, or enterprise features, contact sales@deepSightAI-Trinetra.com.

### What's the difference between deepSightAI Trinetra and traditional video analytics?

Traditional systems require **training custom models** for each detection scenario. deepSightAI Trinetra uses **natural language search** - just type what you're looking for without any training. It works out-of-the-box for common concepts (vehicles, people, colors, actions, scenes).

### What video formats are supported?

- **Container**: MP4, MOV, AVI, MKV, WEBM
- **Codecs**: H.264, H.265/HEVC, VP9, MJPEG (some legacy codecs)
- Max resolution: 4K (4096x2160)
- Max duration: 2 hours (longer videos should be pre-segmented)

RTSP streams are also supported for live cameras.

### How accurate is the search?

deepSightAI Trinetra (using CLIP) achieves **70-90% precision** on common concepts (vehicles, people, indoor/outdoor, colors). It's not perfect - sometimes returns false positives. Best results come from:
- Specific queries: "red pickup truck" vs "vehicle"
- Training/fine-tuning for your domain (coming in Phase 2 plugin system)

### Can deepSightAI Trinetra run on CPU only?

Yes, but embedding generation is **~10x slower** on CPU vs GPU. Recommended:
- Evaluation: CPU works for small batches (< 10 videos)
- Production: At least 1 GPU (NVIDIA T4, A10, A100) for embedder service

---

## Deployment

### What are the system requirements?

**Minimum (Docker Compose - evaluation)**:
- RAM: 8 GB (16 GB recommended)
- Disk: 100 GB SSD (plus storage for videos)
- CPU: 4 vCPU (8+ recommended)
- GPU: Not required (but strongly recommended)

**Production (Kubernetes)**:
- API nodes: 2+ (4 vCPU, 8 GB RAM each)
- Extractor workers: 10-50 (auto-scale based on queue)
- Embedder nodes: 1-5 GPU nodes (NVIDIA T4/A10/A100)
- PostgreSQL: High-availability cluster (Patroni) with 2+ replicas
- Milvus: Cluster mode with query/index nodes
- MinIO: Distributed cluster (4+ nodes for production)

### Can I run deepSightAI Trinetra in the cloud?

Yes! deepSightAI Trinetra is cloud-agnostic. Deploy on:
- AWS (EKS, EC2)
- Google Cloud (GKE)
- Azure (AKS)
- Any Kubernetes cluster

See [Installation → Cloud](../installation/cloud.md) for cloud-specific guides.

### Should I use Docker Compose or Kubernetes?

- **Docker Compose**: Evaluation, development, small teams (<10 videos/day), single-server deployments
- **Kubernetes**: Production, scaling, high availability, enterprise deployments

Kubernetes offers auto-scaling, built-in HA, and easier maintenance at scale.

### How do I enable HTTPS/TLS?

For production, all external endpoints should use TLS:

1. Obtain TLS certificate (Let's Encrypt, Cloud CA, or enterprise PKI)
2. Configure ingress (Nginx, Traefik, Istio) with TLS termination
3. For service-to-service mTLS, see [Security Architecture](../architecture/security.md)

Example Nginx ingress:
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: deepSightAI-Trinetra-ingress
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
spec:
  tls:
  - hosts:
    - api.deepSightAI-Trinetra.com
    - ui.deepSightAI-Trinetra.com
    secretName: deepSightAI-Trinetra-tls
  rules:
  - host: api.deepSightAI-Trinetra.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: api-service
            port:
              number: 8080
```

### How do I set up authentication?

deepSightAI Trinetra supports multiple auth methods:

1. **JWT** (default) - Users authenticate via AuthService, receive JWTs
2. **API Keys** - For programmatic machine-to-machine access
3. **OAuth2** - Social login (Google, GitHub) - optional
4. **Disable** (dev only) - Set `AUTH_ENABLED=false` (not recommended for production)

See [User Guide → Authentication](../user-guide/auth.md) for setup.

### Can I run multiple deepSightAI Trinetra instances (multi-region)?

Yes. Deploy separate clusters per region and:
- Use MinIO replication for data sync
- Configure Milvus in cluster mode across regions (experimental)
- Use PostgreSQL read replicas for cross-region read scaling
- Route users to nearest region via DNS (Route53 latency-based routing)

Active-active multi-master is not yet supported.

---

## Usage

### How long does processing take?

Processing time ≈ **1-2x video duration** (depends on GPU availability):
- 1-minute video: ~1-2 minutes
- 1-hour video: ~1-2 hours

Factors affecting speed:
- GPU count/type (more GPUs → parallel processing)
- Frame extraction FPS (default 1 FPS)
- Embedding batch size
- Storage I/O (MinIO performance)

### Can I search for specific people or objects?

deepSightAI Trinetra understands general concepts like "person", "car", "building", "red", "nighttime". But it **cannot** identify specific individuals (no facial recognition by default). For specialized detection (license plates, weapons, PPE), use the plugin system (Phase 2).

### What's the difference between frames and segments?

- **Segment**: 30-second video chunk (processing unit)
- **Frame**: Single still image (1 per second) extracted from segment

You interact with frames in search results, but processing happens at segment level.

### Why are some videos "stuck" in processing?

Common reasons:
- Extractor workers all busy (check queue depth)
- Corrupt video file (check extractor logs)
- Milvus down (embedder can't insert vectors)
- MinIO out of space

Check logs and restart services if needed.

### Can I delete individual search results?

No, search results are derived from indexed embeddings. To remove content, delete the video entirely (which removes all associated frames and embeddings). Audit logs remain (immutable).

---

## Scaling & Performance

### How many videos can deepSightAI Trinetra handle?

Depends on your cluster size. Approximate capacity:

**Small (Docker Compose)**:
- 10 videos/day
- 10,000 total videos
- 10M+ embedded frames

**Medium (k3s, 5 nodes)**:
- 100 videos/day
- 100,000 total videos
- 100M+ embedded frames

**Large (EKS, 50 nodes)**:
- 1,000+ videos/day
- Millions of videos
- Billions of embedded frames

Milvus scales horizontally to billions of vectors. Storage capacity is the main limit.

### How do I scale extractors?

Extractors are stateless - just add more replicas:

**Docker Compose**:
```bash
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" up -d --scale extractor=10
```

**Kubernetes**:
```bash
kubectl scale deployment extractor --replicas=20
# Or configure HPA for auto-scaling
kubectl autoscale deployment extractor --cpu-percent=70 --min=10 --max=50
```

Extractors register with the registry service and pull jobs from Redis queue.

### What GPU do I need?

For embedder service:
- **Minimum**: NVIDIA T4 (16 GB) - handles ~10 FPS
- **Recommended**: NVIDIA A10 (24 GB) - ~20 FPS
- **High-end**: NVIDIA A100 (40/80 GB) - ~40+ FPS

More VRAM = larger batch size = higher throughput.

Multiple GPUs can be used in one embedder pod (set `CUDA_VISIBLE_DEVICES`) or run multiple embedder replicas.

### How do I monitor system health?

See [Monitoring Guide](../operations/monitoring.md). Key metrics:
- API request rate and latency
- Extractor queue depth (backlog)
- Embedder FPS (frames per second)
- Milvus search latency
- Storage utilization

Set up Grafana dashboards and alerts.

---

## Troubleshooting

### Where are the logs?

**Docker Compose**:
```bash
docker logs deepSightAI-Trinetra-api
docker logs --follow extractor
```

**Kubernetes**:
```bash
kubectl logs -f deployment/api -n deepSightAI-Trinetra
kubectl logs -f statefulset/milvus -n deepSightAI-Trinetra
```

**Structured logs** are in JSON format by default.

### How do I enable debug logging?

Set `LOG_LEVEL=DEBUG` for the service.

**Docker Compose**:
```bash
# Edit .env
LOG_LEVEL=DEBUG
docker-compose down && docker-compose up -d
```

**Kubernetes**:
```bash
kubectl set env deployment/api LOG_LEVEL=DEBUG -n deepSightAI-Trinetra
kubectl rollout restart deployment/api -n deepSightAI-Trinetra
```

### Why is my search slow?

See [Troubleshooting](../operations/troubleshooting.md#search-slow-5-seconds) section.

Common causes:
- Milvus index not built or optimized
- Insufficient Milvus resources
- Network latency between API and Milvus

---

## Data Management

### Where is my data stored?

- **PostgreSQL**: Metadata (users, videos, segments) in Docker volume or PVC
- **MinIO**: Videos and frames in object storage (default: `deepSightAI-Trinetra/` bucket)
- **Milvus**: Embeddings in vector database storage (local disk or cloud storage)
- **Redis**: Cache and queues (ephemeral, stored in memory)

### How do I migrate to new hardware?

1. Set up new cluster
2. Take fresh backups from old cluster
3. Restore to new cluster
4. Switch DNS/load balancer to new cluster
5. Decommission old cluster

See [Backup & Restore](../operations/backup-restore.md) for details.

### Can I export my data?

Yes. deepSightAI Trinetra is your data - you can export:

- **Videos**: Download from MinIO directly
- **Frames**: Download from MinIO `frames/` prefix
- **Metadata**: Export from PostgreSQL (CSV, JSON)
- **Embeddings**: Export from Milvus (numpy arrays, binary)

### How do I delete all data (GDPR)?

For complete data erasure per GDPR Article 17:

```bash
# 1. Delete from PostgreSQL
psql deepSightAI-Trinetra -c "DELETE FROM videos WHERE tenant_id='tenant-to-delete';"
# Also delete from audit_logs if needed (but those are WORM - may need to drop table)

# 2. Delete from MinIO
mc rm --recursive --force minio/deepSightAI-Trinetra/videos/tenant_to_delete/
mc rm --recursive --force minio/deepSightAI-Trinetra/frames/tenant_to_delete/

# 3. Delete from Milvus
# Drop partitions or delete vectors with tenant_id filter
```

**Note**: Audit logs are WORM (Write Once Read Many) and **cannot** be deleted due to compliance requirements. They must be retained for 7+ years.

---

## Development & Contributing

### How do I build from source?

See [Contributing](../about/contributing.md) for development setup.

Quick start:
```bash
git clone https://github.com/yourorg/deepSightAI-Trinetra.git
cd deepSightAI-Trinetra
# Install dependencies in each service directory
pip install -r Server\ and\ Extractor/requirements.txt
pip install -r Embedder/requirements_embedder.txt
pip install -r AuthService/requirements.txt
# Run with Docker Compose
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" up -d
```

### How do I add a new plugin?

deepSightAI Trinetra plugin architecture is in Phase 2. See [Architecture → Components](../architecture/components.md#plugin-architecture) for design. Plugins are Python modules implementing a standard interface.

### Where can I find API documentation?

Full API reference: [User Guide → API Reference](../user-guide/api.md) or auto-generated OpenAPI spec at `/docs` when running (Swagger UI).

---

## Support & Community

- **GitHub Issues**: [Report bugs/request features](https://github.com/yourorg/deepSightAI-Trinetra/issues)
- **Discussions**: [Community questions](https://github.com/yourorg/deepSightAI-Trinetra/discussions)
- **Slack**: [deepSightAI-Trinetra-community.slack.com](https://deepSightAI-Trinetra-community.slack.com)
- **Documentation**: This site
- **Commercial support**: support@deepSightAI-Trinetra.com

---

## Still Have Questions?

If your question isn't answered here:

1. Search the [documentation](../) thoroughly
2. Check [Troubleshooting](../operations/troubleshooting.md)
3. Ask in [GitHub Discussions](https://github.com/yourorg/deepSightAI-Trinetra/discussions)
4. Join our [Slack community](https://deepSightAI-Trinetra-community.slack.com)

We're happy to help! 😊
