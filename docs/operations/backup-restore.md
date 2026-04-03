# Backup & Restore

This guide covers procedures for backing up ClipSight data and restoring from backups in case of data loss, corruption, or disaster recovery scenarios.

---

## Overview

ClipSight consists of several data stores that need to be backed up:

1. **PostgreSQL** - Video metadata, user accounts, audit logs
2. **MinIO** - Uploaded videos and extracted frames (object storage)
3. **Milvus** - Vector embeddings and indexes
4. **Redis** - Cache and service registry (ephemeral, optional)

**Backup Strategy**:
- **Full backups** daily (nightly) with point-in-time recovery for PostgreSQL
- **MinIO replication** to secondary location for durability
- **Milvus** - index snapshots + metadata backup (embeddings can be regenerated from frames, but this is slow)
- **Redis** - Not backed up (can be rebuilt from services)

---

## PostgreSQL Backup

### Using pg_dump (recommended for <100GB)

```bash
# Full database backup (plain text)
docker exec clipsight-postgres pg_dump -U postgres clipsight > backup_$(date +%Y%m%d_%H%M%S).sql

# Compressed backup
docker exec clipsight-postgres pg_dump -U postgres clipsight | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz

# Custom format (allows selective restore)
docker exec clipsight-postgres pg_dump -U postgres -Fc clipsight > backup_$(date +%Y%m%d_%H%M%S).dump
```

**Restore**:
```bash
# From plain text
docker exec -i clipsight-postgres psql -U postgres clipsight < backup_20250403.sql

# From custom format
docker exec clipsight-postgres pg_restore -U postgres -d clipsight backup_20250403.dump
```

### Using pg_basebackup (for WAL archiving / PITR)

For point-in-time recovery, configure WAL archiving in `postgresql.conf`:

```
wal_level = replica
archive_mode = on
archive_command = 'cp %p /backup/wal/%f'
```

Then take base backups periodically:

```bash
pg_basebackup -h localhost -U postgres -D /backup/base/$(date +%Y%m%d) -Ft -z -P
```

### Kubernetes Backup

For K8s deployments using StatefulSets:

```bash
# Create a backup job using the postgres-backup image
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: postgres-backup-$(date +%Y%m%d)
  namespace: clipsight
spec:
  template:
    spec:
      containers:
      - name: pg-dump
        image: postgres:15
        command: ["/bin/sh", "-c"]
        args:
          - pg_dump -h postgres -U $POSTGRES_PASSWORD clipsight | gzip > /backup/backup_$(date +%Y%m%d_%H%M%S).sql.gz
        env:
        - name: PGPASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secret
              key: password
        volumeMounts:
        - name: backup-volume
          mountPath: /backup
      restartPolicy: Never
      volumes:
      - name: backup-volume
        persistentVolumeClaim:
          claimName: backup-pvc
EOF
```

Store backups in persistent volume or external object storage (S3, GCS).

---

## MinIO Backup (Object Storage)

MinIO stores videos and frames. Options:

### 1. **Replication to Secondary Site** (Production)

Configure MinIO replication to another MinIO cluster or S3 bucket:

```bash
# Via MinIO client (mc)
mc replicate add source-bucket/ target-bucket/ --remote-bucket target-bucket --service-type minio

# Or set up bucket replication in MinIO console under "Replication"
```

### 2. **mc mirror** (Periodic Backup)

```bash
# Mirror to another local directory or remote storage
mc mirror /local/backup/path minio/clipsight/videos/
mc mirror /local/backup/path minio/clipsight/frames/

# With sync (deletes remote files that no longer exist locally - be careful!)
mc mirror --overwrite --remove /backup minio/clipsight/
```

### 3. **S3 Batch Operations** (Large Scale)

For large deployments, use S3 Batch Copy to copy objects to backup bucket with lifecycle policy for archived storage (S3 Glacier).

### Restore from MinIO Backup

