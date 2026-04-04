#!/usr/bin/env python3
"""
T1.5.7: Audit log retention policy - Archive old audit logs to S3 cold storage

This script runs periodically (via K8s CronJob) to archive audit logs older than
90 days from the hot PostgreSQL database to S3 (Glacier) for long-term retention
(7+ years). After successful archival, logs are deleted from the database.

Environment variables:
- DATABASE_URL: PostgreSQL connection string
- S3_BUCKET: S3 bucket for archival (e.g., deepSightAI-Trinetra-audit-archive)
- S3_PREFIX: Optional prefix within bucket (e.g., audit-logs)
- AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY: AWS credentials (or use IAM role)
- ARCHIVE_AFTER_DAYS: Days after which logs are archived (default: 90)
- CHUNK_SIZE: Number of rows to process at a time (default: 1000)
"""

import os
import sys
import json
import gzip
import logging
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2
from psycopg2.extras import DictCursor
import boto3
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
S3_BUCKET = os.getenv("S3_BUCKET", "deepSightAI-Trinetra-audit-archive")
S3_PREFIX = os.getenv("S3_PREFIX", "audit-logs")
ARCHIVE_AFTER_DAYS = 90  # default, can be overridden by environment
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
RETENTION_YEARS = 7  # Keep archived logs for 7 years (metadata only, actual S3 lifecycle managed separately)

# S3 storage class for cold storage (Glacier or Glacier Deep Archive)
STORAGE_CLASS = os.getenv("S3_STORAGE_CLASS", "GLACIER")  # Options: GLACIER, DEEP_ARCHIVE

# Override ARCHIVE_AFTER_DAYS from environment if provided
if os.getenv("ARCHIVE_AFTER_DAYS"):
    ARCHIVE_AFTER_DAYS = int(os.getenv("ARCHIVE_AFTER_DAYS"))


def connect_db():
    """Connect to PostgreSQL."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False  # We'll manage transaction for safe delete
        logger.info("Connected to PostgreSQL")
        return conn
    except Exception as e:
        logger.error(f"DB connection failed: {e}")
        sys.exit(1)


def connect_s3():
    """Create S3 client."""
    try:
        session = boto3.Session()
        s3 = session.client('s3')
        logger.info("Connected to S3")
        return s3
    except Exception as e:
        logger.error(f"S3 client creation failed: {e}")
        sys.exit(1)


def fetch_old_logs(conn, cutoff_date):
    """Fetch audit logs older than cutoff_date, in chunks."""
    query = """
        SELECT id, tenant_id, user_id, action, resource_type, resource_id, resource_name,
               timestamp, outcome, ip_address, user_agent, request_id, changes, error_message, metadata,
               created_at
        FROM audit_logs
        WHERE timestamp < %s
        ORDER BY timestamp ASC
        FOR UPDATE SKIP LOCKED
    """
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute(query, (cutoff_date,))
    while True:
        rows = cursor.fetchmany(CHUNK_SIZE)
        if not rows:
            break
        yield rows
    cursor.close()


def archive_chunk_to_s3(s3, chunk, chunk_num, total_rows):
    """Upload a chunk of audit logs to S3 as gzipped JSON lines."""
    # Create S3 key with date-based partitioning
    now = datetime.utcnow()
    key = f"{S3_PREFIX}/{now:%Y/%m}/archive_{now:%Y%m%d_%H%M%S}_chunk{chunk_num}.json.gz"
    # Convert rows to JSON lines
    lines = []
    for row in chunk:
        # Convert row to dict
        log_entry = dict(row)
        # Convert date/timestamp objects to ISO strings
        for k, v in log_entry.items():
            if isinstance(v, datetime):
                log_entry[k] = v.isoformat()
        lines.append(json.dumps(log_entry, default=str))
    payload = "\n".join(lines).encode('utf-8')
    # Gzip
    import io
    gz_buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_buffer, mode='wb') as gz:
        gz.write(payload)
    gz_buffer.seek(0)
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=gz_buffer,
            ContentType='application/json',
            ContentEncoding='gzip',
            StorageClass=STORAGE_CLASS
        )
        logger.info(f"Uploaded chunk {chunk_num} ({len(chunk)} rows) to s3://{S3_BUCKET}/{key}")
        return key
    except ClientError as e:
        logger.error(f"Failed to upload chunk {chunk_num} to S3: {e}")
        raise


def delete_archived_logs(conn, ids):
    """Delete archived log entries by ID."""
    if not ids:
        return
    with conn.cursor() as cur:
        # Delete in chunks to avoid huge IN clause
        for i in range(0, len(ids), CHUNK_SIZE):
            batch = ids[i:i+CHUNK_SIZE]
            cur.execute("DELETE FROM audit_logs WHERE id = ANY(%s)", (batch,))
        conn.commit()
        logger.info(f"Deleted {len(ids)} archived logs from database")


def main():
    """Main archiving logic."""
    logger.info("Starting audit log archival...")
    conn = connect_db()
    s3 = connect_s3()
    cutoff_date = datetime.utcnow() - timedelta(days=ARCHIVE_AFTER_DAYS)
    logger.info(f"Archiving logs older than {cutoff_date} (ARCHIVE_AFTER_DAYS={ARCHIVE_AFTER_DAYS})")
    total_archived = 0
    chunk_num = 0
    try:
        for chunk in fetch_old_logs(conn, cutoff_date):
            chunk_num += 1
            if not chunk:
                break
            ids = [row['id'] for row in chunk]
            # Upload to S3
            archive_chunk_to_s3(s3, chunk, chunk_num, total_archived + len(chunk))
            # Delete from DB after successful upload
            delete_archived_logs(conn, ids)
            total_archived += len(chunk)
            logger.info(f"Progress: archived {total_archived} rows")
        logger.info(f"Archival complete: {total_archived} logs archived to cold storage")
        # Optional: verify S3 bucket lifecycle policy exists for 7-year retention (but not checked)
        return 0
    except Exception as e:
        logger.exception("Archival failed")
        conn.rollback()
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
