"""
T1.3.5: Milvus tenant isolation

Provides utilities to ensure Milvus data is tenant-isolated.
Strategy: Each tenant gets their own collection named `video_frames_<tenant_id>`.

Alternative (not chosen): single collection with `tenant_id` field and filter.
"""

import os
from typing import Optional
from pymilvus import (
    connections,
    Collection,
    FieldSchema,
    CollectionSchema,
    DataType,
    utility
)


# Default embedding dimension for CLIP ViT-B-32
DEFAULT_EMBEDDING_DIM = 512


def get_collection_name(tenant_id: str) -> str:
    """
    Generate Milvus collection name for a tenant.

    Args:
        tenant_id: Tenant identifier

    Returns:
        Collection name: "video_frames_<tenant_id>"
    """
    # Sanitize tenant_id for use in collection name
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

    Note:
        Collection schema:
        - pk: VARCHAR(primary key) - frame identifier
        - video_id: VARCHAR - source video ID
        - frame_path: VARCHAR - MinIO object key (tenant-prefixed)
        - embedding: FLOAT_VECTOR[embedding_dim] - CLIP embedding
        - tenant_id: VARCHAR (redundant but for safety)
    """
    host = milvus_host or os.getenv("MILVUS_HOST", "milvus-standalone")
    port = milvus_port or os.getenv("MILVUS_PORT", "19530")

    # Connect to Milvus (reuses connection if already connected)
    connections.connect(
        alias="default",
        host=host,
        port=port
    )

    collection_name = get_collection_name(tenant_id)

    # If collection already exists, just return it
    if utility.has_collection(collection_name):
        return Collection(collection_name)

    # Define schema
    fields = [
        FieldSchema(name="pk", dtype=DataType.VARCHAR, max_length=255, is_primary=True),
        FieldSchema(name="video_id", dtype=DataType.VARCHAR, max_length=255),
        FieldSchema(name="frame_path", dtype=DataType.VARCHAR, max_length=1024),
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
