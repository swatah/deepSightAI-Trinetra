# Troubleshooting

This guide helps diagnose and resolve common issues with deepSightAI Trinetra deployments.

---

## Quick Diagnostic Checklist

Before diving into specific issues, run through these checks:

- [ ] All containers/pods are running (`docker ps` or `kubectl get pods`)
- [ ] Services return 200 on health endpoints (`/health`)
- [ ] Database connectivity (`psql`, or `kubectl exec postgres -- psql`)
- [ ] Redis connectivity (`redis-cli ping`)
- [ ] MinIO connectivity (`mc ls minio/deepSightAI-Trinetra/`)
- [ ] Milvus connectivity (`milvus-cli list collections`)
- [ ] Sufficient disk space (`df -h`)
- [ ] Sufficient memory (`free -h`, `docker stats`)
- [ ] Network connectivity between services (`kubectl logs`, `docker network inspect`)

If any check fails, see the relevant section below.

---

## Service Won't Start

### Container exits immediately

**Check logs**:
```bash
docker logs <container-name>
# or
kubectl logs <pod-name> -n deepSightAI-Trinetra
```

**Common causes**:

1. **Missing environment variables**
   ```bash
   # Check .env file or K8s ConfigMap
   docker exec <container> env | grep -v "^PATH=" | grep -v "^HOME="
   ```

2. **Database not reachable**
   ```bash
   # From inside container, test connectivity
   docker exec <container> nc -zv postgres 5432
   docker exec <container> nc -zv redis 6379
   ```

3. **Port conflict**
   ```bash
   sudo lsof -i :8080
   # Change port in config or stop conflicting service
   ```

4. **Out of memory**
   ```bash
   docker stats
   # Reduce resource limits or add swap
   ```

---

## Video Upload Fails

### "File too large" error

- Check `client_max_body_size` in Nginx/Ingress (increase to >2GB)
- Check reverse proxy timeouts (increase to 300s+)
- Client may timeout - use resumable upload for large files

### "Upload hangs" or times out

**Check**:
- Network bandwidth (`iftop`, `nethogs`)
- Disk I/O on MinIO (`iostat`, `docker stats`)
- Reverse proxy timeouts (Nginx `proxy_read_timeout`, `proxy_send_timeout`)

**Increase timeouts** in reverse proxy configuration.

### Upload succeeds but video never processes

1. Check video record in PostgreSQL:
   ```sql
   SELECT * FROM videos WHERE id = 'vid_xxx';
   -- status should be 'processing'
   ```

2. Check extractor queue:
   ```bash
   docker exec deepSightAI-Trinetra-redis redis-cli
   > LLEN extractor_queue
   ```

3. Check extractor logs:
   ```bash
   docker logs deepSightAI-Trinetra-extractor
   # Look for errors like "FFmpeg error", "MinIO connection failed"
   ```

4. Common issues:
   - Invalid video codec (convert with `ffmpeg -i input.mp4 -c:v libx264 output.mp4`)
   - Corrupt video file (test with `ffprobe`)
   - MinIO credentials incorrect
   - Insufficient disk space in MinIO

---

## Search Returns No Results

### Video status is "ready" but search finds nothing

1. **Verify embedding completed**:
   ```bash
   # Check Milvus collection has vectors
   from pymilvus import Collection
   collection = Collection("video_frames")
   collection.num_entities  # Should be > 0
   ```

2. **Check Milvus index created**:
   ```bash
   collection.describe_index()
   # Should show HNSW index with params
   ```

3. **Test embedding generation**:
   - Check embedder logs for errors
   - Embedder should show: "Processed X frames", "Inserted X vectors into Milvus"

4. **Verify tenant isolation** (if multi-tenant):
   - Ensure search request includes correct `tenant_id`
   - Milvus partitions exist: `milvus-cli list partitions --collection video_frames`
   - Tenant's partition has entities

5. **Test search directly**:
   ```python
   from pymilvus import Collection
   collection = Collection("video_frames")
   # Search with empty query vector (random) to see if any results
   results = collection.search(
       data=[[0.0]*512],  # dummy vector
       anns_field="embedding",
       param={"metric_type": "COSINE", "params": {"nprobe": 10}},
       limit=10
   )
   print(results)
   ```

### Search is slow (>5 seconds)

