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


# Schema version tag convention (DM-10)
DSAI_MILVUS_SCHEMA_VERSION = "1.0.0"


def dsai_get_milvus_collection_version(collection: Collection) -> str:
    """Extract schema version tag from Milvus collection description."""
    desc = getattr(collection.schema, "description", "") or ""
    if "[schema_version=" in desc:
        return desc.split("[schema_version=")[1].split("]")[0]
    return "1.0.0"


def dsai_generate_video_object_pk(
    tenant_id: str,
    camera_id: str,
    frame_timestamp: float,
    object_class: str,
    bbox: Optional[list] = None,
    det_idx: Optional[int] = None,
    sequence_number: Optional[int] = None,
    video_id: Optional[str] = None
) -> str:
    """
    Generate deterministic video_object_pk for idempotent upserts (DM-11).

    If det_idx is provided, keys on ordinal position in the frame:
    {tenant_id}:{camera_id}:{timestamp}:{object_class}:{det_idx}
    Otherwise, uses canonical bbox coordinates rounded to 2 decimals.
    """
    import hashlib
    ts_str = f"{float(frame_timestamp):.3f}"
    if det_idx is not None:
        canonical_str = f"{tenant_id}:{camera_id}:{ts_str}:{object_class}:det_{det_idx}"
    else:
        bbox_str = ",".join(f"{float(coord):.2f}" for coord in bbox) if bbox else "0.00,0.00,0.00,0.00"
        canonical_str = f"{tenant_id}:{camera_id}:{ts_str}:{object_class}:{bbox_str}"
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def get_person_collection_name(tenant_id: str) -> str:
    """Generate Milvus collection name for person detections (DM-1)."""
    safe_tenant = tenant_id.replace("-", "_").replace(" ", "_")
    return f"video_objects_person_{safe_tenant}"


def get_vehicle_collection_name(tenant_id: str) -> str:
    """Generate Milvus collection name for vehicle detections (DM-1)."""
    safe_tenant = tenant_id.replace("-", "_").replace(" ", "_")
    return f"video_objects_vehicle_{safe_tenant}"


def ensure_tenant_collection(
    tenant_id: str,
    embedding_dim: int = DEFAULT_EMBEDDING_DIM,
    milvus_host: Optional[str] = None,
    milvus_port: Optional[str] = None
) -> Collection:
    """
    Ensure a tenant's Milvus frame collection exists, creating it if needed.
    """
    host = milvus_host or os.getenv("MILVUS_HOST", "milvus-standalone")
    port = milvus_port or os.getenv("MILVUS_PORT", "19530")

    connect_milvus_with_retry(alias="default", host=host, port=port)

    collection_name = get_collection_name(tenant_id)

    # If collection already exists, just return it
    if utility.has_collection(collection_name):
        return Collection(collection_name)

    # Define schema with camera_id and frame_timestamp (DM-4)
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
        description=f"Video frame embeddings for tenant {tenant_id} [schema_version={DSAI_MILVUS_SCHEMA_VERSION}]",
        enable_dynamic_field=False
    )

    # Create collection
    collection = Collection(
        name=collection_name,
        schema=schema,
        using='default'
    )

    # Create index on embedding for similarity search (DM-2)
    index_params = {
        "metric_type": "COSINE",
        "index_type": "HNSW",
        "params": {"M": 16, "efConstruction": 200}
    }
    collection.create_index(
        field_name="embedding",
        index_params=index_params
    )

    # Create scalar indexes (DM-2, DM-4)
    for scalar_field in ["camera_id", "frame_timestamp", "tenant_id"]:
        try:
            collection.create_index(field_name=scalar_field, index_params={})
        except Exception as e:
            logger.debug(f"Scalar index on {scalar_field} skipped: {e}")

    return collection


def ensure_person_collection(
    tenant_id: str,
    embedding_dim: int = 256,
    milvus_host: Optional[str] = None,
    milvus_port: Optional[str] = None
) -> Collection:
    """
    Ensure a tenant's video_objects_person collection exists (DM-1, DM-2).
    """
    host = milvus_host or os.getenv("MILVUS_HOST", "milvus-standalone")
    port = milvus_port or os.getenv("MILVUS_PORT", "19530")

    connect_milvus_with_retry(alias="default", host=host, port=port)

    collection_name = get_person_collection_name(tenant_id)
    if utility.has_collection(collection_name):
        return Collection(collection_name)

    fields = [
        FieldSchema(name="video_object_pk", dtype=DataType.VARCHAR, max_length=255, is_primary=True),
        FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=255),
        FieldSchema(name="camera_id", dtype=DataType.VARCHAR, max_length=255),
        FieldSchema(name="video_id", dtype=DataType.VARCHAR, max_length=255),
        FieldSchema(name="frame_timestamp", dtype=DataType.DOUBLE),
        FieldSchema(name="frame_path", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="crop_path", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="object_class", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="confidence", dtype=DataType.FLOAT),
        FieldSchema(name="bbox_x1", dtype=DataType.FLOAT),
        FieldSchema(name="bbox_y1", dtype=DataType.FLOAT),
        FieldSchema(name="bbox_x2", dtype=DataType.FLOAT),
        FieldSchema(name="bbox_y2", dtype=DataType.FLOAT),
        FieldSchema(name="attributes_json", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="has_plate_read", dtype=DataType.BOOL),
        FieldSchema(name="plate_number", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=embedding_dim),
    ]

    schema = CollectionSchema(
        fields,
        description=f"Person detections for tenant {tenant_id} [schema_version={DSAI_MILVUS_SCHEMA_VERSION}]",
        enable_dynamic_field=False
    )

    collection = Collection(name=collection_name, schema=schema, using='default')

    # Vector index (DM-2)
    index_params = {
        "metric_type": "COSINE",
        "index_type": "HNSW",
        "params": {"M": 16, "efConstruction": 200}
    }
    collection.create_index(field_name="embedding", index_params=index_params)

    # Scalar indexes (DM-2, DM-4)
    for scalar_field in ["camera_id", "frame_timestamp", "object_class", "has_plate_read", "tenant_id"]:
        try:
            collection.create_index(field_name=scalar_field, index_params={})
        except Exception as e:
            logger.debug(f"Scalar index on {scalar_field} skipped: {e}")

    return collection


