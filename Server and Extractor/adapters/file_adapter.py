"""
T2.2.5: FileSourceAdapter

Handles file upload preparation: uploads to MinIO and prepares extractor payload.
"""

import os
import uuid
from minio import Minio
from minio.error import S3Error
from typing import Optional


class FileAdapter:
    """
    Adapter for file source ingestion.

    Prepares file uploads by storing them in MinIO and generating a payload
    for the extractor service.

    Attributes:
        minio_client: Configured Minio client instance
        bucket_name: Name of the MinIO bucket for video storage
    """

    def __init__(self, minio_client=None, bucket_name: str = None):
        """
        Initialize FileAdapter.

        Args:
            minio_client: Pre-configured Minio client. If None, creates from env.
            bucket_name: Bucket name. If None, uses VIDEO_BUCKET env or 'videos'.
        """
        if minio_client is None:
            # Create Minio client from environment
            endpoint = os.getenv("MINIO_URL", "minio:9000").replace("http://", "").replace("https://", "")
            access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
            secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
            self.minio_client = Minio(
                endpoint=endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=False
            )
        else:
            self.minio_client = minio_client

        self.bucket_name = bucket_name or os.getenv("VIDEO_BUCKET", "videos")

        # Ensure bucket exists (best effort)
        try:
            if not self.minio_client.bucket_exists(self.bucket_name):
                self.minio_client.make_bucket(self.bucket_name)
        except S3Error as e:
            # Log but continue; bucket might be created elsewhere
            print(f"Warning: Could not ensure bucket exists: {e}")

    def prepare(self, file, job_id: str, video_id: str, tenant_id: str) -> dict:
        """
        Prepare file for ingestion: upload to MinIO and generate payload.

        Args:
            file: UploadFile-like object with .filename and .file (file-like)
            job_id: Unique job identifier
            video_id: Video identifier
            tenant_id: Tenant identifier

        Returns:
            Dictionary payload for extractor service.
        """
        if not file or not hasattr(file, 'filename'):
            raise ValueError("Invalid file object")

        filename = file.filename
        # Determine object key: use tenant_id for isolation, then job_id
        object_key = f"{tenant_id}/{job_id}/{filename}"

        # Upload file to MinIO
        try:
            # Upload file object; use file.file which is the actual file-like object
            # Upload read entire content; Minio will handle streaming
            self.minio_client.fput_object(
                bucket_name=self.bucket_name,
                object_name=object_key,
                data=file.file,
                length=-1  # Let Minio determine size by reading
            )
        except S3Error as e:
            raise RuntimeError(f"Failed to upload file to MinIO: {e}")

        # Build payload for extractor
        payload = {
            "job_id": job_id,
            "video_id": video_id,
            "source_type": "file",
            "minio_uri": f"minio://{self.bucket_name}/{object_key}",
            "filename": filename,
            "tenant_id": tenant_id
        }

        return payload
