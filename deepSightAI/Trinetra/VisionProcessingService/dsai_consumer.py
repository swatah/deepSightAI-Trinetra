"""
Vision Processing Service Consumer (VP-12, VP-14, VP-20, VP-22, VP-23).

Consumes FrameReadyEvents from Redis Streams on consumer group 'vision-processing-group',
runs detection plugins, enforces crop retention, writes to Milvus, and publishes
ObjectDetectedEvents.
"""

import os
import sys
import json
import time
import tempfile
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import numpy as np

from deepSightAI.Trinetra.Shared.LoggingSetup import dsai_get_logger
from deepSightAI.Trinetra.Shared.Errors import ModelInferenceError, MilvusError, StorageError
from deepSightAI.Trinetra.Shared.Streaming.Consumer import StreamConsumer
from deepSightAI.Trinetra.Shared.Streaming.Producer import StreamProducer
from deepSightAI.Trinetra.Shared.Streaming.Schema import FrameReadyEvent, ObjectDetectedEvent
from deepSightAI.Trinetra.Shared.Milvus import (
    ensure_person_collection,
    ensure_vehicle_collection,
    dsai_generate_video_object_pk,
)
from deepSightAI.Trinetra.Shared.Retention import dsai_crop_policy
from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_plugin_loader import PluginLoader
from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_pp_human import PPHumanPlugin
from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_pp_vehicle import PPVehiclePlugin
from deepSightAI.Trinetra.VisionProcessingService.plugins.dsai_vehicle_attributes import PPVehicleAttributePlugin

logger = dsai_get_logger("deepSightAI.Trinetra.VisionProcessingService.Consumer")


