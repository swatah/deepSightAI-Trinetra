"""
Resilient Redis Stream Consumer with Bounded Retry, DLQ Routing, and Idle-Message Reclaim (REL-57, REL-58, REL-59).

Provides:
- ResilientStreamConsumer: Unified consumer handling:
  1. Idempotent group creation
  2. Bounded per-message retry with configurable max retries
  3. Poison pill isolation & Dead-Letter Queue (DLQ) routing
  4. Automatic idle-message reclaim sweep (XPENDING / XCLAIM)
  5. X-Request-ID & correlation ID propagation
  6. Scrapeable metrics updates (DLQ depth, processing latency)
"""

import os
import json
import time
import uuid
import logging
from typing import Optional, Dict, Any, List, Callable, Tuple
import redis

from deepSightAI.Trinetra.Shared.LoggingSetup import dsai_get_logger
from deepSightAI.Trinetra.Shared.Errors import StreamingError, DeadLetterQueueError
from deepSightAI.Trinetra.Shared.Streaming.Consumer import Message
from deepSightAI.Trinetra.Shared.Streaming.Producer import StreamProducer
from deepSightAI.Trinetra.Shared.Streaming.RedisClient import create_redis_client
from deepSightAI.Trinetra.Shared.Metrics import dsai_update_dlq_depth, dsai_record_processing_latency

dsai_logger = dsai_get_logger("deepSightAI.Trinetra.Shared.Streaming.ResilientConsumer")


