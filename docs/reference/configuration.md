# Configuration Reference

This document lists all configuration options for ClipSight services, typically set via environment variables or configuration files.

---

## Overview

Configuration is managed through:

1. **Environment variables** - Primary method for containerized deployments
2. **Configuration files** - Optional YAML/JSON configs for complex settings
3. **Kubernetes ConfigMaps/Secrets** - For K8s deployments
4. **Docker Compose `.env` files** - For local development

All configuration options are documented per service below.

---

## Global Settings

Settings that apply across multiple services.

### `LOG_LEVEL`

- **Description**: Set logging verbosity
- **Default**: `INFO`
- **Options**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- **Example**: `LOG_LEVEL=DEBUG` (for troubleshooting)

### `JAEGER_AGENT_HOST`

- **Description**: Hostname for Jaeger distributed tracing agent
- **Default**: `localhost`
- **Example**: `JAEGER_AGENT_HOST=jaeger-agent`

---

## Main API Service

Environment variables for the main FastAPI service.

### `API_HOST`

- **Description**: Network interface to bind
- **Default**: `0.0.0.0`
- **Example**: `API_HOST=0.0.0.0`

### `API_PORT`

- **Description**: Port for HTTP server
- **Default**: `8080`
- **Example**: `API_PORT=8080`

### `API_WORKERS`

- **Description**: Number of Gunicorn worker processes
- **Default**: `4`
- **Example**: `API_WORKERS=8` (for high-throughput deployments)

### `DATABASE_URL`

- **Description**: PostgreSQL connection string
- **Default**: `postgresql://postgres:postgres@postgres:5432/clipsight`
- **Example**: `DATABASE_URL=postgresql://user:pass@host:5432/dbname`

### `REDIS_URL`

- **Description**: Redis connection string
- **Default**: `redis://redis:6379`
- **Example**: `REDIS_URL=redis://:password@redis:6379/0`

### `MINIO_URL`

- **Description**: MinIO S3-compatible endpoint
- **Default**: `http://minio:9000`
- **Example**: `MINIO_URL=https://s3.amazonaws.com`

### `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`

- **Description**: MinIO credentials
- **Default**: `minioadmin` / `minioadmin`
- **Example**: `MINIO_ACCESS_KEY=your-access-key`

### `MILVUS_HOST` / `MILVUS_PORT`

- **Description**: Milvus vector database connection
- **Default**: `milvus` / `19530`
- **Example**: `MILVUS_HOST=milvus-cluster`

### `AUTH_ENABLED`

- **Description**: Enable JWT authentication middleware
- **Default**: `false` (dev), `true` (prod)
- **Options**: `true`, `false`
- **Example**: `AUTH_ENABLED=true`

### `AUTH_SERVICE_URL`

- **Description**: URL of AuthService for token validation
- **Default**: `http://auth-service:8000`
- **Example**: `AUTH_SERVICE_URL=https://auth.clipsight.com`

---

## Extractor Service

### `EXTRACTOR_PORT`

- **Description**: HTTP port for extractor API
- **Default**: `8001`
- **Example**: `EXTRACTOR_PORT=8001`

### `EXTRACTOR_WORKERS`

- **Description**: Number of parallel extraction workers
- **Default**: `10`
- **Example**: `EXTRACTOR_WORKERS=20` (scale for high volume)

### `EXTRACTOR_QUEUE_TIMEOUT`

- **Description**: Seconds to wait for jobs from Redis queue
- **Default**: `30`
- **Example**: `EXTRACTOR_QUEUE_TIMEOUT=60`

### `SEGMENT_DURATION_SECONDS`

- **Description**: Length of video segments for processing
- **Default**: `30`
- **Example**: `SEGMENT_DURATION_SECONDS=60` (fewer, larger segments)

### `FRAME_EXTRACTION_FPS`

- **Description**: Frames per second to extract from video
- **Default**: `1`
- **Example**: `FRAME_EXTRACTION_FPS=2` (higher density, more storage/compute)

---

## Embedder Service

### `EMBEDDER_PORT`

- **Description**: HTTP port for embedder API
- **Default**: `8002`
- **Example**: `EMBEDDER_PORT=8002`

### `EMBEDDER_BATCH_SIZE`

- **Description**: Number of frames to process in one batch
- **Default**: `32`
- **Example**: `EMBEDDER_BATCH_SIZE=64` (larger batches need more GPU memory)

### `EMBEDDER_MODEL`

- **Description**: CLIP model variant to use
- **Default**: `openai/clip-vit-base-patch32`
- **Options**: See HuggingFace model hub
- **Example**: `EMBEDDER_MODEL=openai/clip-vit-large-patch14` (higher quality, slower)

### `EMBEDDER_DEVICE`

- **Description**: Device for inference
- **Default**: `cuda` if GPU available, else `cpu`
- **Options**: `cuda`, `cpu`, `mps` (Apple Silicon)
- **Example**: `EMBEDDER_DEVICE=cuda`

### `EMBEDDER_GPU_MEMORY_FRACTION`

- **Description**: Fraction of GPU memory to allocate (0.0-1.0)
- **Default**: `0.8`
- **Example**: `EMBEDDER_GPU_MEMORY_FRACTION=0.9`

---

## Registry Service

### `REGISTRY_PORT`

- **Description**: HTTP port for registry API
- **Default**: `8000`
- **Example**: `REGISTRY_PORT=8000`

### `REGISTRY_HEARTBEAT_TTL`

- **Description**: Seconds before extractor registration expires
- **Default**: `30`
- **Example**: `REGISTRY_HEARTBEAT_TTL=60` (more tolerant to network issues)

---

## AuthService

### `AUTH_SERVICE_PORT`

