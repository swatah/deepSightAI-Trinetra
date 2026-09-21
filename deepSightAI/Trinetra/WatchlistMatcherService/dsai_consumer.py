"""
Watchlist Matcher Consumer: Consumes events:object_detected and evaluates watchlists (WL-26, WL-31).
"""

import os
import json
import time
import asyncio
from typing import Optional, Dict, Any, List, Tuple

from deepSightAI.Trinetra.Shared.LoggingSetup import dsai_get_logger
from deepSightAI.Trinetra.Shared.Errors import StorageError, StreamingError
from deepSightAI.Trinetra.Shared.Streaming.Consumer import StreamConsumer, Message
from deepSightAI.Trinetra.Shared.Streaming.Producer import StreamProducer
from deepSightAI.Trinetra.Shared.Streaming.RedisClient import create_redis_client
from deepSightAI.Trinetra.Shared.Streaming.Schema import ObjectDetectedEvent, WatchlistAlertEvent
from deepSightAI.Trinetra.Shared.Repositories.WatchlistRepository import AlertRepository
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_cache import WatchlistCache, dsai_get_watchlist_cache, WatchlistEntryCacheItem
from deepSightAI.Trinetra.WatchlistMatcherService.dsai_matcher import (
    dsai_match_plate,
    dsai_match_reid,
    AlertFloodSafeguard,
    dsai_get_alert_safeguard,
)

dsai_logger = dsai_get_logger("deepSightAI.Trinetra.WatchlistMatcherService.dsai_consumer")

# In-memory queues for real-time SSE streaming (WL-32)
_dsai_sse_subscribers: List[asyncio.Queue] = []


def dsai_register_sse_subscriber(dsai_queue: asyncio.Queue):
    """Register an active SSE queue subscriber."""
    if dsai_queue not in _dsai_sse_subscribers:
        _dsai_sse_subscribers.append(dsai_queue)


def dsai_unregister_sse_subscriber(dsai_queue: asyncio.Queue):
    """Unregister an SSE subscriber."""
    if dsai_queue in _dsai_sse_subscribers:
        _dsai_sse_subscribers.remove(dsai_queue)


def dsai_broadcast_alert_sse(dsai_alert_dict: Dict[str, Any]):
    """
    Broadcast an alert dictionary to all active SSE subscribers (WL-32).
    Dispatches both locally to in-process subscribers and across processes via Redis Pub/Sub.
    """
    # 1. Local in-process broadcast
    for dsai_sub in list(_dsai_sse_subscribers):
        try:
            dsai_sub.put_nowait(dsai_alert_dict)
        except Exception:
            pass

    # 2. Cross-process Redis Pub/Sub broadcast
    try:
        dsai_redis = create_redis_client()
        dsai_tenant = dsai_alert_dict.get("tenant_id") or "default"
        dsai_payload_str = json.dumps(dsai_alert_dict)
        dsai_redis.publish(f"channel:alerts:{dsai_tenant}", dsai_payload_str)
        dsai_redis.publish("channel:alerts:broadcast", dsai_payload_str)
    except Exception as dsai_redis_err:
        dsai_logger.debug(f"Redis Pub/Sub alert broadcast omitted/failed: {dsai_redis_err}")