class ResilientStreamConsumer:
    """
    Unified resilient consumer for Redis Streams (REL-59).
    Implements bounded retries (REL-57) and idle-message reclaim sweep (REL-58).
    """

    def __init__(
        self,
        dsai_group_name: Optional[str] = None,
        dsai_stream_name: Optional[str] = None,
        dsai_consumer_id: Optional[str] = None,
        dsai_dlq_stream: Optional[str] = None,
        dsai_max_retries: int = 3,
        dsai_idle_reclaim_ms: int = 60000,
        dsai_redis_client: Optional[Any] = None,
        dsai_producer: Optional[StreamProducer] = None,
        **kwargs,
    ):
        self.dsai_group_name = dsai_group_name or kwargs.get("group_name", "default-group")
        self.dsai_stream_name = dsai_stream_name or kwargs.get("stream_name", "events:default")
        self.dsai_consumer_id = dsai_consumer_id or kwargs.get("consumer_name") or f"resilient-{uuid.uuid4().hex[:8]}"
        self.dsai_dlq_stream = dsai_dlq_stream or kwargs.get("dlq_stream") or os.getenv("DLQ_STREAM", "events:dlq")
        self.dsai_max_retries = int(kwargs.get("max_retries", dsai_max_retries))
        self.dsai_idle_reclaim_ms = int(kwargs.get("idle_reclaim_ms", dsai_idle_reclaim_ms))
        self.dsai_client = dsai_redis_client or kwargs.get("redis_client") or create_redis_client()
        self.dsai_producer = dsai_producer or kwargs.get("producer")
        self.dsai_ack_fn = kwargs.get("ack_fn") or kwargs.get("dsai_ack_fn")
        self.dsai_retry_backoff_base = float(kwargs.get("retry_backoff_base", 0.1))
        self.dsai_retry_counts: Dict[str, int] = {}

    def dsai_ensure_group(self, dsai_stream: Optional[str] = None) -> None:
        """Ensure consumer group exists for the stream."""
        dsai_target_stream = dsai_stream or self.dsai_stream_name
        try:
            self.dsai_client.xgroup_create(
                stream=dsai_target_stream,
                groupname=self.dsai_group_name,
                id='$',
                mkstream=True
            )
        except TypeError:
            try:
                self.dsai_client.xgroup_create(
                    name=dsai_target_stream,
                    groupname=self.dsai_group_name,
                    id='$',
                    mkstream=True
                )
            except Exception as dsai_e:
                dsai_msg = str(dsai_e).lower()
                if "busygroup" in dsai_msg or "already exists" in dsai_msg:
                    return
                raise
        except Exception as dsai_e:
            dsai_msg = str(dsai_e).lower()
            if "busygroup" in dsai_msg or "already exists" in dsai_msg:
                return
            raise

    def dsai_read_messages(self, dsai_count: int = 10, dsai_block_ms: int = 2000) -> List[Message]:
        """Read pending unacknowledged messages first (PEL '0'), then new messages ('>')."""
        self.dsai_ensure_group(self.dsai_stream_name)

        dsai_result = None
        # 1. Check PEL for this consumer first (ID "0")
        try:
            dsai_res_pel = self.dsai_client.xreadgroup(
                groupname=self.dsai_group_name,
                consumername=self.dsai_consumer_id,
                streams={self.dsai_stream_name: '0'},
                count=dsai_count
            )
            if dsai_res_pel and isinstance(dsai_res_pel, (list, tuple)):
                for dsai_s, dsai_msgs in dsai_res_pel:
                    if dsai_msgs and isinstance(dsai_msgs, (list, tuple)):
                        dsai_result = dsai_res_pel
                        break
        except Exception as dsai_pel_err:
            dsai_logger.debug(f"PEL read check on {self.dsai_stream_name}: {dsai_pel_err}")

        # 2. If no pending unacknowledged messages in PEL, read new messages ('>')
        if not dsai_result:
            try:
                dsai_result = self.dsai_client.xreadgroup(
                    groupname=self.dsai_group_name,
                    consumername=self.dsai_consumer_id,
                    streams={self.dsai_stream_name: '>'},
                    count=dsai_count,
                    block=dsai_block_ms
                )
            except (redis.exceptions.TimeoutError, Exception) as dsai_err:
                dsai_logger.debug(f"Read timeout/error on {self.dsai_stream_name}: {dsai_err}")
                return []

        dsai_messages: List[Message] = []
        if dsai_result and isinstance(dsai_result, (list, tuple)):
            for dsai_stream, dsai_msg_list in dsai_result:
                for dsai_msg_id, dsai_data in dsai_msg_list:
                    # Normalize string keys if returned as bytes
                    if isinstance(dsai_msg_id, bytes):
                        dsai_msg_id = dsai_msg_id.decode("utf-8")
                    dsai_clean_data = {}
                    if isinstance(dsai_data, dict):
                        for k, v in dsai_data.items():
                            k_str = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                            v_str = v.decode("utf-8") if isinstance(v, bytes) else v
                            dsai_clean_data[k_str] = v_str
                    dsai_messages.append(Message(
                        stream=str(dsai_stream),
                        msg_id=str(dsai_msg_id),
                        data=dsai_clean_data
                    ))
        return dsai_messages

    def dsai_reclaim_idle_messages(
        self,
        dsai_min_idle_ms: Optional[int] = None,
        dsai_count: int = 10
    ) -> List[Message]:
        """
        Sweep and reclaim pending messages stranded by dead or unresponsive consumers (REL-58).
        Uses XPENDING to discover pending messages and XCLAIM to reassign ownership.
        """
        dsai_min_idle = dsai_min_idle_ms if dsai_min_idle_ms is not None else self.dsai_idle_reclaim_ms
        dsai_claimed_messages: List[Message] = []

        try:
            # 1. Discover pending messages using xpending_range or xpending
            dsai_pending_entries = []
            if hasattr(self.dsai_client, "xpending_range"):
                try:
                    dsai_pending_entries = self.dsai_client.xpending_range(
                        name=self.dsai_stream_name,
                        groupname=self.dsai_group_name,
                        min="-",
                        max="+",
                        count=dsai_count
                    )
                except Exception as dsai_pr_err:
                    dsai_logger.debug(f"xpending_range fallback: {dsai_pr_err}")

            if not dsai_pending_entries and hasattr(self.dsai_client, "xpending"):
                try:
                    dsai_summary = self.dsai_client.xpending(
                        name=self.dsai_stream_name,
                        groupname=self.dsai_group_name
                    )
                    # Summary returns [count, min_id, max_id, [[consumer, count], ...]]
                except Exception:
                    pass

            # 2. Identify messages eligible for reclaim (idle >= min_idle)
            dsai_ids_to_claim = []
            for dsai_entry in dsai_pending_entries:
                if isinstance(dsai_entry, dict):
                    dsai_mid = dsai_entry.get("message_id")
                    dsai_idle = (
                        dsai_entry.get("idle_time")
                        or dsai_entry.get("time_since_delivered")
                        or dsai_entry.get("idle")
                        or 0
                    )
                    dsai_owner = dsai_entry.get("consumer", "")
                elif isinstance(dsai_entry, (list, tuple)) and len(dsai_entry) >= 3:
                    dsai_mid = dsai_entry[0]
                    dsai_owner = dsai_entry[1]
                    dsai_idle = dsai_entry[2]
                else:
                    continue

                if isinstance(dsai_mid, bytes):
                    dsai_mid = dsai_mid.decode("utf-8")
                if isinstance(dsai_owner, bytes):
                    dsai_owner = dsai_owner.decode("utf-8")

                if dsai_idle >= dsai_min_idle and str(dsai_owner) != self.dsai_consumer_id:
                    dsai_ids_to_claim.append(str(dsai_mid))

            # 3. Claim discovered idle messages
            for dsai_claim_id in dsai_ids_to_claim:
                try:
                    dsai_claimed = self.dsai_client.xclaim(
                        self.dsai_stream_name,
                        self.dsai_group_name,
                        self.dsai_consumer_id,
                        dsai_min_idle,
                        [dsai_claim_id]
                    )
                    if dsai_claimed:
                        for item in dsai_claimed:
                            if isinstance(item, (list, tuple)) and len(item) == 2:
                                cid, cdata = item
                                cid_str = cid.decode("utf-8") if isinstance(cid, bytes) else str(cid)
                                cdata_clean = {}
                                if isinstance(cdata, dict):
                                    for k, v in cdata.items():
                                        k_str = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                                        v_str = v.decode("utf-8") if isinstance(v, bytes) else v
                                        cdata_clean[k_str] = v_str
                                dsai_claimed_messages.append(Message(
                                    stream=self.dsai_stream_name,
                                    msg_id=cid_str,
                                    data=cdata_clean
                                ))
                                dsai_logger.info(
                                    f"Reclaimed idle pending message {cid_str} on stream {self.dsai_stream_name}"
                                )
                except Exception as dsai_claim_err:
                    dsai_logger.debug(f"Failed to claim message {dsai_claim_id}: {dsai_claim_err}")

        except Exception as dsai_sweep_err:
            dsai_logger.error(f"Error during idle message reclaim sweep: {dsai_sweep_err}")

        return dsai_claimed_messages

    def dsai_ack(self, dsai_msg_id: str) -> None:
        """Acknowledge message processing and clear retry state."""
        if self.dsai_ack_fn is not None:
            try:
                self.dsai_ack_fn(dsai_msg_id)
            except Exception as dsai_ack_err:
                dsai_logger.error(f"Custom ack failed for {dsai_msg_id}: {dsai_ack_err}")
        elif self.dsai_client is not None:
            try:
                if hasattr(self.dsai_client, "xack"):
                    self.dsai_client.xack(self.dsai_stream_name, self.dsai_group_name, dsai_msg_id)
                elif hasattr(self.dsai_client, "ack"):
                    self.dsai_client.ack(self.dsai_stream_name, dsai_msg_id)
            except Exception as dsai_ack_err:
                dsai_logger.error(f"Failed to acknowledge {dsai_msg_id}: {dsai_ack_err}")
        self.dsai_retry_counts.pop(dsai_msg_id, None)

    def dsai_route_to_dlq(self, dsai_msg: Any, dsai_error: Exception) -> bool:
        """Route failed message to DLQ stream upon exceeding max retries (REL-57)."""
        dsai_msg_id = getattr(dsai_msg, "id", None) or (dsai_msg.get("id") if isinstance(dsai_msg, dict) else str(uuid.uuid4()))
        dsai_payload = getattr(dsai_msg, "data", dsai_msg)
        dsai_attempts = self.dsai_retry_counts.get(dsai_msg_id, self.dsai_max_retries)

        # Extract correlation ID if present
        dsai_corr_id = None
        if isinstance(dsai_payload, dict):
            dsai_corr_id = dsai_payload.get("x_request_id")
            if not dsai_corr_id and "event" in dsai_payload:
                try:
                    inner = json.loads(dsai_payload["event"])
                    if isinstance(inner, dict):
                        dsai_corr_id = inner.get("correlation_id") or inner.get("request_id")
                except Exception:
                    pass

        dsai_dlq_record = {
            "source_stream": self.dsai_stream_name,
            "message_id": dsai_msg_id,
            "event": dsai_payload,
            "error": str(dsai_error),
            "retry_count": dsai_attempts,
            "correlation_id": dsai_corr_id,
            "failed_at": time.time(),
        }

        # Publish to DLQ
        published = False
        if self.dsai_producer is not None:
            try:
                self.dsai_producer.publish(self.dsai_dlq_stream, dsai_dlq_record)
                published = True
            except Exception as dsai_pub_err:
                dsai_logger.error(f"Producer publish to DLQ failed: {dsai_pub_err}")

        if not published:
            try:
                self.dsai_client.xadd(self.dsai_dlq_stream, {"event": json.dumps(dsai_dlq_record)})
                published = True
            except Exception as dsai_raw_err:
                dsai_logger.error(f"Raw client publish to DLQ failed: {dsai_raw_err}")

        # Update scrapeable DLQ depth metric (REL-64)
        try:
            dsai_depth = self.dsai_client.xlen(self.dsai_dlq_stream)
            dsai_update_dlq_depth(self.dsai_dlq_stream, dsai_depth)
        except Exception:
            pass

        # Ack from source stream to unblock poison pill
        self.dsai_ack(dsai_msg_id)
        dsai_logger.warning(
            f"Poison pill message {dsai_msg_id} routed to DLQ '{self.dsai_dlq_stream}' "
            f"after {dsai_attempts} retries: {dsai_error}"
        )
        return published

    def dsai_process_message(
        self,
        dsai_msg: Any,
        dsai_handler: Callable[[Any], Any]
    ) -> bool:
        """
        Process message with durable ack-after-success and bounded retry/DLQ routing (REL-57).
        """
        if isinstance(dsai_msg, dict):
            dsai_msg = Message(
                stream=dsai_msg.get("stream", self.dsai_stream_name),
                msg_id=str(dsai_msg.get("id", uuid.uuid4())),
                data=dsai_msg.get("data", dsai_msg)
            )

        dsai_start = time.time()
        try:
            dsai_handler(dsai_msg)
            # Acknowledge ONLY after handler returns successfully
            self.dsai_ack(dsai_msg.id)
            dsai_record_processing_latency("resilient_consumer", self.dsai_stream_name, time.time() - dsai_start)
            return True
        except Exception as dsai_err:
            self.dsai_retry_counts[dsai_msg.id] = self.dsai_retry_counts.get(dsai_msg.id, 0) + 1
            attempts = self.dsai_retry_counts[dsai_msg.id]
            dsai_logger.error(
                f"Error processing message {dsai_msg.id} on '{self.dsai_stream_name}' "
                f"(attempt {attempts}/{self.dsai_max_retries}): {dsai_err}"
            )

            if attempts >= self.dsai_max_retries:
                self.dsai_route_to_dlq(dsai_msg, dsai_err)
            return False

    # Backwards compatibility methods and aliases
    dsai_process_single_message = dsai_process_message
    process_single_message = dsai_process_message
    ensure_group = dsai_ensure_group
    read_messages = dsai_read_messages
    reclaim_idle_messages = dsai_reclaim_idle_messages
    ack = dsai_ack
    route_to_dlq = dsai_route_to_dlq
    process_message = dsai_process_message