- **Description**: HTTP port for AuthService
- **Default**: `8000`
- **Example**: `AUTH_SERVICE_PORT=8000`

### `JWT_ALGORITHM`

- **Description**: Algorithm for signing JWTs
- **Default**: `RS256` (recommended) or `HS256` (dev only)
- **Example**: `JWT_ALGORITHM=RS256`

### `JWT_PRIVATE_KEY_PATH` / `JWT_PUBLIC_KEY_PATH`

- **Description**: Paths to RSA private/public key files
- **Default**: `/run/secrets/jwt-private.pem` / `/run/secrets/jwt-public.pem`
- **Example**: `JWT_PRIVATE_KEY_PATH=/etc/clipsight/jwt.key`

### `JWT_EXPIRY_HOURS`

- **Description**: Token expiration time
- **Default**: `24`
- **Example**: `JWT_EXPIRY_HOURS=168` (1 week)

### `OAUTH2_CLIENT_ID` / `OAUTH2_CLIENT_SECRET`

- **Description**: OAuth2 credentials for social login
- **Default**: none
- **Example**: `OAUTH2_CLIENT_ID=google-client-id`

---

## AuditService

### `AUDIT_SERVICE_PORT`

- **Description**: HTTP port for AuditService
- **Default**: `8003`
- **Example**: `AUDIT_SERVICE_PORT=8003`

### `AUDIT_KAFKA_BROKERS`

- **Description**: Comma-separated list of Kafka brokers for audit stream
- **Default**: `kafka:9092`
- **Example**: `AUDIT_KAFKA_BROKERS=kafka-0:9092,kafka-1:9092`

### `AUDIT_KAFKA_TOPIC`

- **Description**: Kafka topic for audit events
- **Default**: `audit-logs`
- **Example**: `AUDIT_KAFKA_TOPIC=clipsight-audit`

### `AUDIT_RETENTION_DAYS`

- **Description**: Days to keep hot audit data in PostgreSQL
- **Default**: `90`
- **After**: Older entries archived to cold storage (S3 Glacier)
- **Example**: `AUDIT_RETENTION_DAYS=365`

---

## Storage - MinIO

### `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`

- **Description**: Administrative credentials
- **Default**: `minioadmin` / `minioadmin`
- **Example**: Set strong passwords in production!

### `MINIO_REGION`

- **Description**: Region for bucket creation
- **Default**: `us-east-1`
- **Example**: `MINIO_REGION=eu-west-1`

**Additional settings**: See MinIO documentation for server-side encryption, replication, etc.

---

## Database - PostgreSQL

See PostgreSQL documentation for:

- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- Connection pooling: `PGCONNECT_TIMEOUT`, `MAX_CONNECTIONS`
- WAL settings for replication
- `shared_preload_libraries=pgcrypto` (for encryption)
- Row-level security (RLS) policies

---

## Cache - Redis

### `REDIS_PASSWORD`

- **Description**: Authentication password (if enabled)
- **Default**: none
- **Example**: `REDIS_PASSWORD=secure-redis-password`

---

## Message Queue - Kafka

### `KAFKA_BOOTSTRAP_SERVERS`

- **Description**: Comma-separated list of Kafka brokers
- **Default**: `kafka:9092`
- **Example**: `KAFKA_BOOTSTRAP_SERVERS=kafka-0:9092,kafka-1:9092`

---

## Monitoring

### `PROMETHEUS_MULTIPROC_DIR`

- **Description**: Directory for Prometheus multiprocess metrics (when using Gunicorn)
- **Default**: `/tmp`
- **Example**: `PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus`

---

## Security

### `TLS_CERT_PATH` / `TLS_KEY_PATH`

- **Description**: Paths to TLS certificate and private key
- **Default**: none (HTTP only in dev)
- **Example**: `TLS_CERT_PATH=/etc/ssl/certs/clipsight.crt`

### `VAULT_ADDR` / `VAULT_TOKEN`

- **Description**: HashiCorp Vault connection for secrets management
- **Default**: none
- **Example**: `VAULT_ADDR=https://vault.clipsight.com`

---

## Feature Flags

### `FEATURE_X_AI_SEARCH`

- **Description**: Enable experimental AI-powered search enhancements
- **Default**: `false`
- **Options**: `true`, `false`

### `FEATURE_BATCH_UPLOADS`

- **Description**: Enable bulk upload API
- **Default**: `true`

---

## Performance Tuning

| Setting | Purpose | Typical Values |
|---------|---------|----------------|
| `API_WORKERS` | API concurrency | `CPU cores * 2` |
| `EXTRACTOR_WORKERS` | Parallel extractions | `10-50` (HPA in K8s) |
| `EMBEDDER_BATCH_SIZE` | GPU throughput | `16-64` (depends on GPU memory) |
| `POSTGRQL_MAX_CONNECTIONS` | DB pool size | `100-500` |
| `REDIS_MAX_CONNECTIONS` | Redis pool | `50-200` |

Monitor metrics and adjust based on load.

---

## Kubernetes-Specific

When deploying on K8s, configuration typically comes from:

- **ConfigMaps** for non-sensitive settings
- **Secrets** for credentials and TLS keys
- **Environment variables** injected via deployment manifests

See `k8s/base/` and `helm/` for reference configurations.

---

## Docker Compose

For local development using Docker Compose, see:

- [Installation → Docker Compose](../installation/docker-compose.md) for complete `.env` example
- `Server and Extractor/docker-compose.extractor.yml`
- `Embedder/docker-compose.embedder.yaml`

---

## Further Reading

- [Architecture](../architecture/index.md) - System design
- [Security](../architecture/security.md) - Security best practices
- [Operations](../operations/monitoring.md) - Monitoring and alerting
- [API Reference](../user-guide/api.md) - API endpoint documentation