class WatchlistMatcherConsumer:
    """
    Consumes ObjectDetectedEvent messages from 'events:object_detected' (WL-26).
    Evaluates detections against cached active watchlists and commits alerts (WL-31).
    """

    def __init__(
        self,
        dsai_config: Optional[Dict[str, Any]] = None,
        dsai_cache: Optional[WatchlistCache] = None,
        dsai_safeguard: Optional[AlertFloodSafeguard] = None,
        dsai_producer: Optional[StreamProducer] = None,
        dsai_consumer: Optional[StreamConsumer] = None
    ):
        self.dsai_config = dsai_config or {}
        self.dsai_stream_name = self.dsai_config.get("stream_name", "events:object_detected")
        self.dsai_alerts_stream = self.dsai_config.get("alerts_stream", "events:watchlist_alerts")
        self.dsai_group_name = self.dsai_config.get("group_name", "trinetra-watchlist-matcher")
        self.dsai_consumer_name = self.dsai_config.get(
            "consumer_name", f"matcher-{os.getpid()}"
        )

        self.dsai_cache = dsai_cache or dsai_get_watchlist_cache()
        self.dsai_safeguard = dsai_safeguard or dsai_get_alert_safeguard()

        # Streaming components (can be injected for testing)
        self.dsai_producer = dsai_producer
        self.dsai_consumer = dsai_consumer

        # Bounded retries & Dead-Letter Queue (REL-57)
        self.dsai_max_retries = int(
            self.dsai_config.get("max_retries") or os.getenv("MAX_MESSAGE_RETRIES", "3")
        )
        self.dsai_dlq_stream = (
            self.dsai_config.get("dlq_stream") or os.getenv("DLQ_STREAM", "events:dlq")
        )

        from deepSightAI.Trinetra.Shared.Streaming.dsai_resilient_consumer import ResilientStreamConsumer
        self.dsai_resilient_consumer = ResilientStreamConsumer(
            group_name=self.dsai_group_name,
            consumer_name=self.dsai_consumer_name,
            stream_name=self.dsai_stream_name,
            dlq_stream=self.dsai_dlq_stream,
            max_retries=self.dsai_max_retries,
            redis_client=getattr(self.dsai_consumer, "client", None),
            producer=self.dsai_producer,
            ack_fn=self.dsai_ack_message,
        )
        self.dsai_retry_counts: Dict[str, int] = self.dsai_resilient_consumer.dsai_retry_counts

    def dsai_ensure_streams(self):
        """Ensure StreamConsumer and StreamProducer are initialized."""
        if self.dsai_consumer is None:
            try:
                self.dsai_consumer = StreamConsumer(
                    group_name=self.dsai_group_name,
                    consumer_id=self.dsai_consumer_name
                )
                self.dsai_consumer.ensure_group(self.dsai_stream_name)
            except Exception as dsai_e:
                dsai_logger.warning(f"Could not connect Redis consumer: {dsai_e}")
                self.dsai_consumer = None

        if self.dsai_producer is None:
            try:
                self.dsai_producer = StreamProducer()
            except Exception as dsai_e:
                dsai_logger.warning(f"Could not connect Redis producer: {dsai_e}")
                self.dsai_producer = None

    def dsai_ack_message(self, dsai_msg_id: str):
        """Acknowledge message cleanly, handling both real StreamConsumer and test mocks."""
        if self.dsai_consumer is None:
            return
        try:
            self.dsai_consumer.ack(self.dsai_stream_name, dsai_msg_id)
        except TypeError:
            try:
                self.dsai_consumer.ack(dsai_msg_id)
            except Exception as dsai_ack_err:
                dsai_logger.error(f"Failed to ack message {dsai_msg_id}: {dsai_ack_err}")
        except Exception as dsai_ack_err:
            dsai_logger.error(f"Failed to ack message {dsai_msg_id}: {dsai_ack_err}")

    def dsai_reclaim_idle_messages(self, dsai_min_idle_ms: int = 60000, dsai_count: int = 10) -> List[Any]:
        """Automatic idle-message reclaim sweep using XPENDING / XCLAIM (REL-58)."""
        if not self.dsai_consumer or not hasattr(self.dsai_consumer, "client"):
            return []
        try:
            from deepSightAI.Trinetra.Shared.Streaming.ResilientConsumer import ResilientStreamConsumer
            r_consumer = ResilientStreamConsumer(
                dsai_group_name=self.dsai_group_name,
                dsai_stream_name=self.dsai_stream_name,
                dsai_consumer_id=self.dsai_consumer_name,
                dsai_redis_client=getattr(self.dsai_consumer, "client", None),
                dsai_producer=self.dsai_producer,
            )
            return r_consumer.reclaim_idle_messages(dsai_min_idle_ms=dsai_min_idle_ms, dsai_count=dsai_count)
        except Exception as e:
            dsai_logger.error(f"Error reclaiming idle messages: {e}")
            return []

    reclaim_idle_messages = dsai_reclaim_idle_messages

    def dsai_read_messages(self, dsai_count: int = 10) -> List[Any]:
        """Read pending unacknowledged messages first (PEL), then new messages."""
        if self.dsai_consumer is None:
            return []

        dsai_messages = []
        # Check consumer PEL for unacknowledged messages needing retry
        if hasattr(self.dsai_consumer, "client") and hasattr(self.dsai_consumer, "group_name") and hasattr(self.dsai_consumer, "consumer_id"):
            try:
                dsai_res = self.dsai_consumer.client.xreadgroup(
                    groupname=self.dsai_consumer.group_name,
                    consumername=self.dsai_consumer.consumer_id,
                    streams={self.dsai_stream_name: "0"},
                    count=dsai_count
                )
                if dsai_res:
                    for dsai_stream, dsai_msg_list in dsai_res:
                        for dsai_mid, dsai_data in dsai_msg_list:
                            dsai_messages.append(Message(stream=dsai_stream, msg_id=dsai_mid, data=dsai_data))
            except Exception as dsai_pel_err:
                dsai_logger.debug(f"PEL read check error: {dsai_pel_err}")

        # If no pending unacknowledged messages, read next messages from stream
        if not dsai_messages:
            try:
                dsai_messages = self.dsai_consumer.read(self.dsai_stream_name, count=dsai_count, block_ms=1000)
            except TypeError:
                dsai_messages = self.dsai_consumer.read(count=dsai_count, block_ms=1000)

        return dsai_messages or []

    def dsai_process_event(self, dsai_event: ObjectDetectedEvent) -> List[WatchlistAlertEvent]:
        """
        Evaluate a single ObjectDetectedEvent against active watchlist entries (WL-28, WL-29, WL-31).
        Inserts alerts durably, emits WatchlistAlertEvent, and broadcasts to SSE.
        """
        dsai_tenant_id = dsai_event.tenant_id or "default"
        dsai_active_entries = self.dsai_cache.dsai_get_active_entries(dsai_tenant_id)
        if not dsai_active_entries:
            return []

        dsai_matched_alerts: List[WatchlistAlertEvent] = []
        dsai_matches_found: List[Tuple[WatchlistEntryCacheItem, float, str, str]] = []

        # 1. Plate matching (WL-28)
        dsai_has_plate = bool(dsai_event.has_plate_read or dsai_event.plate_number)
        if dsai_has_plate and dsai_event.plate_number:
            for dsai_entry in dsai_active_entries:
                if dsai_entry.dsai_entry_type == "plate" and dsai_entry.dsai_plate_text_norm:
                    dsai_is_match, dsai_score = dsai_match_plate(
                        dsai_event.plate_number, dsai_entry.dsai_plate_text_norm
                    )
                    if dsai_is_match:
                        dsai_matches_found.append(
                            (dsai_entry, dsai_score, "plate", dsai_event.plate_number)
                        )

        # 2. Re-ID embedding matching (WL-29)
        dsai_emb = dsai_event.reid_embedding
        if dsai_emb is not None and dsai_event.object_class in ("person", "vehicle"):
            dsai_target_type = "person_reid" if dsai_event.object_class == "person" else "vehicle_reid"
            for dsai_entry in dsai_active_entries:
                if dsai_entry.dsai_entry_type == dsai_target_type and dsai_entry.dsai_reid_embedding:
                    dsai_is_match, dsai_score = dsai_match_reid(
                        dsai_emb, dsai_entry.dsai_reid_embedding
                    )
                    if dsai_is_match:
                        dsai_matches_found.append(
                            (dsai_entry, dsai_score, dsai_target_type, dsai_event.video_object_pk)
                        )

        # 3. Process confirmed matches: rate-limit, persist, emit (WL-31, WL-34)
        for dsai_entry, dsai_score, dsai_match_type, dsai_matched_entity in dsai_matches_found:
            # Check alert flood safeguard (WL-34)
            dsai_suppress, dsai_reason = self.dsai_safeguard.dsai_should_suppress(
                dsai_tenant_id=dsai_tenant_id,
                dsai_entry_id=dsai_entry.dsai_id,
                dsai_camera_id=dsai_event.camera_id
            )
            if dsai_suppress:
                dsai_logger.info(
                    f"Suppressed alert for entry {dsai_entry.dsai_id} (camera {dsai_event.camera_id}) due to {dsai_reason}"
                )
                continue

            # Durable commit to PostgreSQL alerts table (WL-31)
            try:
                dsai_alert_repo = AlertRepository(dsai_tenant_id)
                dsai_alert_record = dsai_alert_repo.dsai_create(
                    watchlist_entry_id=dsai_entry.dsai_id,
                    video_object_pk=dsai_event.video_object_pk,
                    camera_id=dsai_event.camera_id,
                    match_score=dsai_score,
                    crop_path=dsai_event.crop_path
                )
            except Exception as dsai_db_err:
                dsai_logger.error(
                    f"Durable commit failed for alert on entry {dsai_entry.dsai_id}: {dsai_db_err}"
                )
                raise StorageError(
                    f"Failed to persist alert in database for object {dsai_event.video_object_pk}: {dsai_db_err}"
                )

            # Record alert in safeguard
            self.dsai_safeguard.dsai_record_alert(
                dsai_tenant_id=dsai_tenant_id,
                dsai_entry_id=dsai_entry.dsai_id,
                dsai_camera_id=dsai_event.camera_id
            )

            # Construct WatchlistAlertEvent
            dsai_alert_event = WatchlistAlertEvent(
                alert_id=dsai_alert_record.id,
                tenant_id=dsai_tenant_id,
                watchlist_entry_id=dsai_entry.dsai_id,
                video_object_pk=dsai_event.video_object_pk,
                camera_id=dsai_event.camera_id,
                matched_at=dsai_alert_record.matched_at,
                match_score=dsai_score,
                crop_path=dsai_event.crop_path,
                label=dsai_entry.dsai_label,
                priority=dsai_entry.dsai_priority,
                entry_type=dsai_match_type,
                matched_entity=dsai_matched_entity
            )
            dsai_matched_alerts.append(dsai_alert_event)

            # Publish WatchlistAlertEvent to events:watchlist_alerts (WL-31)
            if self.dsai_producer is not None:
                try:
                    self.dsai_producer.publish(self.dsai_alerts_stream, dsai_alert_event)
                except Exception as dsai_pub_err:
                    dsai_logger.error(f"Failed to publish WatchlistAlertEvent: {dsai_pub_err}")
                    raise StreamingError(f"Watchlist alert publish failed: {dsai_pub_err}")

            # Broadcast to real-time SSE listeners
            dsai_broadcast_alert_sse(dsai_alert_event.model_dump(mode="json"))
            dsai_logger.info(
                f"Generated WatchlistAlert [id={dsai_alert_record.id}] for {dsai_match_type} "
                f"'{dsai_matched_entity}' on cam '{dsai_event.camera_id}' (score={dsai_score:.2f})"
            )

        return dsai_matched_alerts

    def dsai_consume_batch(self, dsai_count: int = 10) -> int:
        """
        Fetch and process a batch of ObjectDetectedEvent messages.
        Acks only after durable commit (WL-31).
        Implements bounded retries and DLQ routing on failures (REL-57).
        """
        self.dsai_ensure_streams()
        if self.dsai_consumer is None:
            return 0

        # Synchronize resilient consumer dependencies
        self.dsai_resilient_consumer.dsai_producer = self.dsai_producer
        self.dsai_resilient_consumer.dsai_max_retries = self.dsai_max_retries
        self.dsai_resilient_consumer.dsai_dlq_stream = self.dsai_dlq_stream
        self.dsai_resilient_consumer.dsai_ack_fn = self.dsai_ack_message
        if hasattr(self.dsai_consumer, "client") and self.dsai_consumer.client is not None:
            self.dsai_resilient_consumer.dsai_client = self.dsai_consumer.client

        try:
            dsai_messages = self.dsai_read_messages(dsai_count=dsai_count)
        except Exception as dsai_read_err:
            dsai_logger.error(f"Error reading from stream {self.dsai_stream_name}: {dsai_read_err}")
            return 0

        dsai_processed = 0
        for dsai_msg in dsai_messages:
            def dsai_handle_object_event(m):
                dsai_payload = m.data
                if isinstance(dsai_payload, str):
                    dsai_payload = json.loads(dsai_payload)
                elif isinstance(dsai_payload, dict) and "event" in dsai_payload and isinstance(dsai_payload["event"], str):
                    dsai_payload = json.loads(dsai_payload["event"])

                dsai_obj_event = ObjectDetectedEvent(**dsai_payload)
                self.dsai_process_event(dsai_obj_event)

            if self.dsai_resilient_consumer.dsai_process_message(dsai_msg, dsai_handle_object_event):
                dsai_processed += 1

        return dsai_processed

    def run_loop(self, dsai_stop_flag=None):
        """Continuous consumer loop (REL-57, REL-58)."""
        dsai_logger.info(f"Starting WatchlistMatcherConsumer loop on '{self.dsai_stream_name}'...")
        self.dsai_cache.dsai_start()

        dsai_last_reclaim = time.time()
        while True:
            if dsai_stop_flag and dsai_stop_flag.is_set():
                break

            try:
                # Periodic idle message reclaim sweep (REL-58)
                if time.time() - dsai_last_reclaim > 30.0:
                    try:
                        self.dsai_reclaim_idle_messages()
                    except Exception as dsai_reclaim_err:
                        dsai_logger.debug(f"Matcher idle reclaim sweep error: {dsai_reclaim_err}")
                    dsai_last_reclaim = time.time()

                dsai_count = self.dsai_consume_batch(dsai_count=10)
                if dsai_count == 0:
                    time.sleep(0.1)
            except Exception as dsai_loop_err:
                dsai_logger.error(f"WatchlistMatcherConsumer loop error: {dsai_loop_err}")
                time.sleep(1.0)

        self.dsai_cache.dsai_stop()
        dsai_logger.info("WatchlistMatcherConsumer loop terminated.")

    dsai_run_loop = run_loop