```bash
# Recursively copy back to MinIO
mc mirror /backup minio/clipsight/
```

---

## Milvus Backup

Milvus stores vector embeddings. While embeddings can be regenerated (slow), we recommend backing up:

1. **Index files** (HNSW graphs)
2. **Collection metadata** (via system database)

### Snapshot Collection

```python
from pymilvus import Collection

# Load collection
collection = Collection("video_frames")

# Create snapshot (Milvus 2.4+)
collection.create_snapshot()

# Snapshots stored in Milvus storage, copy them out
# Snapshot location depends on storage config (usually in etcd or metadata storage)
```

### Export to Numpy (Small Collections)

For small deployments, export vectors to disk:

```python
import numpy as np
from pymilvus import Collection

collection = Collection("video_frames")
ids, embeddings = collection.query(expr="", output_fields=["embedding"], limit=1000000)
np.savez("milvus_backup.npz", ids=ids, embeddings=embeddings)
```

**Restore**: Load numpy file and insert via `collection.insert()`.

**Recommendation**: For production, configure Milvus persistence properly (use shared storage with replication). The storage itself (MinIO for objects, etcd for metadata) should be backed up separately.

---

## Full System Backup Script

Here's a comprehensive backup script that can be scheduled via cron:

```bash
#!/bin/bash
# backup.sh - Full ClipSight backup

set -euo pipefail

BACKUP_DIR="/backup/clipsight/$(date +%Y/%m/%d)"
MINIO_BACKUP_DIR="$BACKUP_DIR/minio"
POSTGRES_BACKUP_DIR="$BACKUP_DIR/postgres"
RETENTION_DAYS=30

echo "Starting backup to $BACKUP_DIR"

# Create backup directories
mkdir -p "$MINIO_BACKUP_DIR" "$POSTGRES_BACKUP_DIR"

# 1. PostgreSQL
echo "Backing up PostgreSQL..."
docker exec clipsight-postgres pg_dump -U postgres clipsight | gzip > "$POSTGRES_BACKUP_DIR/clipsight_$(date +%Y%m%d_%H%M%S).sql.gz"

# 2. MinIO (mirror to backup location)
echo "Backing up MinIO..."
mc mirror --overwrite minio/clipsight/ "$MINIO_BACKUP_DIR/"

# 3. Milvus (optional - snapshot metadata)
echo "Backing up Milvus metadata..."
# See Milvus section above - export collection metadata

echo "Backup complete!"
echo ""

# Cleanup old backups (retention policy)
echo "Cleaning up backups older than $RETENTION_DAYS days..."
find /backup/clipsight -type f -mtime +$RETENTION_DAYS -delete
echo "Cleanup complete"

# Upload to cloud storage (optional)
# aws s3 sync "$BACKUP_DIR" s3://clipsight-backups/$(date +%Y%m%d)/
```

**Schedule via cron** (daily at 2am):
```bash
0 2 * * * /path/to/backup.sh >> /var/log/backup.log 2>&1
```

---

## Restore Procedures

### Complete System Restore from Scratch

1. **Provision new infrastructure** (K8s cluster, or Docker host)
2. **Deploy** using standard installation procedures (see [Installation Guide](../installation/docker-compose.md))
3. **Restore PostgreSQL**:
   ```bash
   zcat backup/postgres/clipsight_20250403.sql.gz | docker exec -i clipsight-postgres psql -U postgres clipsight
   ```
4. **Restore MinIO**:
   ```bash
   mc mirror /backup/minio/ minio/clipsight/
   ```
5. **Restore Milvus** (if backup exists):
   ```bash
   # Recreate collections, then insert embeddings from backup
   ```
6. **Restart services** and verify health endpoints

### Partial Restore (Single Video)

To restore a single video's data:

1. Get video record from PostgreSQL:
   ```sql
   SELECT * FROM videos WHERE id = 'vid_abc123';
   ```

