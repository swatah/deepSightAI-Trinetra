"""
T1.3.5: Milvus tenant isolation under deepSightAI.Trinetra.Shared.Milvus.

Provides utilities to ensure Milvus data is tenant-isolated.
Strategy: Each tenant gets their own collection named `video_frames_<tenant_id>`.
"""

import os
import sys
from typing import Optional
from pymilvus import (
    connections,
    Collection,
    FieldSchema,
    CollectionSchema,
    DataType,
    utility
)

import time
import logging

logger = logging.getLogger("deepSightAI.Trinetra.Shared.Milvus")

# Default embedding dimension for CLIP ViT-B-32
DEFAULT_EMBEDDING_DIM = 512


def connect_milvus_with_retry(
    alias: str = "default",
    host: Optional[str] = None,
    port: Optional[str] = None,
    max_retries: Optional[int] = None,
    initial_delay: Optional[float] = None,
    backoff_factor: float = 2.0
):
    """Connect to Milvus with exponential backoff retry."""
    host = host or os.getenv("MILVUS_HOST", "milvus-standalone")
    port = port or os.getenv("MILVUS_PORT", "19530")

    if max_retries is None:
        max_retries = int(os.getenv("MILVUS_MAX_RETRIES", "1" if "pytest" in sys.modules else "5"))
    if initial_delay is None:
        initial_delay = float(os.getenv("MILVUS_INITIAL_DELAY", "0.05" if "pytest" in sys.modules else "1.0"))

    if connections.has_connection(alias):
        return

    delay = initial_delay
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            connections.connect(alias=alias, host=host, port=port)
            logger.info(f"Connected to Milvus at {host}:{port} (alias={alias})")
            return
        except Exception as e:
            last_err = e
            logger.warning(
                f"Failed to connect to Milvus at {host}:{port} (attempt {attempt}/{max_retries}): {e}"
            )
            if attempt < max_retries:
                time.sleep(delay)
                delay *= backoff_factor

    raise RuntimeError(f"Could not connect to Milvus after {max_retries} attempts: {last_err}")


def get_collection_name(tenant_id: str) -> str:
    """
    Generate Milvus collection name for a tenant.

    Args:
        tenant_id: Tenant identifier

    Returns:
        Collection name: "video_frames_<tenant_id>"
    """
    safe_tenant = tenant_id.replace("-", "_").replace(" ", "_")
    return f"video_frames_{safe_tenant}"


def ensure_tenant_collection(
    tenant_id: str,
    embedding_dim: int = DEFAULT_EMBEDDING_DIM,
    milvus_host: Optional[str] = None,
    milvus_port: Optional[str] = None
) -> Collection:
    """
    Ensure a tenant's Milvus collection exists, creating it if needed.

    Args:
        tenant_id: Tenant identifier
        embedding_dim: Embedding vector dimension (default 512)
        milvus_host: Milvus host (default from env)
        milvus_port: Milvus port (default from env)

    Returns:
        The Milvus Collection instance.
    """
    host = milvus_host or os.getenv("MILVUS_HOST", "milvus-standalone")
    port = milvus_port or os.getenv("MILVUS_PORT", "19530")

    connect_milvus_with_retry(alias="default", host=host, port=port)

    collection_name = get_collection_name(tenant_id)

    # If collection already exists, just return it
    if utility.has_collection(collection_name):
        return Collection(collection_name)

    # Define schema
    fields = [
        FieldSchema(name="pk", dtype=DataType.VARCHAR, max_length=255, is_primary=True),
        FieldSchema(name="video_id", dtype=DataType.VARCHAR, max_length=255),
        FieldSchema(name="camera_id", dtype=DataType.VARCHAR, max_length=255),
        FieldSchema(name="frame_path", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="frame_timestamp", dtype=DataType.DOUBLE),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=embedding_dim),
        FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=255),
    ]
    schema = CollectionSchema(
        fields,
        description=f"Video frame embeddings for tenant {tenant_id}",
        enable_dynamic_field=False
    )

    # Create collection
    collection = Collection(
        name=collection_name,
        schema=schema,
        using='default'
    )

    # Create index on embedding for similarity search
    index_params = {
        "metric_type": "COSINE",
        "index_type": "HNSW",
        "params": {"M": 16, "efConstruction": 200}
    }
    collection.create_index(
        field_name="embedding",
        index_params=index_params
    )

    return collection


def drop_tenant_collection(tenant_id: str) -> bool:
    """
    Drop a tenant's Milvus collection.

    Args:
        tenant_id: Tenant identifier

    Returns:
        True if dropped, False if didn't exist.
    """
    collection_name = get_collection_name(tenant_id)
    if utility.has_collection(collection_name):
        utility.drop_collection(collection_name)
        return True
    return False