- **Milvus index not built** - First search triggers index build; wait or trigger manually
- **HNSW parameters too conservative** - Increase `M` and `efConstruction` for faster recall
- **Insufficient Milvus resources** - Check CPU, RAM, and disk I/O on Milvus nodes
- **Network latency** - Ensure API and Milvus in same VPC/region
- **Large result set** - Reduce `top_k`

**Optimization**:
```bash
# Increase search parameters
collection.load()
results = collection.search(
    data=[query_vector],
    anns_field="embedding",
    param={"metric_type": "COSINE", "params": {"ef": 64}},  # Increase ef for speed-accuracy tradeoff
    limit=10
)
```

---

## Embedder Service Fails

### CUDA out of memory

```bash
# Check GPU memory
nvidia-smi

# Reduce batch size in config
export EMBEDDER_BATCH_SIZE=16  # instead of 32 or 64

# If still OOM, reduce model size:
export EMBEDDER_MODEL=openai/clip-vit-base-patch32  # instead of large
```

### Embedder stuck on "Processing..." forever

1. **Check MinIO connectivity** - embedder polls MinIO for new frames
   ```bash
   docker logs embedder | grep "MinIO"
   ```

2. **Verify queue exists** - Redis stream `frames_queue` should have pending entries
   ```bash
   docker exec deepSightAI-Trinetra-redis redis-cli
   > XLEN frames_queue
   ```

3. **Check for stuck frames** - old frames might be locked; restart embedder to clear state

---

## Extractor Service Issues

### "No extractors available" error

The registry reports no available extractors. Causes:

1. **All extractors busy** - scale horizontally:
   ```bash
   docker-compose -f "Server and Extractor/docker-compose.extractor.yml" up -d --scale extractor=5
   # or in K8s: kubectl scale deployment extractor --replicas=10
   ```

2. **Extractors failed to register** - check extractor logs
   ```bash
   docker logs extractor
   # Should see: "Registered with registry at http://registry:8000"
   ```

3. **Registry unreachable** - check registry service
   ```bash
   curl http://localhost:8000/health
   ```

### Video segmentation fails (ffmpeg errors)

```bash
# Test video file with ffmpeg directly
docker exec extractor ffprobe /path/to/video.mp4

# Common issues:
# - Unsupported codec: convert video
# - Corrupt file: re-download or re-encode
# - Missing audio stream: usually OK, extractor handles
```

---

## Database Issues

### "Too many connections"

Increase PostgreSQL `max_connections` in `postgresql.conf`:
```
max_connections = 200
```

Also tune application connection pools (SQLAlchemy `pool_size`, `max_overflow`).

### "Database is locked" / deadlocks

Check for long-running transactions:
```sql
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state != 'idle' AND now() - pg_stat_activity.query_start > interval '5 minutes';
```

Kill offending transaction:
```sql
SELECT pg_terminate_backend(pid);
```

### Disk full

```bash
df -h /var/lib/postgresql
# Clean up old backups, WAL files, or increase storage

# Check table sizes
SELECT pg_size_pretty(pg_database_size('deepSightAI-Trinetra'));
```

---

## Redis Issues

### Connection refused

```bash
docker exec deepSightAI-Trinetra-redis redis-cli ping
# Should return PONG

# If not, restart redis
docker restart deepSightAI-Trinetra-redis
```

### Out of memory

Redis eviction policy:
```
maxmemory 2gb
maxmemory-policy allkeys-lru  # evict least recently used
```

Or increase memory.

---

## Milvus Issues

### Search returns empty results despite data

1. **Check collection loaded**:
   ```python
   collection.load()
   collection.num_entities  # Should be > 0
   ```

2. **Check partition data** (if using per-tenant partitions):
   ```python
   collection.load(partition_name="tenant-acme")
   ```

3. **Verify index exists**:
   ```python
   collection.describe_index()
   # If index not created, create it:
   collection.create_index(
       field_name="embedding",
       index_params={"metric_type": "COSINE", "index_type": "HNSW", "params": {"M": 16, "efConstruction": 200}}
   )
   ```

### Milvus high latency (>1s)

- **Index not optimal**: Increase `ef` search parameter for accuracy, or `nprobe` for IVF index
- **Insufficient resources**: Milvus is memory-intensive; increase CPU/RAM
- **Large dataset**: HNSW scales logarithmically but still needs sufficient memory
- **Cold cache**: First search slower; subsequent searches faster

---

