import os
import gi
import uvicorn
import httpx
try:
    import ffmpeg
except ImportError:
    ffmpeg = None
import sys
import tempfile
import time
import traceback
import uuid
from collections import deque
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from minio import Minio
from minio.error import S3Error
import signal
import threading
from deepSightAI.Trinetra.Shared.Streaming.Producer import StreamProducer
from deepSightAI.Trinetra.Shared.Streaming.Schema import FrameReadyEvent
from deepSightAI.Trinetra.Shared.Config import get as get_config
from deepSightAI.Trinetra.Shared.Storage import configure_bucket_lifecycle

# --- GStreamer and GObject Imports ---
try:
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst, GLib
    Gst.init(None)
except (ImportError, AttributeError, ValueError, Exception):
    Gst = None
    GLib = None

# --- CONFIGURATION ---
EXTRACTOR_ID = os.getenv("EXTRACTOR_ID", "default_extractor")
EXTRACTOR_URL = os.getenv("EXTRACTOR_URL", "http://localhost:8001")
REGISTRY_URL = os.getenv("REGISTRY_URL", "http://registry:8000")
MINIO_URL = os.getenv("MINIO_URL", "localhost:9000")
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
VIDEO_BUCKET = "videos"
FRAME_BUCKET = "frames"  # Used for file jobs
CONTROL_STREAM = "control:ingest"  # For publishing events; will also have frames:{video_id} later but we use control for now per design? Actually design says frames go to frames:{video_id}. We'll use that.

EXTRACTION_FPS = int(os.getenv("EXTRACTION_FPS", get_config("extraction.fps", 5)))
EXTRACTOR_THREADS = int(os.getenv("EXTRACTOR_THREADS", get_config("extraction.extractor_threads", 4)))

# RTSP concurrency: how many live camera feeds this process accepts.
# Hard-capped at 6 regardless of what the config file or env var says.
RTSP_SOFT_LIMIT = int(os.getenv("RTSP_SOFT_LIMIT", get_config("extraction.rtsp_soft_limit", 3)))
RTSP_HARD_LIMIT = min(6, int(os.getenv("RTSP_HARD_LIMIT", get_config("extraction.rtsp_hard_limit", 6))))

# --- Graceful Shutdown Event (file jobs use this one implicitly via signal handling) ---
shutdown_event = threading.Event()

# Bounds how many FILE extraction jobs this process runs at once, sized from
# EXTRACTOR_THREADS. RTSP streams are NOT gated by this -- they're a separate,
# long-running, lightweight I/O workload with their own soft/hard limit below,
# since a single process can watch several camera feeds concurrently without
# needing a dedicated worker slot per feed the way a file segment job does.
_job_slots = threading.Semaphore(EXTRACTOR_THREADS)

# --- RTSP capacity tracking ---
# stream_id -> threading.Event(), one per active RTSP stream so each can be
# stopped independently (a single shared event would stop every stream at once).
_active_rtsp_streams = {}
# camera_id -> stream_id mapping for stopping streams by camera identifier
_active_camera_streams = {}
# RLock, not Lock: /extract_stream holds this while calling _rtsp_effective_limit(),
# which itself acquires it via _rtsp_is_degraded() -- a plain Lock would deadlock
# on that reentrant acquisition from the same thread.
_rtsp_lock = threading.RLock()

# Rolling window of recent per-frame grab+upload latencies (seconds), used to
# detect degradation. If the extractor is struggling to keep up, average
# latency rises well above what a healthy feed looks like.
_rtsp_frame_latencies = deque(maxlen=20)
_RTSP_DEGRADED_LATENCY_SECONDS = 0.5


def _rtsp_record_latency(seconds: float):
    with _rtsp_lock:
        _rtsp_frame_latencies.append(seconds)


def _rtsp_is_degraded() -> bool:
    with _rtsp_lock:
        if not _rtsp_frame_latencies:
            return False
        avg = sum(_rtsp_frame_latencies) / len(_rtsp_frame_latencies)
    return avg > _RTSP_DEGRADED_LATENCY_SECONDS