2. Restore video file from MinIO backup to MinIO live:
   ```bash
   mc cp /backup/minio/videos/vid_abc123.mp4 minio/clipsight/videos/
   ```

3. Re-extract frames (trigger extractor manually):
   ```bash
   curl -X POST http://localhost:8080/v1/process_video -F "file=@vid_abc123.mp4"
   ```
   Or replicate frames from backup directly.

---

## Disaster Recovery

### Recovery Time Objective (RTO)

- **PostgreSQL**: < 1 hour (from pg_dump), < 15 min (from PITR with streaming replica)
- **MinIO**: < 30 min (from replicated bucket), < 4 hrs (from offline backup)
- **Milvus**: < 2 hrs (index rebuild from embeddings), < 30 min (from snapshot)

### Recovery Point Objective (RPO)

- **PostgreSQL**: < 15 min (WAL streaming replication)
- **MinIO**: < 1 hr (replication lag)
- **Milvus**: < 1 hr

### High Availability Recommendations

To minimize RTO/RPO:

1. **PostgreSQL**: Use streaming replication with automatic failover (Patroni, Stolon)
2. **MinIO**: Deploy as distributed cluster with erasure coding and replication
3. **Milvus**: Deploy in cluster mode with multiple index nodes
4. **Redis**: Use Redis Sentinel for automatic failover
5. **Cross-region replication**: For critical deployments, replicate to secondary region

---

## Testing Backups

**Regularly test your backups!** A backup that hasn't been tested is not a backup.

Recommended monthly:

1. Deploy a fresh test environment (staging)
2. Restore backups to test environment
3. Verify:
   - All videos play correctly
   - Search returns expected results (embeddings intact)
   - User accounts work
   - Audit logs accessible
4. Document the restore process and time taken

Create automated restore tests using CI:

```bash
#!/bin/bash
# test-restore.sh
set -e

# Spin up fresh stack
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" up -d
docker-compose -f "Embedder/docker-compose.embedder.yaml" up -d

sleep 60  # Wait for services

# Restore backups
zcat /backup/latest/postgres.sql.gz | docker exec -i test-postgres psql -U postgres clipsight
mc mirror /backup/latest/minio/ minio/clipsight/

# Smoke test
curl http://localhost:8080/health
curl http://localhost:8080/v1/videos

echo "Restore test PASSED"
```

---

## Backup Monitoring & Alerts

Set up alerts for backup failures:

- **Backup job failed** (cron exit code non-zero)
- **Backup size unusually large/small** (indicates problem)
- **No backup in last 24 hours**
- **Restore test failures** (run weekly)

Example Prometheus alert rule:

```yaml
- alert: BackupFailed
  expr: backup_last_success_timestamp < time() - 86400
  for: 1h
  annotations:
    summary: "No successful backup in 24 hours"
    description: "Check backup cron job and storage"

- alert: BackupTooLarge
  expr: backup_size_bytes > expected_size * 1.5
  for: 2h
  annotations:
    summary: "Backup size excessive"
    description: "Possible runaway log or data growth"
```

---

## Encryption of Backups

Backups may contain sensitive data. Encrypt them:

```bash
# Encrypt with GPG
gpg --encrypt --recipient ops@clipsight.com backup.sql.gz

# Or use age (modern, simpler)
age -r keys.txt -o backup.sql.gz.age backup.sql.gz

# Store encryption keys separately from backups!
```

For cloud storage backups, use server-side encryption (SSE-S3, SSE-KMS).

---

## Further Reading

- [Monitoring](../monitoring.md) - Monitor backup metrics
- [Troubleshooting](../troubleshooting.md) - Common backup issues
- [Security Architecture](../architecture/security.md) - Data protection guidelines
- [PostgreSQL Backup Docs](https://www.postgresql.org/docs/current/backup.html)
- [MinIO Replication](https://min.io/docs/minio/linux/administration/mirror-replication.html)