## Authentication Issues

### "401 Unauthorized" despite valid token

1. **Check token expiration**:
   ```bash
   # Decode JWT (no verification)
   python -c "import jwt; print(jwt.decode('YOUR_TOKEN', options={'verify_signature': False}))"
   ```

2. **Verify AuthService reachable**:
   ```bash
   curl http://auth-service:8000/health
   ```

3. **Check middleware configuration** in API service - is `require_auth` dependency applied?

4. **Token audience/issuer mismatch** - Verify JWT `aud` and `iss` claims match expected values

### "403 Forbidden" insufficient permissions

User's JWT lacks required role for endpoint. Check user's roles in database:
```sql
SELECT * FROM user_roles WHERE user_id = 'user_abc';
```

---

## Performance Issues

### High CPU usage

Identify culprit:
```bash
docker stats  # See which container using CPU
top / htop on host

# If embedder using CPU: normal during batch processing
# If API using CPU: high request volume; scale horizontally
# If extractor using CPU: video processing; add more workers
```

### Slow uploads

- Check network bandwidth (`iperf3` between client and server)
- Check disk I/O on MinIO (`iostat -x 1`)
- Check reverse proxy buffers/limits

### API response times high

- Check database slow queries:
  ```sql
  SELECT query, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;
  ```
- Add database indexes as needed
- Enable Redis caching for frequent queries
- Scale API horizontally (add replicas)

---

## Kubernetes-Specific Issues

### Pods stuck in `Pending`

```bash
kubectl describe pod <pod-name>
# Look for events: Insufficient resources, PVC binding, etc.

# Common fixes:
# - Add more nodes to cluster
# - Increase resource requests/limits if too high
# - Ensure PersistentVolumeClaims have matching storage class
```

### Pods crashlooping

```bash
kubectl logs <pod-name> --previous  # Last container logs
kubectl describe pod <pod-name>     # Events and state

# Common causes:
# - Invalid environment variable
# - Missing secret/configmap
# - Liveness probe too aggressive (adjust initialDelaySeconds, periodSeconds)
```

### Services not reachable

```bash
kubectl get svc
kubectl describe svc <service-name>
kubectl get endpoints <service-name>  # Should list pod IPs

# Check pod labels match service selector
kubectl get pods --show-labels
```

---

## Logging & Debugging

### Enable debug logging

Set `LOG_LEVEL=DEBUG` environment variable for the service.

Then view structured JSON logs:

```bash
docker logs --follow deepSightAI-Trinetra-api | jq '.message'
# Filter by level
docker logs deepSightAI-Trinetra-api 2>&1 | grep '"level":"ERROR"'
```

### Distributed tracing (Jaeger)

If Jaeger is configured:

1. Instrument FastAPI app:
   ```python
   from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
   FastAPIInstrumentor.instrument_app(app)
   ```

2. View traces at `http://localhost:16686`

---

## Common Error Messages

| Error | Likely Cause | Fix |
|-------|--------------|-----|
| `Connection refused` | Service down or wrong host/port | Check service status, network policies |
| `Timeout` | Slow network or overloaded service | Increase timeouts, scale horizontally |
| `413 Payload Too Large` | Request body exceeds limit | Increase `client_max_body_size` |
| `429 Too Many Requests` | Rate limit exceeded | Throttle client, increase limits in config |
| `500 Internal Server Error` | Application bug | Check application logs, report issue |
| `503 Service Unavailable` | Service not ready or overloaded | Check health, increase resources |

---

## Getting Help

If you're still stuck:

1. **Check logs** - Application, database, and infrastructure logs
2. **Search GitHub Issues** - Someone may have encountered the same problem
3. **Community Slack** - Real-time help from community
4. **Create an Issue** - Provide:
   - Steps to reproduce
   - Relevant logs (sensitive data redacted)
   - Environment details (Docker/K8s, versions)
   - What you've already tried

Include logs excerpts and error messages. The more context you provide, the faster we can help.

---

## Preventive Maintenance

- **Monitor disk space** - Alert at >80% usage
- **Regular backups** - Verify backups weekly
- **Keep software updated** - Security patches for OS, Docker, K8s
- **Capacity planning** - Monitor growth trends; plan scaling
- **DR drills** - Practice restore quarterly

---

*Can't find your issue? Check [FAQ](../faq.md) or the [Operations Guide](../monitoring.md).*