def _rtsp_effective_limit() -> int:
    """The ceiling currently in effect: throttled down to the soft limit
    while degraded, otherwise the hard limit."""
    return RTSP_SOFT_LIMIT if _rtsp_is_degraded() else RTSP_HARD_LIMIT

def ensure_bucket(minio_client, bucket_name):
    """Helper function to create a Minio bucket if it doesn't already exist and configure retention."""
    try:
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
        if bucket_name == FRAME_BUCKET:
            configure_bucket_lifecycle(minio_client, bucket_name, retention_days=7)
    except S3Error as err:
        if err.code != "BucketAlreadyOwnedByYou":
            raise


# --- EVENT PUBLISHING ---
_producer = None


def get_producer() -> StreamProducer:
    """Lazy singleton for StreamProducer."""
    global _producer
    if _producer is None:
        _producer = StreamProducer()
    return _producer


import json

# In-memory recoverable orphan log (REL-56)
DSAI_RECOVERABLE_ORPHANS = []


def dsai_record_recoverable_orphan(event: FrameReadyEvent, error_message: str):
    """Record recoverable orphan event when Redis publish exhausts retries (REL-56)."""
    orphan_record = {
        "event": event.model_dump() if hasattr(event, "model_dump") else event.dict(),
        "error": error_message,
        "recorded_at": datetime.utcnow().isoformat(),
        "status": "RECOVERABLE_ORPHAN"
    }
    DSAI_RECOVERABLE_ORPHANS.append(orphan_record)
    try:
        orphan_log_path = os.getenv("ORPHAN_LOG_PATH", "/tmp/dsai_recoverable_orphans.jsonl")
        with open(orphan_log_path, "a") as f:
            f.write(json.dumps(orphan_record) + "\n")
        print(f"[{EXTRACTOR_ID}] Recorded recoverable orphan to {orphan_log_path}")
    except Exception as log_e:
        print(f"[{EXTRACTOR_ID}] Failed to write orphan log: {log_e}")


def dsai_upload_frame_with_retry(
    minio_client,
    bucket_name: str,
    object_name: str,
    file_path: str,
    max_retries: int = 3,
    initial_delay: float = 0.1,
    backoff: float = 2.0
) -> bool:
    """
    Retry with backoff on extractor MinIO upload; route to DLQ on exhaustion (REL-55).
    """
    delay = initial_delay
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            minio_client.fput_object(bucket_name, object_name, file_path)
            return True
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(delay)
                delay *= backoff

    # DLQ routing on exhaustion (REL-55)
    dlq_payload = {
        "event_type": "minio.upload.failed",
        "extractor_id": EXTRACTOR_ID,
        "bucket": bucket_name,
        "object_name": object_name,
        "error": str(last_err),
        "timestamp": datetime.utcnow().isoformat()
    }
    try:
        producer = get_producer()
        producer.publish("events:dlq", dlq_payload)
        print(f"[{EXTRACTOR_ID}] Routed failed upload {object_name} to events:dlq")
    except Exception as dlq_e:
        print(f"[{EXTRACTOR_ID}] Failed to route to DLQ: {dlq_e}")

    return False


