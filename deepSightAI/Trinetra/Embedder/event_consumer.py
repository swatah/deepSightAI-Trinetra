"""
T2.2.8: Event-driven embedder consumer

Replaces polling loop with Redis Streams consumer.
"""

import logging
import time
import tempfile
import os
import json
from typing import List
from deepSightAI.Trinetra.Shared.Streaming.Consumer import StreamConsumer
from deepSightAI.Trinetra.Shared.Streaming.Schema import FrameReadyEvent

# We'll import these from embedder.py when running in production
# They initialize heavy model on import
try:
    try:
        from embedder import encode_images, get_minio_client, get_milvus_collection, FRAME_BUCKET, register_with_registry, update_embedder_status
    except ImportError:
        try:
            from deepSightAI.Trinetra.Embedder.embedder import encode_images, get_minio_client, get_milvus_collection, FRAME_BUCKET, register_with_registry, update_embedder_status
        except ImportError:
            from Embedder.embedder import encode_images, get_minio_client, get_milvus_collection, FRAME_BUCKET, register_with_registry, update_embedder_status
    EMBEDDER_MODULE_AVAILABLE = True
except Exception as e:
    # During testing, mocks will be provided
    EMBEDDER_MODULE_AVAILABLE = False
    encode_images = None

logger = logging.getLogger("embedder_consumer")


class EmbedderConsumer:
    """
    Consumes FrameReadyEvents from Redis Streams and processes them.

    Attributes:
        milvus_collection: Milvus collection for embeddings
        minio_client: MinIO client for frame storage
        consumer: StreamConsumer for Redis Streams
    """

    def __init__(self, milvus_collection=None, minio_client=None,
                 redis_url=None, group_name="embedder-group", consumer_id=None):
        """
        Initialize consumer.

        Args:
            milvus_collection: Pre-configured Milvus collection. If None, will call get_milvus_collection().
            minio_client: Pre-configured MinIO client. If None, will call get_minio_client().
            redis_url: Redis connection URL (uses REDIS_URL env if None)
            group_name: Consumer group name
            consumer_id: Unique consumer ID (auto-generated if None)
        """
        # Initialize dependencies
        if milvus_collection is None:
            if not EMBEDDER_MODULE_AVAILABLE:
                raise RuntimeError("embedder module not available and no milvus_collection provided")
            self.milvus_collection = get_milvus_collection()
        else:
            self.milvus_collection = milvus_collection

        if minio_client is None:
            if not EMBEDDER_MODULE_AVAILABLE:
                raise RuntimeError("embedder module not available and no minio_client provided")
            self.minio_client = get_minio_client()
        else:
            self.minio_client = minio_client

        self.consumer = StreamConsumer(
            group_name=group_name,
            consumer_id=consumer_id,
            redis_client=None  # will be created via default
        )
        self.group_name = group_name

    def process_event(self, event: FrameReadyEvent):
        """
        Process a FrameReadyEvent: download frames, encode, insert into Milvus, delete frames.

        Args:
            event: FrameReadyEvent instance
        """
        frame_objects = event.frame_paths
        bucket = event.bucket_name or "frames"

        if not frame_objects:
            logger.info(f"No frames in event for video {event.video_id}")
            return

        # Download frames to temporary files
        local_paths = []
        try:
            # Download all frames
            for obj in frame_objects:
                tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                tmp.close()
                self.minio_client.fget_object(bucket, obj, tmp.name)
                local_paths.append(tmp.name)

            # Encode frames
            feats = encode_images(local_paths)
            if feats.numel() == 0:
                logger.warning(f"No features extracted from event {event.video_id} segment {event.segment_id}")
                # Clean up temp files
                for p in local_paths:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
                return

            # Prepare batch for Milvus
            import uuid
            n = len(feats)
            tenant_id = getattr(event, "tenant_id", None) or "default"
            camera_id = getattr(event, "camera_id", None) or event.video_id
            timestamps = getattr(event, "timestamps", None) or [0.0] * n
            if len(timestamps) != n:
                timestamps = [0.0] * n
            pks = [uuid.uuid4().hex for _ in range(n)]
            video_ids = [event.video_id] * n
            camera_ids = [camera_id] * n
            tenant_ids = [tenant_id] * n
            embeddings = feats.cpu().numpy().tolist()

            try:
                schema_fields = getattr(self.milvus_collection.schema, "fields", [])
            except Exception:
                schema_fields = []

            # Insert into Milvus (flush after each event for simplicity)
            if len(schema_fields) in (3, 4):
                self.milvus_collection.insert([video_ids, frame_objects, embeddings])
            else:
                self.milvus_collection.insert([pks, video_ids, camera_ids, frame_objects, timestamps, embeddings, tenant_ids])
            self.milvus_collection.flush()
            logger.info(f"Inserted {len(video_ids)} embeddings for video {event.video_id}, segment {event.segment_id}")

        except Exception as e:
            logger.exception(f"Error processing event for video {event.video_id}: {e}")
            # Clean up any remaining temp files
            for p in local_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass
            # Optionally, we could ack or not? In TDD we might ack to avoid reprocessing; but for now we raise to let consumer loop handle
            raise

    def run_loop(self, stop_flag=None, max_iterations=None):
        """
        Main event loop: read from "frames" stream and process events.

        Args:
            stop_flag: threading.Event or similar with is_set() to signal stop
            max_iterations: If set, loop at most this many times (for testing)
        """
        stream_name = "frames"
        # Ensure consumer group exists
        self.consumer.ensure_group(stream_name)

        iteration = 0
        while True:
            if stop_flag and stop_flag.is_set():
                logger.info("Stop flag set, exiting loop")
                break
            try:
                # Block for up to 5 seconds waiting for messages
                messages = self.consumer.read(stream_name, count=10, block_ms=5000)
                for msg in messages:
                    try:
                        # Parse event JSON from msg.data['event']
                        event_data = json.loads(msg.data['event'])
                        event = FrameReadyEvent(**event_data)
                        logger.info(f"Processing event: video={event.video_id}, segment={event.segment_id}")
                        self.process_event(event)
                        # Acknowledge after successful processing
                        self.consumer.ack(stream_name, msg.id)
                    except Exception as e:
                        logger.error(f"Failed to process message {msg.id}: {e}")
                        # Could also negative-ack or requeue; for now just continue
                        continue

                iteration += 1
                if max_iterations and iteration >= max_iterations:
                    break

            except Exception as e:
                logger.exception(f"Error in consumer loop: {e}")
                time.sleep(5)

        logger.info("EmbedderConsumer loop ended")
