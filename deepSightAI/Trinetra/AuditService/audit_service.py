"""
AuditService - Immutable audit logging for deepSightAI Trinetra
T1.5.2: Create AuditService (FastAPI)
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import psycopg2
from psycopg2.extras import execute_values
from kafka import KafkaProducer
import jsonschema

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("audit_service")

# Load audit log schema
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "design", "audit-schema.json")
with open(SCHEMA_PATH) as f:
    AUDIT_SCHEMA = json.load(f)

app = FastAPI(title="AuditService", description="Immutable audit logging service")

# Database connection (from env)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_AUDIT_TOPIC = os.getenv("KAFKA_AUDIT_TOPIC", "audit-logs")


class AuditService:
    """Core audit service logic."""

    def __init__(self, db_url=None, kafka_servers=None):
        self.db_url = db_url or DATABASE_URL
        self.kafka_servers = kafka_servers or KAFKA_BOOTSTRAP_SERVERS
        self.conn = None
        self.kafka_producer = None
        self.connect_db()
        self.connect_kafka()

    def connect_db(self):
        """Connect to PostgreSQL."""
        try:
            self.conn = psycopg2.connect(self.db_url)
            self.conn.autocommit = True
            logger.info("Connected to PostgreSQL")
        except Exception as e:
            logger.error(f"DB connection failed: {e}")
            self.conn = None

    def connect_kafka(self):
        """Connect to Kafka."""
        try:
            self.kafka_producer = KafkaProducer(
                bootstrap_servers=self.kafka_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            logger.info("Connected to Kafka")
        except Exception as e:
            logger.warning(f"Kafka connection failed: {e}")
            self.kafka_producer = None

    def validate_audit_log(self, log: Dict[str, Any]):
        """Validate audit log against JSON schema."""
        # Basic required fields validation (lightweight)
        required = ["tenant_id", "user_id", "action", "resource", "timestamp", "outcome"]
        for field in required:
            if field not in log:
                raise ValueError(f"Missing required field: {field}")
        # Validate resource structure
        res = log.get("resource")
        if not isinstance(res, dict):
            raise ValueError("resource must be an object")
        if "type" not in res or "id" not in res:
            raise ValueError("resource must have type and id")
        # Full JSON Schema validation (if jsonschema is available)
        try:
            jsonschema.validate(instance=log, schema=AUDIT_SCHEMA)
        except Exception as e:
            logger.error(f"Audit log validation failed: {e}")
            raise ValueError(f"Invalid audit log: {e}")

    def store(self, log: Dict[str, Any]):
        """
        Store audit log in PostgreSQL (immutable append-only table).
        In production, the table should be WORM (Write Once Read Many).
        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        query = """
            INSERT INTO audit_logs
            (tenant_id, user_id, action, resource_type, resource_id, resource_name, timestamp, outcome, ip_address, user_agent, request_id, changes, error_message, metadata)
            VALUES %s
            ON CONFLICT DO NOTHING
        """
        # Extract fields
        tenant_id = log["tenant_id"]
        user_id = log["user_id"]
        action = log["action"]
        resource = log["resource"]
        resource_type = resource.get("type")
        resource_id = resource.get("id")
        resource_name = resource.get("name")
        timestamp = log["timestamp"]
        outcome = log["outcome"]
        ip_address = log.get("ip_address")
        user_agent = log.get("user_agent")
        request_id = log.get("request_id")
        changes = json.dumps(log.get("changes", [])) if log.get("changes") else None
        error_message = log.get("error_message")
        metadata = json.dumps(log.get("metadata", {})) if log.get("metadata") else None

        values = [(
            tenant_id, user_id, action, resource_type, resource_id, resource_name,
            timestamp, outcome, ip_address, user_agent, request_id, changes,
            error_message, metadata
        )]

        with self.conn.cursor() as cur:
            execute_values(cur, query, values)

        logger.info(f"Stored audit log: {action} on {resource_type}")

    def produce_to_kafka(self, log: Dict[str, Any]):
        """Produce audit log to Kafka topic."""
        if not self.kafka_producer:
            logger.warning("Kafka producer not available, skipping")
            return
        try:
            self.kafka_producer.send(KAFKA_AUDIT_TOPIC, log)
            self.kafka_producer.flush()
            logger.info(f"Produced audit log to Kafka topic {KAFKA_AUDIT_TOPIC}")
        except Exception as e:
            logger.error(f"Failed to produce to Kafka: {e}")

    def handle_log(self, log: Dict[str, Any]):
        """Validate, store, and forward an audit log."""
        self.validate_audit_log(log)
        self.store(log)
        self.produce_to_kafka(log)


# Initialize service
audit_service = AuditService()


@app.post("/audit")
async def receive_audit_log(log: Dict[str, Any]):
    """Receive a single audit log entry."""
    try:
        audit_service.handle_log(log)
        return {"status": "accepted", "message": "Audit log stored"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error processing audit log")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/audit/batch")
async def receive_audit_batch(logs: List[Dict[str, Any]]):
    """Receive multiple audit log entries."""
    results = []
    for log in logs:
        try:
            audit_service.handle_log(log)
            results.append({"status": "accepted"})
        except Exception as e:
            results.append({"status": "rejected", "error": str(e)})
    return {"batch": results}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "audit"}


# CLI entrypoint for running the service
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