def publish_frame_ready_event(video_id: str, segment_id: int, frame_paths: list,
                               timestamps: list, sequence_numbers: list,
                               bucket_name: str = None,
                               tenant_id: str = "default",
                               camera_id: str = None,
                               correlation_id: str = None):
    """
    Publish FrameReadyEvent to Redis Streams with retry and orphan recording (REL-56).
    """
    if bucket_name is None:
        bucket_name = FRAME_BUCKET

    event = None
    try:
        event = FrameReadyEvent(
            video_id=video_id,
            segment_id=segment_id,
            frame_paths=frame_paths,
            timestamps=timestamps,
            sequence_numbers=sequence_numbers,
            extractor_id=EXTRACTOR_ID,
            bucket_name=bucket_name,
            tenant_id=tenant_id or "default",
            camera_id=camera_id,
            correlation_id=correlation_id,
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        print(f"[{EXTRACTOR_ID}] Failed to construct FrameReadyEvent: {e}")
        return

    stream_name = os.getenv("FRAME_EVENTS_STREAM", "frames")
    max_retries = 3
    delay = 0.05 if "pytest" in sys.modules else 0.1
    last_err = None

    for attempt in range(1, max_retries + 1):
        try:
            producer = get_producer()
            producer.publish(stream_name, event)
            print(f"[{EXTRACTOR_ID}] Published FrameReadyEvent to {stream_name} for video {video_id}, segment {segment_id}")
            return
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2.0

    # Exhaustion: Record recoverable orphan (REL-56)
    print(f"[{EXTRACTOR_ID}] Exhausted retries publishing FrameReadyEvent for video {video_id}: {last_err}")
    dsai_record_recoverable_orphan(event, str(last_err))

# --- CLASS FOR VIDEO FILE EXTRACTION (UNCHANGED) ---
class GStreamerFileExtractor:
    """Extracts frames from a local video file and saves them to a directory."""
    def extract_frames(self, input_file, output_dir):
        file_uri = f"file://{os.path.abspath(input_file)}"
        pipeline_desc = f"""
        uridecodebin uri="{file_uri}" ! videoconvert ! videorate ! video/x-raw,framerate={EXTRACTION_FPS}/1 !
        jpegenc !
        multifilesink location="{output_dir}/frame-%05d.jpg"
        """
        pipeline = Gst.parse_launch(pipeline_desc)
        bus = pipeline.get_bus()
        pipeline.set_state(Gst.State.PLAYING)
        try:
            msg = bus.timed_pop_filtered(Gst.CLOCK_TIME_NONE, Gst.MessageType.EOS | Gst.MessageType.ERROR)
            if msg and msg.type == Gst.MessageType.ERROR:
                err, debug = msg.parse_error()
                print(f"[{EXTRACTOR_ID}] GStreamer Error (File): {err} {debug}")
        finally:
            pipeline.set_state(Gst.State.NULL)

# --- CLASS FOR RTSP STREAM EXTRACTION (MODIFIED) ---
class GStreamerRtspExtractor:
    """
    Connects to an RTSP stream, captures frames, and uploads them to Minio.
    It checks a threading.Event to know when to shut down gracefully.
    """
    def __init__(self, rtsp_url: str, video_id: str, minio_client, bucket_name: str, shutdown_event: threading.Event,
                 tenant_id: str = "default", camera_id: str = None):
        self.rtsp_url = rtsp_url
        self.video_id = video_id
        self.minio_client = minio_client
        self.bucket_name = bucket_name
        self.shutdown_event = shutdown_event  # per-stream, not shared with other concurrent streams
        self.tenant_id = tenant_id or "default"
        self.camera_id = camera_id or video_id
        self.loop = GLib.MainLoop()
        self.pipeline = None
        self.sequence_counter = 0  # Track sequence numbers within this session

    def on_message(self, bus, message):
        """Callback to handle messages from the GStreamer bus."""
        msg_type = message.type
        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"[{EXTRACTOR_ID}] GStreamer error (RTSP): {err} {debug}")
            self.stop()
            # Do NOT set shutdown_event here so the reconnect loop in run_rtsp_extraction_job can retry
        elif msg_type == Gst.MessageType.EOS:
            print(f"[{EXTRACTOR_ID}] End-of-stream reached for RTSP.")
            self.stop()

    def on_new_sample(self, sink):
        """Callback triggered when a new frame is available from the appsink."""
        frame_start = time.monotonic()
        sample = sink.emit("pull-sample")
        if sample:
            buffer = sample.get_buffer()
            try:
                success, map_info = buffer.map(Gst.MapFlags.READ)
                if success:
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=True) as tmpfile:
                        tmpfile.write(map_info.data)
                        tmpfile.flush()
                        date_str = datetime.utcnow().strftime("%Y-%m-%d")
                        frame_name = f"{self.tenant_id}/{self.camera_id}/{date_str}/frame_{int(time.time() * 1000)}_{self.sequence_counter:06d}.jpg"
                        upload_ok = dsai_upload_frame_with_retry(self.minio_client, self.bucket_name, frame_name, tmpfile.name)
                        if upload_ok:
                            print(f"[{EXTRACTOR_ID}] Uploaded {frame_name} to bucket {self.bucket_name}")
                            _rtsp_record_latency(time.monotonic() - frame_start)

                            # Publish FrameReadyEvent
                            try:
                                # For RTSP, segment_id is always 0
                                seq_num = self.sequence_counter
                                self.sequence_counter += 1
                                timestamp = time.time()
                                publish_frame_ready_event(
                                    video_id=self.video_id,
                                    segment_id=0,
                                    frame_paths=[frame_name],
                                    timestamps=[timestamp],
                                    sequence_numbers=[seq_num],
                                    bucket_name=self.bucket_name,
                                    tenant_id=self.tenant_id,
                                    camera_id=self.camera_id
                                )
                            except Exception as e:
                                print(f"[{EXTRACTOR_ID}] Failed to publish frame event: {e}")

            except Exception as e:
                print(f"[{EXTRACTOR_ID}] Failed to upload frame: {e}")
            finally:
                if 'map_info' in locals():
                    buffer.unmap(map_info)
        return Gst.FlowReturn.OK

    def start(self):
        """Builds and starts the GStreamer pipeline and checks for shutdown."""
        ensure_bucket(self.minio_client, self.bucket_name)
        pipeline_desc = f"""
            rtspsrc location={self.rtsp_url} latency=0 !
            rtph264depay ! h264parse ! avdec_h264 !
            videoconvert ! videorate ! video/x-raw,framerate={EXTRACTION_FPS}/1 !
            jpegenc ! appsink name=sink emit-signals=true
        """
        try:
            self.pipeline = Gst.parse_launch(pipeline_desc)
            appsink = self.pipeline.get_by_name("sink")
            appsink.connect("new-sample", self.on_new_sample)
            bus = self.pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self.on_message)
            print(f"[{EXTRACTOR_ID}] Starting RTSP pipeline...")
            self.pipeline.set_state(Gst.State.PLAYING)
            # Use a context to periodically check this stream's own shutdown event
            context = self.loop.get_context()
            while not self.shutdown_event.is_set():
                context.iteration(may_block=True)
            print(f"[{EXTRACTOR_ID}] Shutdown signal received, stopping RTSP stream...")
            self.stop()
        except Exception as e:
            print(f"[{EXTRACTOR_ID}] Failed to start RTSP pipeline: {e}")
            self.stop()

    def stop(self):
        """Stops the pipeline and quits the main loop."""
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        if self.loop.is_running():
            self.loop.quit()

