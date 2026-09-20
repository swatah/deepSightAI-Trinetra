import os
import gi
import uvicorn
import httpx
import ffmpeg
import sys
import tempfile
import time
import traceback
import uuid
from collections import deque
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from minio import Minio
from minio.error import S3Error
import signal
import threading
from shared.streaming.producer import StreamProducer
from shared.streaming.schema import FrameReadyEvent
from shared.config import get as get_config

# --- GStreamer and GObject Imports ---
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
Gst.init(None)

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
    """Helper function to create a Minio bucket if it doesn't already exist."""
    try:
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
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


def publish_frame_ready_event(video_id: str, segment_id: int, frame_paths: list,
                               timestamps: list, sequence_numbers: list,
                               bucket_name: str = None,
                               tenant_id: str = "default",
                               camera_id: str = None,
                               correlation_id: str = None):
    """
    Publish FrameReadyEvent to Redis Streams.
    """
    if bucket_name is None:
        bucket_name = FRAME_BUCKET

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
        stream_name = os.getenv("FRAME_EVENTS_STREAM", "frames")
        producer = get_producer()
        producer.publish(stream_name, event)
        print(f"[{EXTRACTOR_ID}] Published FrameReadyEvent to {stream_name} for video {video_id}, segment {segment_id}")
    except Exception as e:
        print(f"[{EXTRACTOR_ID}] Failed to publish FrameReadyEvent: {e}")
        # Don't raise - best effort

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
                        self.minio_client.fput_object(self.bucket_name, frame_name, tmpfile.name)
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
class FileJobRequest(BaseModel):
    video_uri: str
    segment_id: int
    start_time: float
    duration: float
    tenant_id: str = "default"
    camera_id: Optional[str] = None

class RtspJobRequest(BaseModel):
    rtsp_url: str
    tenant_id: str = "default"
    camera_id: Optional[str] = None

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
                minio_client.fput_object(FRAME_BUCKET, minio_object_name, local_frame_path)
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
        print(f"[{EXTRACTOR_ID}] RTSP job for {rtsp_url} has concluded.")

# --- FASTAPI APPLICATION SETUP ---
# --- AUTH DEPENDENCY ---
try:
    from shared.middleware import require_auth
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    def require_auth():
        return {}

app = FastAPI(
    title="Extractor Service",
    dependencies=[Depends(require_auth)] if AUTH_AVAILABLE else []
)

@app.on_event("startup")
def on_startup():
    """Register the extractor with the central registry on startup."""
    with httpx.Client() as client:
        client.post(f"{REGISTRY_URL}/register", json={"extractor_id": EXTRACTOR_ID, "extractor_url": EXTRACTOR_URL})

@app.post("/extract")
def extract(request: FileJobRequest, background_tasks: BackgroundTasks):
    """Endpoint to start a job for a video file segment."""
    background_tasks.add_task(
        run_file_extraction_job,
        request.video_uri,
        request.segment_id,
        request.start_time,
        request.duration,
        request.tenant_id,
        request.camera_id
    )
    return {"message": "Job for file segment started."}

@app.post("/extract_stream")
def extract_stream(request: RtspJobRequest, background_tasks: BackgroundTasks):
    """Endpoint to start a job for an RTSP stream. Rejected with 503 if this
    extractor is already at its effective RTSP capacity (soft limit if
    degraded, hard limit otherwise)."""
    with _rtsp_lock:
        if len(_active_rtsp_streams) >= _rtsp_effective_limit():
            raise HTTPException(status_code=503, detail="Extractor at RTSP stream capacity")
        stream_id = f"{EXTRACTOR_ID}-rtsp-{uuid.uuid4().hex[:8]}"
        stream_event = threading.Event()
        _active_rtsp_streams[stream_id] = stream_event

    background_tasks.add_task(
        run_rtsp_extraction_job,
        request.rtsp_url,
        stream_id,
        stream_event,
        request.tenant_id,
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