def ensure_vehicle_collection(
    tenant_id: str,
    embedding_dim: int = 256,
    milvus_host: Optional[str] = None,
    milvus_port: Optional[str] = None
) -> Collection:
    """
    Ensure a tenant's video_objects_vehicle collection exists (DM-1, DM-2).
    """
    host = milvus_host or os.getenv("MILVUS_HOST", "milvus-standalone")
    port = milvus_port or os.getenv("MILVUS_PORT", "19530")

    connect_milvus_with_retry(alias="default", host=host, port=port)

    collection_name = get_vehicle_collection_name(tenant_id)
    if utility.has_collection(collection_name):
        return Collection(collection_name)

    fields = [
        FieldSchema(name="video_object_pk", dtype=DataType.VARCHAR, max_length=255, is_primary=True),
        FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=255),
        FieldSchema(name="camera_id", dtype=DataType.VARCHAR, max_length=255),
        FieldSchema(name="video_id", dtype=DataType.VARCHAR, max_length=255),
        FieldSchema(name="frame_timestamp", dtype=DataType.DOUBLE),
        FieldSchema(name="frame_path", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="crop_path", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="object_class", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="confidence", dtype=DataType.FLOAT),
        FieldSchema(name="color", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="vehicle_type", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="has_plate_read", dtype=DataType.BOOL),
        FieldSchema(name="plate_number", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="plate_candidate_id", dtype=DataType.VARCHAR, max_length=255),
        FieldSchema(name="bbox_x1", dtype=DataType.FLOAT),
        FieldSchema(name="bbox_y1", dtype=DataType.FLOAT),
        FieldSchema(name="bbox_x2", dtype=DataType.FLOAT),
        FieldSchema(name="bbox_y2", dtype=DataType.FLOAT),
        FieldSchema(name="attributes_json", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=embedding_dim),
    ]

    schema = CollectionSchema(
        fields,
        description=f"Vehicle detections for tenant {tenant_id} [schema_version={DSAI_MILVUS_SCHEMA_VERSION}]",
        enable_dynamic_field=False
    )

    collection = Collection(name=collection_name, schema=schema, using='default')

    # Vector index (DM-2)
    index_params = {
        "metric_type": "COSINE",
        "index_type": "HNSW",
        "params": {"M": 16, "efConstruction": 200}
    }
    collection.create_index(field_name="embedding", index_params=index_params)

    # Scalar indexes (DM-2, DM-4, VP-21)
    for scalar_field in ["camera_id", "frame_timestamp", "object_class", "color", "vehicle_type", "has_plate_read", "plate_candidate_id", "tenant_id"]:
        try:
            collection.create_index(field_name=scalar_field, index_params={})
        except Exception as e:
            logger.debug(f"Scalar index on {scalar_field} skipped: {e}")

    return collection


def drop_tenant_collection(tenant_id: str) -> bool:
    """Drop a tenant's Milvus collection."""
    collection_name = get_collection_name(tenant_id)
    if utility.has_collection(collection_name):
        utility.drop_collection(collection_name)
        return True
    return False


def drop_person_collection(tenant_id: str) -> bool:
    """Drop a tenant's person Milvus collection."""
    collection_name = get_person_collection_name(tenant_id)
    if utility.has_collection(collection_name):
        utility.drop_collection(collection_name)
        return True
    return False


def drop_vehicle_collection(tenant_id: str) -> bool:
    """Drop a tenant's vehicle Milvus collection."""
    collection_name = get_vehicle_collection_name(tenant_id)
    if utility.has_collection(collection_name):
        utility.drop_collection(collection_name)
        return True
    return False


# Aliases with dsai_ prefix
dsai_get_collection_name = get_collection_name
dsai_get_person_collection_name = get_person_collection_name
dsai_get_vehicle_collection_name = get_vehicle_collection_name
dsai_ensure_tenant_collection = ensure_tenant_collection
dsai_ensure_person_collection = ensure_person_collection
dsai_ensure_vehicle_collection = ensure_vehicle_collection
dsai_drop_tenant_collection = drop_tenant_collection
dsai_drop_person_collection = drop_person_collection
dsai_drop_vehicle_collection = drop_vehicle_collection