# --- FASTAPI REQUEST MODELS ---
class HttpFileRequest(BaseModel):
    video_uri: str
    segment_id: int
    start_time: float
    duration: float
    tenant_id: str = "default"
    camera_id: Optional[str] = None

# Backward compatibility alias
FileJobRequest = HttpFileRequest


class HttpRtspRequest(BaseModel):
    rtsp_url: str
    tenant_id: str = "default"
    camera_id: Optional[str] = None

# Backward compatibility alias
RtspJobRequest = HttpRtspRequest

# --- BACKGROUND JOB FUNCTIONS ---
def run_file_extraction_job(video_uri: str, segment_id: int, start_time: float, duration: float,
                            tenant_id: str = "default", camera_id: Optional[str] = None):
    """Background task to process a segment of a video file from Minio."""
    _job_slots.acquire()
    with httpx.Client() as client:
        client.post(f"{REGISTRY_URL}/update_status?extractor_id={EXTRACTOR_ID}&status=busy")

    clean_minio_url = MINIO_URL.replace("http://", "").replace("https://", "")
    minio_client = Minio(clean_minio_url, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)

    # Collect frame metadata for event publishing
    uploaded_frames = []  # list of (object_name, timestamp, sequence_number)

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            ensure_bucket(minio_client, VIDEO_BUCKET)
            ensure_bucket(minio_client, FRAME_BUCKET)
            local_video_path = os.path.join(tmpdir, video_uri)
            minio_client.fget_object(VIDEO_BUCKET, video_uri, local_video_path)
            temp_segment_path = os.path.join(tmpdir, f"segment_{segment_id}.mp4")
            ffmpeg.input(local_video_path, ss=start_time).output(
                temp_segment_path, t=duration, vcodec='libx264', an=None
            ).overwrite_output().run(capture_stdout=True, capture_stderr=True)
            frames_output_dir = os.path.join(tmpdir, "frames")
            os.makedirs(frames_output_dir, exist_ok=True)
            extractor = GStreamerFileExtractor()
            extractor.extract_frames(temp_segment_path, frames_output_dir)
            video_basename = os.path.splitext(os.path.basename(video_uri))[0]
            cid = camera_id or video_basename
            date_str = datetime.utcnow().strftime("%Y-%m-%d")

            # Sort frames to ensure correct sequence
            frame_files = sorted([f for f in os.listdir(frames_output_dir) if f.endswith(".jpg")])
            for seq_num, frame_file in enumerate(frame_files):
                local_frame_path = os.path.join(frames_output_dir, frame_file)
                minio_object_name = f"{tenant_id}/{cid}/{date_str}/{video_basename}/segment_{segment_id:04d}/{frame_file}"
                upload_ok = dsai_upload_frame_with_retry(minio_client, FRAME_BUCKET, minio_object_name, local_frame_path)
                if upload_ok:
                    timestamp = start_time + seq_num / EXTRACTION_FPS
                    uploaded_frames.append({
                        "object_name": minio_object_name,
                        "timestamp": timestamp,
                        "sequence_number": seq_num
                    })

            print(f"[{EXTRACTOR_ID}] Finished segment {segment_id} and uploaded {len(uploaded_frames)} frames to MinIO.")

            # Publish FrameReadyEvent
            if uploaded_frames:
                publish_frame_ready_event(
                    video_id=video_basename,
                    segment_id=segment_id,
                    frame_paths=[f["object_name"] for f in uploaded_frames],
                    timestamps=[f["timestamp"] for f in uploaded_frames],
                    sequence_numbers=[f["sequence_number"] for f in uploaded_frames],
                    bucket_name=FRAME_BUCKET,
                    tenant_id=tenant_id,
                    camera_id=cid
                )

        except Exception:
            traceback.print_exc()
        finally:
            with httpx.Client() as client:
                client.post(f"{REGISTRY_URL}/update_status?extractor_id={EXTRACTOR_ID}&status=available")
            _job_slots.release()

