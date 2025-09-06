import os
import gi
import uvicorn
import httpx
import ffmpeg
import sys
import tempfile
import time
import traceback
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from minio import Minio
from minio.error import S3Error
import signal
import threading

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

# --- Graceful Shutdown Event ---
# This event will be set by the main thread's signal handler
shutdown_event = threading.Event()

def ensure_bucket(minio_client, bucket_name):
    """Helper function to create a Minio bucket if it doesn't already exist."""
    try:
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
    except S3Error as err:
        if err.code != "BucketAlreadyOwnedByYou":
            raise

# --- CLASS FOR VIDEO FILE EXTRACTION (UNCHANGED) ---
class GStreamerFileExtractor:
    """Extracts frames from a local video file and saves them to a directory."""
    def extract_frames(self, input_file, output_dir):
        file_uri = f"file://{os.path.abspath(input_file)}"
        pipeline_desc = f"""
        uridecodebin uri="{file_uri}" ! videoconvert ! videorate ! video/x-raw,framerate=1/1 !
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
    def __init__(self, rtsp_url, minio_client, bucket_name):
        self.rtsp_url = rtsp_url
        self.minio_client = minio_client
        self.bucket_name = bucket_name
        self.loop = GLib.MainLoop()
        self.pipeline = None

    def on_message(self, bus, message):
        """Callback to handle messages from the GStreamer bus."""
        msg_type = message.type
        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"[{EXTRACTOR_ID}] GStreamer error (RTSP): {err} {debug}")
            self.stop()
        elif msg_type == Gst.MessageType.EOS:
            print(f"[{EXTRACTOR_ID}] End-of-stream reached for RTSP.")
            self.stop()

    def on_new_sample(self, sink):
        """Callback triggered when a new frame is available from the appsink."""
        sample = sink.emit("pull-sample")
        if sample:
            buffer = sample.get_buffer()
            try:
                success, map_info = buffer.map(Gst.MapFlags.READ)
                if success:
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=True) as tmpfile:
                        tmpfile.write(map_info.data)
                        tmpfile.flush()
                        frame_name = f"frame_{int(time.time() * 1000)}.jpg"
                        self.minio_client.fput_object(self.bucket_name, frame_name, tmpfile.name)
                        print(f"[{EXTRACTOR_ID}] Uploaded {frame_name} to bucket {self.bucket_name}")
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
            videoconvert ! videorate ! video/x-raw,framerate=1/5 !
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
            # Use a context to periodically check the shutdown event
            context = self.loop.get_context()
            while not shutdown_event.is_set():
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

class RtspJobRequest(BaseModel):
    rtsp_url: str

# --- BACKGROUND JOB FUNCTIONS ---
def run_file_extraction_job(video_uri: str, segment_id: int, start_time: float, duration: float):
    """Background task to process a segment of a video file from Minio."""
    # This function remains unchanged.
    with httpx.Client() as client:
        client.post(f"{REGISTRY_URL}/update_status?extractor_id={EXTRACTOR_ID}&status=busy")
    
    clean_minio_url = MINIO_URL.replace("http://", "").replace("https://", "")
    minio_client = Minio(clean_minio_url, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
    
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
            video_basename = os.path.splitext(video_uri)[0]
            for frame_file in sorted(os.listdir(frames_output_dir)): # Sort frames before uploading
                if frame_file.endswith(".jpg"):
                    local_frame_path = os.path.join(frames_output_dir, frame_file)
                    # New naming convention: video/segment_id/frame_name
                    minio_object_name = f"{video_basename}/segment_{segment_id:04d}/{frame_file}"
                    minio_client.fput_object(FRAME_BUCKET, minio_object_name, local_frame_path)
            print(f"[{EXTRACTOR_ID}] Finished segment {segment_id} and uploaded frames to MinIO.")
        except Exception:
            traceback.print_exc()
        finally:
            with httpx.Client() as client:
                client.post(f"{REGISTRY_URL}/update_status?extractor_id={EXTRACTOR_ID}&status=available")

def run_rtsp_extraction_job(rtsp_url: str):
    """Background task to process a live RTSP stream."""
    shutdown_event.clear() # Ensure the event is not set from a previous run
    with httpx.Client() as client:
        client.post(f"{REGISTRY_URL}/update_status?extractor_id={EXTRACTOR_ID}&status=busy")
    
    clean_minio_url = MINIO_URL.replace("http://", "").replace("https://", "")
    minio_client = Minio(clean_minio_url, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
    rtsp_bucket = f"frames-rtsp-{EXTRACTOR_ID}-{int(time.time())}"
    
    extractor = GStreamerRtspExtractor(rtsp_url, minio_client, rtsp_bucket)
    try:
        extractor.start()
    except Exception as e:
        print(f"[{EXTRACTOR_ID}] Error during RTSP extraction job: {e}")
    finally:
        with httpx.Client() as client:
            client.post(f"{REGISTRY_URL}/update_status?extractor_id={EXTRACTOR_ID}&status=available")
        print(f"[{EXTRACTOR_ID}] RTSP job for {rtsp_url} has concluded.")

# --- FASTAPI APPLICATION SETUP ---
app = FastAPI(title="Extractor Service")

@app.on_event("startup")
def on_startup():
    """Register the extractor with the central registry on startup."""
    with httpx.Client() as client:
        client.post(f"{REGISTRY_URL}/register", json={"extractor_id": EXTRACTOR_ID, "extractor_url": EXTRACTOR_URL})

@app.post("/extract")
def extract(request: FileJobRequest, background_tasks: BackgroundTasks):
    """Endpoint to start a job for a video file segment."""
    background_tasks.add_task(run_file_extraction_job, request.video_uri, request.segment_id, request.start_time, request.duration)
    return {"message": "Job for file segment started."}

@app.post("/extract_stream")
def extract_stream(request: RtspJobRequest, background_tasks: BackgroundTasks):
    """Endpoint to start a job for an RTSP stream."""
    background_tasks.add_task(run_rtsp_extraction_job, request.rtsp_url)
    return {"message": "Job for RTSP stream started."}

# --- MAIN THREAD SIGNAL HANDLING ---
def handle_signal(signum, frame):
    """Signal handler that sets the global shutdown event."""
    print(f"Main thread received signal {signum}, setting shutdown event.")
    shutdown_event.set()

# Register signal handlers in the main thread
signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)