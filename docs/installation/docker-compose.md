# Installation: Docker Compose (Single Host)

**Best for**: Evaluation, development, small deployments (< 10 videos/day)

This guide covers deploying the entire ClipSight stack on a single machine using Docker Compose.

---

## Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| RAM | 8 GB | 16 GB |
| Disk | 100 GB SSD | 500 GB SSD |
| CPU | 4 vCPU | 8 vCPU |
| OS | Linux (Ubuntu 22.04+) / macOS / Windows WSL2 | Linux server |

**Software**:
- Docker 24+ (`docker --version`)
- Docker Compose v2 (`docker compose version`)

---

## Architecture (Docker Compose)

```
┌─────────────────────────────────────────────────────┐
│                   Docker Host (single node)         │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │    API     │  │ Extractor  │  │  Embedder  │  │
│  │  :8080     │  │  :8001     │  │  :8002     │  │
│  └────────────┘  └────────────┘  └────────────┘  │
│                                                    │
│  ┌─────────────────────────────────────────────┐  │
│  │        Shared Infrastructure                │  │
│  │  PostgreSQL :5432  │  Redis :6379          │  │
│  │  MinIO :9000       │  Milvus :19530        │  │
│  └─────────────────────────────────────────────┘  │
│                                                     │
└─────────────────────────────────────────────────────┘
```

All services communicate over Docker's internal network. Data persisted in Docker volumes.

---

## Step-by-Step Installation

### 1. Clone Repository

```bash
git clone https://github.com/yourorg/clipsight.git
cd clipsight
```

### 2. Create Environment Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` to customize (optional - defaults work for local dev):

```bash
# Main API
API_PORT=8080
API_WORKERS=4

# Extractor
EXTRACTOR_PORT=8001

# Embedder
EMBEDDER_PORT=8002

# Database
POSTGRES_DB=clipsight
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-secure-password-change-this

# Redis
REDIS_PASSWORD=  # leave empty for dev

# MinIO
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin

# Milvus
MILVUS_PORT=19530
```

**⚠️ SECURITY**: Change all default passwords before production use!

### 3. Start Services

We use two separate Compose files because extractor and embedder have different scaling characteristics:

```bash
# Start core services (API, PostgreSQL, Redis, MinIO, Milvus)
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" up -d

# Start embedder (can be scaled separately)
docker-compose -f "Embedder/docker-compose.embedder.yaml" up -d
```

### 4. Verify Deployment

Check all containers are running:

```bash
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" ps
docker-compose -f "Embedder/docker-compose.embedder.yaml" ps
```

Expected output:

```
Name                          Command               State           Ports
------------------------------------------------------------------------------------------
clipsight-api         uvicorn main_api:app ...   Up (healthy)   0.0.0.0:8080->8080/tcp
clipsight-postgres    docker-entrypoint.sh ...   Up (healthy)   5432/tcp
clipsight-redis       docker-entrypoint.sh ...   Up (healthy)   6379/tcp
clipsight-minio       minio server /data ...     Up (healthy)   0.0.0.0:9090->9000/tcp
clipsight-milvus      milvus run standalone ...  Up (healthy)   0.0.0.0:19530->19530/tcp
clipsight-extractor   python extractor.py       Up (healthy)   8001/tcp
clipsight-embedder    python embedder.py        Up (healthy)   8002/tcp
```

**Wait 60 seconds** for all services to fully initialize (especially Milvus needs time to load indexes).

### 5. Test Health Endpoints

```bash
# API health
curl http://localhost:8080/health

# Expected: {"status":"healthy","service":"api"}

# Extractor health
curl http://localhost:8001/health

# MinIO health
curl http://localhost:9000/minio/health/live

# Redis
docker exec clipsight-redis redis-cli ping
# Expected: PONG
```

---

## Accessing Services

| Service | URL | Credentials |
|---------|-----|-------------|
| **Main API** | http://localhost:8080 | None (if auth disabled) or JWT |
| **Extractor** | http://localhost:8001 | Internal only |
| **Embedder** | http://localhost:8002 | Internal only |
| **Streamlit UI** | http://localhost:8501 | None |
| **MinIO Console** | http://localhost:9090 | minioadmin / minioadmin |
| **Milvus** | localhost:19530 | No auth (dev) |
| **PostgreSQL** | localhost:5432 | postgres / (from .env) |
| **Redis** | localhost:6379 | (from .env) |

---

## Data Persistence

All persistent data stored in Docker named volumes:

```bash
# List volumes
docker volume ls | grep clipsight

# Backup all volumes
docker run --rm -v clipsight_postgres_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/postgres-backup.tar.gz -C /data .
```

Volumes created:
- `clipsight_postgres_data` - Database files
- `clipsight_minio_data` - Uploaded videos and frames
- `clipsight_redis_data` - Cache and service registry
- `clipsight_milvus_data` - Vector embeddings and indexes

---

## Updating

To update to a new version:

```bash
git pull origin main
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" pull
docker-compose -f "Embedder/docker-compose.embedder.yaml" pull
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" up -d
docker-compose -f "Embedder/docker-compose.embedder.yaml" up -d
```

Database migrations run automatically on startup (if needed).

---

## Logs & Debugging

### View logs for specific service

```bash
# API logs
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" logs -f api

# All services
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" logs -f
```

### Structured JSON logs

All apps output JSON logs by default. Parse with `jq`:

```bash
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" logs api 2>&1 \
  | grep "level=ERROR" \
  | jq '.message'
```

---

## Stopping & Cleaning Up

### Graceful shutdown (preserves data)

```bash
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" stop
docker-compose -f "Embedder/docker-compose.embedder.yaml" stop
```

### Remove containers (preserves data)

```bash
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" down
docker-compose -f "Embedder/docker-compose.embedder.yaml" down
```

### Remove everything (WARNING: DELETES ALL DATA)

```bash
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" down -v
docker-compose -f "Embedder/docker-compose.embedder.yaml" down -v
docker system prune -af --volumes
```

---

## Network Configuration

Services communicate via Docker network `clipsight_default`. To inspect:

```bash
docker network inspect clipsight_default
```

To connect additional tools (like `kafkacat` for debugging):

```bash
docker run -it --network clipsight_default --rm kafkacat -b kafka:9092 -L
```

---

## Common Issues

### Port conflicts

If ports 8080, 9090, etc. are already in use, edit `.env` to change them, or stop conflicting services.

### Out of memory

Milvus and extractor are memory-intensive. Ensure at least 8GB free. Check:

```bash
free -h
docker stats
```

If OOM kills occur, reduce batch sizes in config or add swap:

```bash
docker-compose -f "Embedder/docker-compose.embedder.yaml" up -d --scale embedder=1
```

### Milvus fails to start

Milvus needs several dependencies (etcd). Check logs:

```bash
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" logs milvus
```

Wait 2-3 minutes on first start. If still failing, check disk space and kernel parameters.

---

## Production Considerations

**Docker Compose is NOT recommended for production**. For production:

- Use Kubernetes for orchestration, auto-scaling, and high availability
- Enable authentication (JWT/OAuth2)
- Enable TLS for all services
- Use managed databases (RDS, etc.) instead of containers
- Set up backups and monitoring
- Configure proper resource limits

See [Kubernetes Installation](kubernetes.md) for production deployment.

---

## Next Steps

- Configure authentication: [User Guide → Authentication](user-guide/auth.md)
- Deploy to Kubernetes: [Installation → Kubernetes](kubernetes.md)
- Learn architecture: [Architecture Overview](architecture/index.md)
- Set up monitoring: [Operations Guide](operations/monitoring.md)