def run_rtsp_extraction_job(rtsp_url: str, stream_id: str, stream_event: threading.Event,
                            tenant_id: str = "default", camera_id: Optional[str] = None):
    """Background task to process a live RTSP stream. Runs alongside other
    concurrent RTSP streams in this same process, up to the soft/hard limit --
    see _active_rtsp_streams. Not gated by _job_slots (that's for file jobs)
    and doesn't flip the registry's file-job busy/available status, since RTSP
    capacity is tracked separately via _rtsp_effective_limit()/GET /rtsp_status."""
    clean_minio_url = MINIO_URL.replace("http://", "").replace("https://", "")
    minio_client = Minio(clean_minio_url, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
    ensure_bucket(minio_client, FRAME_BUCKET)

    cid = camera_id or stream_id
    video_id = cid

    backoff = 2
    max_backoff = 32
    try:
        while not stream_event.is_set():
            extractor = GStreamerRtspExtractor(
                rtsp_url=rtsp_url,
                video_id=video_id,
                minio_client=minio_client,
                bucket_name=FRAME_BUCKET,
                shutdown_event=stream_event,
                tenant_id=tenant_id,
                camera_id=cid
            )
            try:
                extractor.start()
            except Exception as e:
                print(f"[{EXTRACTOR_ID}] Error during RTSP extraction job: {e}")

            if stream_event.is_set():
                break

            print(f"[{EXTRACTOR_ID}] RTSP stream disconnected for {rtsp_url}, retrying in {backoff}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
    finally:
        with _rtsp_lock:
            _active_rtsp_streams.pop(stream_id, None)
            if cid in _active_camera_streams and _active_camera_streams[cid] == stream_id:
                _active_camera_streams.pop(cid, None)
        print(f"[{EXTRACTOR_ID}] RTSP job for {rtsp_url} has concluded.")

# --- FASTAPI APPLICATION SETUP ---
from deepSightAI.Trinetra.Shared.Middleware import require_auth, RequestIDMiddleware
from deepSightAI.Trinetra.Shared.ErrorHandlers import register_error_handlers
AUTH_AVAILABLE = True

app = FastAPI(
    title="Extractor Service",
    dependencies=[Depends(require_auth)]
)
app.add_middleware(RequestIDMiddleware)
register_error_handlers(app)

_heartbeat_thread = None


def start_heartbeat_thread(interval: float = 30.0) -> threading.Thread:
    """Starts a background daemon thread reporting heartbeats to central registry every 30s."""
    global _heartbeat_thread
    if _heartbeat_thread is not None and _heartbeat_thread.is_alive():
        return _heartbeat_thread

    def _loop():
        while not shutdown_event.is_set():
            try:
                with httpx.Client(timeout=5.0) as client:
                    client.post(
                        f"{REGISTRY_URL}/heartbeat",
                        params={"worker_id": EXTRACTOR_ID, "worker_type": "extractor"}
                    )
            except Exception:
                pass
            shutdown_event.wait(interval)

    _heartbeat_thread = threading.Thread(target=_loop, daemon=True, name="extractor-heartbeat")
    _heartbeat_thread.start()
    return _heartbeat_thread

@app.on_event("startup")
def on_startup():
    """Register the extractor with the central registry and start heartbeat thread on startup."""
    try:
        with httpx.Client() as client:
            client.post(f"{REGISTRY_URL}/register", json={"extractor_id": EXTRACTOR_ID, "extractor_url": EXTRACTOR_URL})
    except Exception as e:
        print(f"[{EXTRACTOR_ID}] Failed to register with registry on startup: {e}")
    start_heartbeat_thread()

def dsai_validate_extractor_tenant(http_request: Optional[Request], requested_tenant_id: Optional[str]) -> str:
    """Ensure incoming extraction job matches authenticated tenant token (AUTH-50)."""
    if http_request is None:
        return requested_tenant_id or "default"
    auth_user = getattr(http_request.state, "user", {}) or {}
    auth_tenant = getattr(http_request.state, "tenant_id", None) or auth_user.get("tenant_id")
    if not auth_tenant:
        return requested_tenant_id or "default"

    user_roles = auth_user.get("roles", []) if isinstance(auth_user, dict) else []
    is_admin = "admin" in user_roles or "system" in user_roles

    if requested_tenant_id and requested_tenant_id != auth_tenant and not is_admin:
        raise HTTPException(
            status_code=403,
            detail=f"Tenant mismatch in extraction request: authenticated as '{auth_tenant}', cannot process for '{requested_tenant_id}'"
        )
    return requested_tenant_id if (requested_tenant_id and is_admin) else auth_tenant


@app.post("/extract")
def extract(request: FileJobRequest, background_tasks: BackgroundTasks, http_request: Request = None):
    """Endpoint to start a job for a video file segment."""
    enforced_tenant = dsai_validate_extractor_tenant(http_request, request.tenant_id)
    background_tasks.add_task(
        run_file_extraction_job,
        request.video_uri,
        request.segment_id,
        request.start_time,
        request.duration,
        enforced_tenant,
        request.camera_id
    )
    return {"message": "Job for file segment started."}

@app.post("/extract_stream")
def extract_stream(request: RtspJobRequest, background_tasks: BackgroundTasks, http_request: Request = None):
    """Endpoint to start a job for an RTSP stream. Rejected with 503 if this
    extractor is already at its effective RTSP capacity (soft limit if
    degraded, hard limit otherwise)."""
    enforced_tenant = dsai_validate_extractor_tenant(http_request, request.tenant_id)
    with _rtsp_lock:
        if len(_active_rtsp_streams) >= _rtsp_effective_limit():
            raise HTTPException(status_code=503, detail="Extractor at RTSP stream capacity")
        stream_id = f"{EXTRACTOR_ID}-rtsp-{uuid.uuid4().hex[:8]}"
        stream_event = threading.Event()
        _active_rtsp_streams[stream_id] = stream_event
        if request.camera_id:
            _active_camera_streams[request.camera_id] = stream_id

    background_tasks.add_task(
        run_rtsp_extraction_job,
        request.rtsp_url,
        stream_id,
        stream_event,
        enforced_tenant,
        request.camera_id
    )
    return {"message": "Job for RTSP stream started.", "stream_id": stream_id}

@app.get("/rtsp_status")
def rtsp_status():
    """Current RTSP capacity: how many streams are active vs. the configured
    limits, and whether auto-throttling has kicked in."""
    degraded = _rtsp_is_degraded()
    with _rtsp_lock:
        current_used = len(_active_rtsp_streams)
    return {
        "current_used": current_used,
        "soft_limit": RTSP_SOFT_LIMIT,
        "hard_limit": RTSP_HARD_LIMIT,
        "effective_limit": RTSP_SOFT_LIMIT if degraded else RTSP_HARD_LIMIT,
        "degraded": degraded,
    }


@app.post("/stop_stream/{stream_id}")
def dsai_stop_stream(stream_id: str):
    """Endpoint to stop an active RTSP stream by stream_id."""
    with _rtsp_lock:
        dsai_stream_event = _active_rtsp_streams.get(stream_id)
        if not dsai_stream_event:
            raise HTTPException(status_code=404, detail=f"Active stream '{stream_id}' not found on this extractor.")
        dsai_stream_event.set()
    return {"message": f"Stop signal dispatched to stream '{stream_id}'.", "stream_id": stream_id}


@app.post("/stop_camera/{camera_id}")
def dsai_stop_camera(camera_id: str):
    """Endpoint to stop an active RTSP stream by camera_id."""
    with _rtsp_lock:
        dsai_stream_id = _active_camera_streams.get(camera_id)
        if not dsai_stream_id or dsai_stream_id not in _active_rtsp_streams:
            raise HTTPException(status_code=404, detail=f"Active stream for camera '{camera_id}' not found on this extractor.")
        dsai_stream_event = _active_rtsp_streams[dsai_stream_id]
        dsai_stream_event.set()
    return {"message": f"Stop signal dispatched for camera '{camera_id}'.", "camera_id": camera_id, "stream_id": dsai_stream_id}


# --- HEALTH & READINESS PROBES (REL-63) ---
@app.get("/health")
def dsai_health():
    """Liveness probe (REL-63)."""
    return {"status": "healthy", "service": "ServerAndExtractor.extractor"}


@app.get("/ready")
def dsai_ready():
    """Readiness probe (REL-63)."""
    return {
        "status": "ready",
        "service": "ServerAndExtractor.extractor",
        "extractor_id": EXTRACTOR_ID,
        "active_rtsp": len(_active_rtsp_streams)
    }


# --- MAIN THREAD SIGNAL HANDLING ---
def handle_signal(signum, frame):
    """Signal handler that stops every active RTSP stream in this process."""
    print(f"Main thread received signal {signum}, stopping all active RTSP streams.")
    shutdown_event.set()
    with _rtsp_lock:
        for stream_event in _active_rtsp_streams.values():
            stream_event.set()

# Register signal handlers in the main thread
signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)