class VisionProcessingConsumer:
    """
    Consumer running within consumer group 'vision-processing-group' (VP-12).
    """

    def __init__(
        self,
        dsai_minio_client=None,
        dsai_producer=None,
        dsai_config: Optional[Dict[str, Any]] = None,
        dsai_group_name: str = "vision-processing-group",
        dsai_consumer_id: Optional[str] = None,
        dsai_stream_name: Optional[str] = None,
    ):
        self.dsai_minio_client = dsai_minio_client
        self.dsai_producer = dsai_producer or StreamProducer()
        self.dsai_config = dsai_config or {}
        self.dsai_group_name = dsai_group_name
        self.dsai_consumer_id = dsai_consumer_id or f"vps-{os.getpid()}"
        self.dsai_stream_name = dsai_stream_name or os.getenv("FRAME_STREAM", os.getenv("FRAME_EVENTS_STREAM", "frames"))
        self.dsai_dlq_stream = os.getenv("DLQ_STREAM", "events:dlq")
        self.message_retry_counts: Dict[str, int] = {}
        self.max_message_retries = int(os.getenv("MAX_MESSAGE_RETRIES", "3"))

        self.consumer = StreamConsumer(
            group_name=self.dsai_group_name,
            consumer_id=self.dsai_consumer_id,
            redis_client=None
        )

        # Initialize plugin loader
        self.plugin_loader = PluginLoader(self.dsai_config)
        # Register built-in detection plugins
        self._dsai_attribute_plugin = PPVehicleAttributePlugin(self.dsai_config.get("plugins", {}).get("pp_vehicle_attributes", {}).get("config", {}))

    def dsai_process_event(self, dsai_event: FrameReadyEvent) -> List[ObjectDetectedEvent]:
        """
        Process a single FrameReadyEvent (VP-20, VP-22, VP-23).

        1. Download frames
        2. Run person / vehicle detection plugins
        3. Enforce crop storage policy (DM-8)
        4. Write detections to tenant Milvus collections
        5. Publish ObjectDetectedEvent to 'events:object_detected'
        """
        dsai_tenant_id = dsai_event.tenant_id or "default"
        dsai_camera_id = dsai_event.camera_id or dsai_event.video_id
        dsai_video_id = dsai_event.video_id
        dsai_bucket = dsai_event.bucket_name or "frames"
        dsai_emitted_events: List[ObjectDetectedEvent] = []

        dsai_tenant_sector = self.dsai_config.get("tenants", {}).get(dsai_tenant_id, {}).get("sector", "default")
        dsai_tenant_config = self.dsai_config.get("tenants", {}).get(dsai_tenant_id, {})

        # Load active plugins for this sector, tenant, and camera (VP-24, VP-25)
        dsai_active_plugins = self.plugin_loader.load_plugins(
            tenant_sector=dsai_tenant_sector,
            tenant_id=dsai_tenant_id,
            camera_id=dsai_camera_id
        )

        # If no plugins dynamically discovered, ensure default plugins
        if not dsai_active_plugins:
            dsai_active_plugins = [
                PPHumanPlugin(self.dsai_config.get("plugins", {}).get("pp_human", {}).get("config", {})),
                PPVehiclePlugin(self.dsai_config.get("plugins", {}).get("pp_vehicle", {}).get("config", {})),
            ]

        # Process each frame path
        for dsai_idx, dsai_frame_path in enumerate(dsai_event.frame_paths):
            dsai_timestamp = dsai_event.timestamps[dsai_idx] if dsai_idx < len(dsai_event.timestamps) else 0.0

            # Mock or download frame
            dsai_local_frame = None
            if self.dsai_minio_client and hasattr(self.dsai_minio_client, "fget_object"):
                try:
                    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                    tmp.close()
                    self.dsai_minio_client.fget_object(dsai_bucket, dsai_frame_path, tmp.name)
                    dsai_local_frame = tmp.name
                except Exception as dl_e:
                    logger.warning(f"Could not download frame {dsai_frame_path}: {dl_e}")

            dsai_frame_input = dsai_local_frame or dsai_frame_path

            # Run active detection plugins (VP-15, VP-16)
            dsai_detections = []
            for dsai_plugin in dsai_active_plugins:
                try:
                    dsai_plugin_dets = dsai_plugin.detect(dsai_frame_input)
                    if dsai_plugin_dets:
                        dsai_detections.extend(dsai_plugin_dets)
                except Exception as det_e:
                    logger.warning(f"Plugin {getattr(dsai_plugin, 'name', 'unknown')} detection error: {det_e}")

            try:
                for dsai_det_idx, dsai_det in enumerate(dsai_detections):
                    dsai_class = dsai_det.get("object_class") or dsai_det.get("label", "unknown")
                    dsai_conf = float(dsai_det.get("confidence", 0.0))
                    dsai_bbox = dsai_det.get("bbox", [0.0, 0.0, 0.0, 0.0])

                    # Generate deterministic video_object_pk (DM-11, ordinal keying)
                    dsai_pk = dsai_generate_video_object_pk(
                        tenant_id=dsai_tenant_id,
                        camera_id=dsai_camera_id,
                        frame_timestamp=dsai_timestamp,
                        object_class=dsai_class,
                        bbox=dsai_bbox,
                        det_idx=dsai_det_idx,
                        video_id=dsai_video_id
                    )

                    # Enforce crop storage policy (DM-8)
                    dsai_persist_crop = dsai_crop_policy.should_persist_crop(
                        object_class=dsai_class,
                        confidence=dsai_conf,
                        tenant_config=dsai_tenant_config
                    )

                    dsai_crop_path = ""
                    dsai_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    if dsai_persist_crop:
                        dsai_crop_key = f"{dsai_tenant_id}/{dsai_camera_id}/{dsai_date_str}/crops/{dsai_pk}.jpg"
                        if self.dsai_minio_client and hasattr(self.dsai_minio_client, "fput_object") and dsai_local_frame:
                            try:
                                self.dsai_minio_client.fput_object(dsai_bucket, dsai_crop_key, dsai_local_frame)
                                dsai_crop_path = dsai_crop_key
                            except Exception as up_e:
                                logger.warning(f"Crop upload failed: {up_e}")
                        else:
                            dsai_crop_path = dsai_crop_key

                    # Extract embedding (dim=256, FP32)
                    dsai_raw_emb = dsai_det.get("embedding")
                    if dsai_raw_emb is None:
                        dsai_raw_emb = (np.ones(256, dtype=np.float32) / np.sqrt(256)).tolist()
                    elif isinstance(dsai_raw_emb, np.ndarray):
                        dsai_raw_emb = dsai_raw_emb.tolist()

                    # Write to tenant-isolated Milvus collection (DM-1, DM-2, VP-20)
                    if dsai_class == "person":
                        dsai_coll = ensure_person_collection(dsai_tenant_id, embedding_dim=len(dsai_raw_emb))
                        try:
                            dsai_coll.insert([
                                [dsai_pk],
                                [dsai_tenant_id],
                                [dsai_camera_id],
                                [dsai_video_id],
                                [float(dsai_timestamp)],
                                [dsai_frame_path],
                                [dsai_crop_path],
                                [dsai_class],
                                [float(dsai_conf)],
                                [float(dsai_bbox[0])],
                                [float(dsai_bbox[1])],
                                [float(dsai_bbox[2])],
                                [float(dsai_bbox[3])],
                                [json.dumps(dsai_det.get("attributes", {}))],
                                [False],
                                [""],
                                [dsai_raw_emb],
                            ])
                            dsai_coll.flush()
                        except Exception as mv_e:
                            logger.error(f"Milvus insert failed (person): {mv_e}")
                            raise MilvusError(f"Milvus insert failed (person): {mv_e}")

                        # Create emitted event
                        dsai_obj_event = ObjectDetectedEvent(
                            video_object_pk=dsai_pk,
                            tenant_id=dsai_tenant_id,
                            camera_id=dsai_camera_id,
                            video_id=dsai_video_id,
                            frame_timestamp=float(dsai_timestamp),
                            frame_path=dsai_frame_path,
                            crop_path=dsai_crop_path if dsai_crop_path else None,
                            object_class=dsai_class,
                            confidence=dsai_conf,
                            bbox=dsai_bbox,
                            attributes=dsai_det.get("attributes", {}),
                            has_plate_read=False,
                            plate_number=None,
                            reid_embedding=dsai_raw_emb,
                        )
                        dsai_emitted_events.append(dsai_obj_event)

                    elif dsai_class == "vehicle":
                        # Extract vehicle attributes (VP-17)
                        dsai_attr = self._dsai_attribute_plugin.extract_attributes(dsai_det)
                        dsai_color = dsai_det.get("color") or dsai_attr.get("color", "red")
                        dsai_type = dsai_det.get("vehicle_type") or dsai_attr.get("vehicle_type", "sedan")
                        dsai_has_plate = bool(dsai_det.get("has_plate_read", False)) or bool(dsai_det.get("plate_number"))
                        dsai_plate = dsai_det.get("plate_number")
                        dsai_plate_candidate_id = dsai_det.get("plate_candidate_id") or (f"plate_cand_{dsai_pk}" if dsai_has_plate else "")

                        # On vehicle detection with plate: insert plate_reads with unique constraint on video_object_pk (VP-21)
                        if dsai_has_plate and dsai_plate:
                            try:
                                from deepSightAI.Trinetra.Shared.Repositories.PlateRepository import PlateRepository
                                dsai_plate_repo = PlateRepository(dsai_tenant_id)
                                dsai_plate_repo.create(
                                    video_object_pk=dsai_pk,
                                    video_id=dsai_video_id,
                                    camera_id=dsai_camera_id,
                                    frame_timestamp=float(dsai_timestamp),
                                    plate_text_raw=str(dsai_det.get("plate_text_raw") or dsai_plate),
                                    plate_text_norm=str(dsai_plate),
                                    ocr_confidence=float(dsai_det.get("plate_confidence", dsai_conf)),
                                    ocr_engine=str(dsai_det.get("ocr_engine", "pp-ocrv3")),
                                    crop_path=dsai_crop_path or None
                                )
                            except Exception as dsai_pr_err:
                                logger.error(f"Plate read persistence failed for {dsai_pk}: {dsai_pr_err}")
                                raise StorageError(f"Plate read persistence failed for {dsai_pk}: {dsai_pr_err}")

                        dsai_coll = ensure_vehicle_collection(dsai_tenant_id, embedding_dim=len(dsai_raw_emb))
                        try:
                            dsai_coll.insert([
                                [dsai_pk],
                                [dsai_tenant_id],
                                [dsai_camera_id],
                                [dsai_video_id],
                                [float(dsai_timestamp)],
                                [dsai_frame_path],
                                [dsai_crop_path],
                                [dsai_class],
                                [float(dsai_conf)],
                                [dsai_color],
                                [dsai_type],
                                [dsai_has_plate],
                                [dsai_plate or ""],
                                [dsai_plate_candidate_id],
                                [float(dsai_bbox[0])],
                                [float(dsai_bbox[1])],
                                [float(dsai_bbox[2])],
                                [float(dsai_bbox[3])],
                                [json.dumps({"color": dsai_color, "vehicle_type": dsai_type})],
                                [dsai_raw_emb],
                            ])
                            dsai_coll.flush()
                        except Exception as mv_e:
                            logger.error(f"Milvus insert failed (vehicle): {mv_e}")
                            raise MilvusError(f"Milvus insert failed (vehicle): {mv_e}")

                        dsai_obj_event = ObjectDetectedEvent(
                            video_object_pk=dsai_pk,
                            tenant_id=dsai_tenant_id,
                            camera_id=dsai_camera_id,
                            video_id=dsai_video_id,
                            frame_timestamp=float(dsai_timestamp),
                            frame_path=dsai_frame_path,
                            crop_path=dsai_crop_path if dsai_crop_path else None,
                            object_class=dsai_class,
                            confidence=dsai_conf,
                            bbox=dsai_bbox,
                            attributes={"color": dsai_color, "vehicle_type": dsai_type},
                            has_plate_read=dsai_has_plate,
                            plate_number=dsai_plate,
                            plate_candidate_id=dsai_plate_candidate_id if dsai_has_plate else None,
                            reid_embedding=dsai_raw_emb,
                        )
                        dsai_emitted_events.append(dsai_obj_event)

                    elif dsai_class == "plate":
                        dsai_plate = dsai_det.get("plate_number")
                        if dsai_plate:
                            try:
                                from deepSightAI.Trinetra.Shared.Repositories.PlateRepository import PlateRepository
                                dsai_plate_repo = PlateRepository(dsai_tenant_id)
                                dsai_plate_repo.create(
                                    video_object_pk=dsai_pk,
                                    video_id=dsai_video_id,
                                    camera_id=dsai_camera_id,
                                    frame_timestamp=float(dsai_timestamp),
                                    plate_text_raw=str(dsai_det.get("plate_text_raw") or dsai_plate),
                                    plate_text_norm=str(dsai_plate),
                                    ocr_confidence=float(dsai_det.get("confidence", dsai_conf)),
                                    ocr_engine=str(dsai_det.get("ocr_engine", "pp-ocrv3")),
                                    crop_path=dsai_crop_path or None
                                )
                            except Exception as dsai_pr_err:
                                logger.error(f"Standalone plate read persistence failed for {dsai_pk}: {dsai_pr_err}")
                                raise StorageError(f"Standalone plate read persistence failed for {dsai_pk}: {dsai_pr_err}")

                        dsai_obj_event = ObjectDetectedEvent(
                            video_object_pk=dsai_pk,
                            tenant_id=dsai_tenant_id,
                            camera_id=dsai_camera_id,
                            video_id=dsai_video_id,
                            frame_timestamp=float(dsai_timestamp),
                            frame_path=dsai_frame_path,
                            crop_path=dsai_crop_path if dsai_crop_path else None,
                            object_class=dsai_class,
                            confidence=dsai_conf,
                            bbox=dsai_bbox,
                            attributes={"plate_number": dsai_plate},
                            has_plate_read=True,
                            plate_number=dsai_plate,
                            plate_candidate_id=f"plate_{dsai_pk}",
                        )
                        dsai_emitted_events.append(dsai_obj_event)

                    # Publish ObjectDetectedEvent to events:object_detected (VP-22)
                    if self.dsai_producer is not None:
                        try:
                            self.dsai_producer.publish("events:object_detected", dsai_obj_event)
                            logger.info(f"Published ObjectDetectedEvent for pk={dsai_pk} ({dsai_class})")
                        except Exception as pub_e:
                            logger.error(f"Failed to publish ObjectDetectedEvent: {pub_e}")
                            raise StreamingError(f"Failed to publish ObjectDetectedEvent: {pub_e}")

            finally:
                if dsai_local_frame and os.path.exists(dsai_local_frame):
                    try:
                        os.unlink(dsai_local_frame)
                    except OSError:
                        pass

        return dsai_emitted_events

    def dsai_run_loop(self, dsai_stop_flag=None, dsai_max_iterations: Optional[int] = None):
        """
        Main consumer event loop (VP-12, VP-23).
        """
        self.consumer.ensure_group(self.dsai_stream_name)
        logger.info(f"VPS Consumer running on stream '{self.dsai_stream_name}' in group '{self.dsai_group_name}'")

        iteration = 0
        while True:
            if dsai_stop_flag and dsai_stop_flag.is_set():
                break

            try:
                messages = self.consumer.read(self.dsai_stream_name, count=10, block_ms=2000)
                for msg in messages:
                    try:
                        event_data = json.loads(msg.data.get("event", "{}"))
                        frame_event = FrameReadyEvent(**event_data)
                        logger.info(f"VPS received FrameReadyEvent: video={frame_event.video_id}, segment={frame_event.segment_id}")

                        # Process detections durably
                        self.dsai_process_event(frame_event)

                        # Acknowledge source FrameReadyEvent ONLY after durable success (VP-23)
                        self.consumer.ack(self.dsai_stream_name, msg.id)
                        self.message_retry_counts.pop(msg.id, None)
                        logger.debug(f"Acknowledged frame event {msg.id}")
                    except Exception as proc_e:
                        self.message_retry_counts[msg.id] = self.message_retry_counts.get(msg.id, 0) + 1
                        attempts = self.message_retry_counts[msg.id]
                        logger.error(f"Error processing frame event {msg.id} (attempt {attempts}/{self.max_message_retries}): {proc_e}")
                        if attempts >= self.max_message_retries:
                            logger.error(f"Event {msg.id} exceeded max retries, forwarding to DLQ '{self.dsai_dlq_stream}'")
                            if self.dsai_producer is not None:
                                try:
                                    self.dsai_producer.publish(self.dsai_dlq_stream, {
                                        "source_stream": self.dsai_stream_name,
                                        "message_id": msg.id,
                                        "event": msg.data.get("event"),
                                        "error": str(proc_e),
                                    })
                                except Exception as dlq_e:
                                    logger.error(f"Failed publishing to DLQ: {dlq_e}")
                            self.consumer.ack(self.dsai_stream_name, msg.id)
                            self.message_retry_counts.pop(msg.id, None)
                        continue

                iteration += 1
                if dsai_max_iterations and iteration >= dsai_max_iterations:
                    break

            except Exception as loop_e:
                logger.error(f"Error in VPS consumer loop: {loop_e}")
                time.sleep(1)

    process_event = dsai_process_event
    run_loop = dsai_run_loop
