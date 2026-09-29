"""
Enterprise Ingestion V3 — Live Multi-Camera E2E Test Runner
Executing all phases and gates of docs/testing/dsai_v3_live_e2e_test_plan.md
"""

import os
import sys
import time
import json
import signal
import shutil
import hashlib
import tempfile
import subprocess
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

# Test Configuration & Early Environment Guardrails
DSAI_TENANT_ID = "tenant_enterprise_demo"

# Scenario times are placed relative to the run start, so the edge push's captured_at is
# within the platform's real clock-skew limit (no skew override needed). The order
# north -> main -> east is set by the test; Gate 9 checks the times survive the pipeline intact.
DSAI_RUN_START = float(int(time.time()))
DSAI_WINDOW_START = DSAI_RUN_START - 12 * 60
DSAI_TS_NORTH = DSAI_WINDOW_START + 3 * 60
DSAI_TS_LOBBY = DSAI_WINDOW_START + 5 * 60
DSAI_TS_MAIN = DSAI_WINDOW_START + 7 * 60
DSAI_CONFIDENCE_THRESHOLD = 0.20
DSAI_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DSAI_REDIS_PORT = 6380
DSAI_POSTGRES_PORT = 5433
DSAI_MINIO_PORT = 9000
DSAI_MINIO_CONSOLE_PORT = 9001
DSAI_MEDIAMTX_PORT = 8554
DSAI_MILVUS_PORT = 19530
DSAI_EXTRACTOR_PORT = 8001
DSAI_EDGE_INGEST_PORT = 8003
DSAI_SEARCH_PORT = 8081

DSAI_DB_URL = f"postgresql://postgres:testpassword@localhost:{DSAI_POSTGRES_PORT}/deepSightAI_test"
DSAI_REDIS_URL = f"redis://localhost:{DSAI_REDIS_PORT}"
DSAI_MINIO_URL = f"localhost:{DSAI_MINIO_PORT}"

os.environ["DATABASE_URL"] = DSAI_DB_URL
os.environ["REDIS_URL"] = DSAI_REDIS_URL
os.environ["MINIO_URL"] = DSAI_MINIO_URL
os.environ["MILVUS_HOST"] = "localhost"
os.environ["MILVUS_PORT"] = str(DSAI_MILVUS_PORT)
os.environ["CUDA_VISIBLE_DEVICES"] = ""

from cryptography.hazmat.primitives.asymmetric import rsa as dsai_rsa
from cryptography.hazmat.primitives import serialization as dsai_serialization

DSAI_JWT_PRIV_KEY_PATH = "/tmp/dsai_test_jwt_priv.pem"
DSAI_JWT_PUB_KEY_PATH = "/tmp/dsai_test_jwt_pub.pem"

dsai_temp_rsa_key = dsai_rsa.generate_private_key(public_exponent=65537, key_size=2048)
with open(DSAI_JWT_PRIV_KEY_PATH, "wb") as dsai_f_priv:
    dsai_f_priv.write(dsai_temp_rsa_key.private_bytes(
        encoding=dsai_serialization.Encoding.PEM,
        format=dsai_serialization.PrivateFormat.PKCS8,
        encryption_algorithm=dsai_serialization.NoEncryption()
    ))
with open(DSAI_JWT_PUB_KEY_PATH, "wb") as dsai_f_pub:
    dsai_f_pub.write(dsai_temp_rsa_key.public_key().public_bytes(
        encoding=dsai_serialization.Encoding.PEM,
        format=dsai_serialization.PublicFormat.SubjectPublicKeyInfo
    ))

os.environ["JWT_PRIVATE_KEY_PATH"] = DSAI_JWT_PRIV_KEY_PATH
os.environ["JWT_PUBLIC_KEY_PATH"] = DSAI_JWT_PUB_KEY_PATH

import httpx
import redis
from minio import Minio
from pymilvus import connections, utility, Collection
import torch
import open_clip
from PIL import Image, ImageDraw

from deepSightAI.Trinetra.AuthService.auth_service import (
    init_db,
    get_db,
    EdgeDevice,
    Tenant,
    create_access_token,
)
from deepSightAI.Trinetra.Shared.DB import (
    init_tenant_schema,
    get_tenant_connection,
    get_tenant_session,
    clear_engine_pool,
)
from deepSightAI.Trinetra.Shared.Repositories.CameraRepository import CameraRepository
from deepSightAI.Trinetra.Shared.Milvus import (
    ensure_tenant_collection,
    get_collection_name,
)

# Global process registry for guaranteed teardown
dsai_spawned_processes: List[subprocess.Popen] = []
dsai_milvus_server_obj = None
dsai_milvus_db_obj = None
dsai_temp_dirs: List[str] = []


def dsai_log(dsai_msg: str):
    """Standardized timestamped test logger."""
    dsai_now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{dsai_now_str}] {dsai_msg}", flush=True)


def dsai_get_gpu_vram_mb() -> int:
    """Read current NVIDIA GPU memory usage in MB."""
    try:
        dsai_out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        return int(dsai_out.split("\n")[0])
    except Exception:
        return 0


def dsai_cleanup_all():
    """Fail-safe cleanup hook ensuring zero zombie processes and isolated teardown."""
    dsai_log("Executing Phase 6: Automated Teardown & Resource Pruning...")

    # 1. Terminate spawned subprocesses. Each was started in its own process group, so the
    #    whole group (including any children) is stopped without touching other host processes.
    for dsai_proc in dsai_spawned_processes:
        try:
            if dsai_proc.poll() is None:
                os.killpg(os.getpgid(dsai_proc.pid), signal.SIGTERM)
                try:
                    dsai_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(dsai_proc.pid), signal.SIGKILL)
        except Exception as dsai_e:
            dsai_log(f"Warning stopping process {dsai_proc.pid}: {dsai_e}")

    # 2. Stop Milvus-Lite gRPC server
    global dsai_milvus_server_obj, dsai_milvus_db_obj
    if dsai_milvus_server_obj is not None:
        try:
            dsai_milvus_server_obj.stop(grace=1)
        except Exception:
            pass
    if dsai_milvus_db_obj is not None:
        try:
            dsai_milvus_db_obj.close()
        except Exception:
            pass

    # 4. Stop and remove test containers
    dsai_containers = ["dsai_test_redis", "dsai_test_postgres", "dsai_test_minio", "dsai_test_mediamtx"]
    for dsai_c in dsai_containers:
        try:
            subprocess.run(["docker", "rm", "-f", dsai_c], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        except Exception:
            pass

    # 5. Clean temporary files and directories
    try:
        subprocess.run("rm -f /tmp/dsai_test_e2e_*.mp4 /tmp/dsai_test_e2e_*.jpg /tmp/dsai_test_jwt_*.pem", shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        subprocess.run("rm -rf /tmp/dsai_test_e2e_frames_*", shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    except Exception:
        pass

    for dsai_dir in dsai_temp_dirs:
        try:
            shutil.rmtree(dsai_dir, ignore_errors=True)
        except Exception:
            pass

    clear_engine_pool()
    dsai_log("Automated teardown completed successfully.")


def dsai_signal_handler(dsai_signum, dsai_frame):
    dsai_cleanup_all()
    sys.exit(1)


signal.signal(signal.SIGINT, dsai_signal_handler)
signal.signal(signal.SIGTERM, dsai_signal_handler)


def dsai_wait_for_port(dsai_port: int, dsai_timeout: float = 30.0, dsai_name: str = "service") -> bool:
    """Poll TCP port until accessible."""
    import socket
    dsai_deadline = time.time() + dsai_timeout
    while time.time() < dsai_deadline:
        try:
            with socket.create_connection(("127.0.0.1", dsai_port), timeout=1.0):
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {dsai_name} on port {dsai_port}")


def dsai_wait_for_postgres(dsai_container_name: str = "dsai_test_postgres", dsai_timeout: float = 30.0) -> bool:
    """Wait until PostgreSQL is fully initialized and accepting queries."""
    dsai_deadline = time.time() + dsai_timeout
    while time.time() < dsai_deadline:
        dsai_res = subprocess.run(
            ["docker", "exec", dsai_container_name, "pg_isready", "-U", "postgres"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        if dsai_res.returncode == 0:
            time.sleep(1.0)
            return True
        time.sleep(0.5)
    raise TimeoutError("Timed out waiting for PostgreSQL container readiness")


def dsai_wait_for_redis(dsai_port: int = DSAI_REDIS_PORT, dsai_timeout: float = 30.0) -> bool:
    """Wait until Redis responds to PING."""
    dsai_deadline = time.time() + dsai_timeout
    while time.time() < dsai_deadline:
        try:
            dsai_r = redis.Redis(host="localhost", port=dsai_port)
            if dsai_r.ping():
                return True
        except Exception:
            time.sleep(0.5)
    raise TimeoutError("Timed out waiting for Redis readiness")


def dsai_wait_for_minio(dsai_url: str = DSAI_MINIO_URL, dsai_timeout: float = 30.0) -> bool:
    """Wait until MinIO responds to API calls."""
    dsai_deadline = time.time() + dsai_timeout
    while time.time() < dsai_deadline:
        try:
            dsai_m = Minio(dsai_url, access_key="minioadmin", secret_key="minioadmin", secure=False)
            dsai_m.list_buckets()
            return True
        except Exception:
            time.sleep(0.5)
    raise TimeoutError("Timed out waiting for MinIO readiness")



def dsai_fmt_ts(dsai_ts: float) -> str:
    return datetime.fromtimestamp(dsai_ts, tz=timezone.utc).strftime("%H:%M:%S")


def dsai_list_other_containers() -> List[str]:
    """Names of running containers that this test did not create."""
    dsai_out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    return sorted(dsai_n for dsai_n in dsai_out.split() if not dsai_n.startswith("dsai_test_"))


def dsai_probe_rtsp(dsai_url: str, dsai_timeout: float = 20.0) -> Tuple[str, float]:
    """Return (codec_name, frames_per_second) of the first video stream at an RTSP URL."""
    dsai_deadline = time.time() + dsai_timeout
    dsai_last_err = ""
    while time.time() < dsai_deadline:
        dsai_res = subprocess.run([
            "ffprobe", "-v", "error", "-rtsp_transport", "tcp", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,r_frame_rate", "-of", "json", dsai_url
        ], capture_output=True, text=True, timeout=15)
        try:
            dsai_stream = json.loads(dsai_res.stdout)["streams"][0]
            dsai_num, dsai_den = dsai_stream["r_frame_rate"].split("/")
            return dsai_stream["codec_name"], float(dsai_num) / float(dsai_den)
        except Exception:
            dsai_last_err = dsai_res.stderr.strip()
            time.sleep(1.0)
    raise AssertionError(f"RTSP stream {dsai_url} not available: {dsai_last_err}")


def dsai_frame_events_by_camera(dsai_r, dsai_since_ms: int) -> Dict[str, int]:
    """Count FrameReadyEvents per camera in the Redis 'frames' stream since a given time."""
    dsai_counts: Dict[str, int] = {}
    for _, dsai_fields in dsai_r.xrange("frames", min=f"{dsai_since_ms}-0", max="+"):
        dsai_raw = dsai_fields.get(b"event") or dsai_fields.get("event")
        if dsai_raw is None:
            continue
        dsai_cam = json.loads(dsai_raw).get("camera_id")
        dsai_counts[dsai_cam] = dsai_counts.get(dsai_cam, 0) + 1
    return dsai_counts


def dsai_search_text(dsai_headers: Dict[str, str], dsai_t0: float, dsai_t1: float,
                     dsai_camera_ids: Optional[List[str]] = None, dsai_top_k: int = 30) -> List[Dict[str, Any]]:
    dsai_body: Dict[str, Any] = {
        "query_text": "a red car", "time_start": dsai_t0, "time_end": dsai_t1,
        "top_k": dsai_top_k, "tenant_id": DSAI_TENANT_ID,
    }
    if dsai_camera_ids:
        dsai_body["camera_ids"] = dsai_camera_ids
    dsai_resp = httpx.post(f"http://127.0.0.1:{DSAI_SEARCH_PORT}/search/text", json=dsai_body,
                           headers=dsai_headers, timeout=30.0)
    # SearchService returns 503 on backend failure, so a failure can no longer pass as "0 hits".
    assert dsai_resp.status_code == 200, f"Search failed ({dsai_resp.status_code}): {dsai_resp.text}"
    return dsai_resp.json()


def dsai_generate_red_car_image(dsai_out_path: str):
    """Draw a recognizable red vehicle on a road background for OpenCLIP feature extraction."""
    dsai_im = Image.new("RGB", (640, 360), color=(180, 180, 180))
    dsai_draw = ImageDraw.Draw(dsai_im)
    # road
    dsai_draw.rectangle([0, 240, 640, 360], fill=(50, 50, 50))
    # car lower body (red)
    dsai_draw.rounded_rectangle([150, 180, 480, 260], radius=10, fill=(220, 20, 20))
    # car cabin (red)
    dsai_draw.polygon([(220, 180), (270, 120), (390, 120), (440, 180)], fill=(200, 15, 15))
    # windows
    dsai_draw.polygon([(230, 175), (275, 125), (325, 125), (325, 175)], fill=(150, 200, 230))
    dsai_draw.polygon([(335, 175), (335, 125), (385, 125), (430, 175)], fill=(150, 200, 230))
    # wheels
    dsai_draw.ellipse([200, 240, 260, 300], fill=(20, 20, 20))
    dsai_draw.ellipse([215, 255, 245, 285], fill=(180, 180, 180))
    dsai_draw.ellipse([370, 240, 430, 300], fill=(20, 20, 20))
    dsai_draw.ellipse([385, 255, 415, 285], fill=(180, 180, 180))
    # headlight
    dsai_draw.polygon([(475, 200), (480, 200), (480, 220), (475, 220)], fill=(255, 255, 100))
    dsai_im.save(dsai_out_path)


def dsai_run_e2e_pipeline() -> Dict[str, Any]:
    """Execute all 6 phases and 10 verification gates of the live test plan."""
    dsai_initial_vram = dsai_get_gpu_vram_mb()
    dsai_initial_containers = dsai_list_other_containers()
    dsai_log(f"Initial Host Baseline: GPU VRAM = {dsai_initial_vram} MB, other containers = {dsai_initial_containers}")

    dsai_gate_results: Dict[str, bool] = {}
    dsai_trajectory_report: List[Dict[str, Any]] = []

    try:
        # =====================================================================
        # PHASE 1: Environment & Backing Services Setup
        # =====================================================================
        dsai_log("=== PHASE 1: Environment Isolation & Provisioning ===")

        # 1.1 Redis 7 on Port 6380
        dsai_log("Starting isolated Redis container on port 6380...")
        subprocess.run([
            "docker", "run", "-d", "--name", "dsai_test_redis",
            "--memory=256m",
            "-p", f"{DSAI_REDIS_PORT}:6379",
            "redis:7-alpine", "redis-server", "--maxmemory", "200mb", "--maxmemory-policy", "allkeys-lru"
        ], check=True, stdout=subprocess.DEVNULL)
        dsai_wait_for_redis(DSAI_REDIS_PORT)

        # 1.2 PostgreSQL 16 on Port 5433
        dsai_log("Starting isolated PostgreSQL container on port 5433...")
        subprocess.run([
            "docker", "run", "-d", "--name", "dsai_test_postgres",
            "--memory=512m",
            "-e", "POSTGRES_USER=postgres",
            "-e", "POSTGRES_PASSWORD=testpassword",
            "-e", "POSTGRES_DB=deepSightAI_test",
            "-p", f"{DSAI_POSTGRES_PORT}:5432",
            "postgres:16-alpine"
        ], check=True, stdout=subprocess.DEVNULL)
        dsai_wait_for_postgres("dsai_test_postgres")

        # 1.3 MinIO on Port 9000
        dsai_log("Starting isolated MinIO container on port 9000...")
        subprocess.run([
            "docker", "run", "-d", "--name", "dsai_test_minio",
            "--memory=256m",
            "-e", "MINIO_ROOT_USER=minioadmin",
            "-e", "MINIO_ROOT_PASSWORD=minioadmin",
            "-p", f"{DSAI_MINIO_PORT}:9000",
            "-p", f"{DSAI_MINIO_CONSOLE_PORT}:9001",
            "quay.io/minio/minio:latest", "server", "/data"
        ], check=True, stdout=subprocess.DEVNULL)
        dsai_wait_for_minio(DSAI_MINIO_URL)

        # 1.4 Milvus-Lite gRPC server on Port 19530
        dsai_log("Starting Milvus-Lite gRPC server on port 19530...")
        global dsai_milvus_server_obj, dsai_milvus_db_obj
        dsai_milvus_data_dir = tempfile.mkdtemp(prefix="dsai_milvus_data_")
        dsai_temp_dirs.append(dsai_milvus_data_dir)
        from milvus_lite.adapter.grpc import server as dsai_milvus_grpc
        dsai_milvus_server_obj, dsai_milvus_db_obj, _ = dsai_milvus_grpc.start_server_in_thread(
            dsai_milvus_data_dir, host="127.0.0.1", port=DSAI_MILVUS_PORT
        )
        dsai_wait_for_port(DSAI_MILVUS_PORT, dsai_name="Milvus-Lite gRPC")
        dsai_log("Milvus-Lite gRPC server operational.")

        # 1.5 Database Seeding
        dsai_log("Seeding database schema, tenant, camera registry, and edge credentials...")
        os.environ["DATABASE_URL"] = DSAI_DB_URL
        os.environ["REDIS_URL"] = DSAI_REDIS_URL
        os.environ["MINIO_URL"] = DSAI_MINIO_URL
        os.environ["MILVUS_HOST"] = "localhost"
        os.environ["MILVUS_PORT"] = str(DSAI_MILVUS_PORT)
        os.environ["REGISTRY_URL"] = "http://localhost:8000"

        # Initialize public tables (tenants, edge_devices, etc.)
        init_db(DSAI_DB_URL)

        # Initialize tenant schema
        init_tenant_schema(DSAI_TENANT_ID)

        # Seed tenant in public schema
        with get_tenant_session("public")() as dsai_session:
            dsai_existing_tenant = dsai_session.query(Tenant).filter_by(slug=DSAI_TENANT_ID).first()
            if not dsai_existing_tenant:
                dsai_new_tenant = Tenant(
                    name="Enterprise Demo",
                    slug=DSAI_TENANT_ID,
                    description="Enterprise test tenant",
                    active=True,
                    plugin_config={}
                )
                dsai_session.add(dsai_new_tenant)
                dsai_session.commit()

        # Seed cameras in tenant schema
        dsai_cam_repo = CameraRepository(tenant_id=DSAI_TENANT_ID)
        for dsai_cid, dsai_cname, dsai_rurl, dsai_cpath in [
            ("cam_north_gate", "North Gate Camera", "rtsp://localhost:8554/live/cam_north_gate", "pull"),
            ("cam_main_ave", "Main Avenue Camera", "rtsp://localhost:8554/live/cam_main_ave", "pull"),
            ("cam_east_perimeter", "East Perimeter Camera", None, "push"),
            ("cam_lobby_indoor", "Lobby Indoor Negative Control", "rtsp://localhost:8554/live/cam_lobby_indoor", "pull")
        ]:
            if not dsai_cam_repo.get(dsai_cid):
                dsai_cam_repo.create(
                    camera_id=dsai_cid,
                    name=dsai_cname,
                    rtsp_url=dsai_rurl,
                    location="Facility",
                    is_active=True,
                    ingestion_path=dsai_cpath
                )

        # Seed edge device in public schema
        dsai_edge_key = "test_edge_key_east_01"
        dsai_edge_hash = hashlib.sha256(dsai_edge_key.encode("utf-8")).hexdigest()
        with get_tenant_session("public")() as dsai_session:
            dsai_existing_device = dsai_session.query(EdgeDevice).filter_by(device_id="edge_dev_east_01").first()
            if not dsai_existing_device:
                dsai_new_device = EdgeDevice(
                    device_id="edge_dev_east_01",
                    tenant_id=DSAI_TENANT_ID,
                    name="East Perimeter Edge Sensor",
                    api_key_prefix=dsai_edge_key[:12],
                    api_key_hash=dsai_edge_hash,
                    assigned_cameras=["cam_east_perimeter"],
                    revoked=False,
                    failed_auth_count=0
                )
                dsai_session.add(dsai_new_device)
                dsai_session.commit()

        # Seed MinIO buckets
        dsai_minio_client = Minio(DSAI_MINIO_URL, access_key="minioadmin", secret_key="minioadmin", secure=False)
        for dsai_bucket in ["frames", "videos"]:
            if not dsai_minio_client.bucket_exists(dsai_bucket):
                dsai_minio_client.make_bucket(dsai_bucket)

        # Ensure Milvus Collection
        ensure_tenant_collection(
            tenant_id=DSAI_TENANT_ID,
            embedding_dim=512,
            milvus_host="localhost",
            milvus_port=str(DSAI_MILVUS_PORT)
        )
        dsai_log("Phase 1 complete: All backing services & schemas initialized.")

        # =====================================================================
        # PHASE 2: 30 fps Multi-Codec Video Generation & RTSP Streaming
        # =====================================================================
        dsai_log("=== PHASE 2: 30 fps Multi-Codec Video Generation & RTSP Streaming ===")

        # 2.0 Acquire real CCTV surveillance footage assets
        dsai_car_source_video = "/tmp/intel_car_detection.mp4"
        if not os.path.exists(dsai_car_source_video):
            dsai_log("Downloading real CCTV vehicle surveillance footage...")
            subprocess.run([
                "curl", "-s", "-L", "-o", dsai_car_source_video,
                "https://raw.githubusercontent.com/intel-iot-devkit/sample-videos/master/car-detection.mp4"
            ], check=True)

        dsai_people_source_video = "/tmp/intel_people_detection.mp4"
        if not os.path.exists(dsai_people_source_video):
            dsai_log("Downloading real CCTV lobby pedestrian surveillance footage...")
            subprocess.run([
                "curl", "-s", "-L", "-o", dsai_people_source_video,
                "https://raw.githubusercontent.com/intel-iot-devkit/sample-videos/master/people-detection.mp4"
            ], check=True)

        # 2.1 H.264 @ 30 fps video (Camera 01: North Gate - Real Red Car Ingress)
        dsai_h264_clip = "/tmp/dsai_test_e2e_red_car_h264_30fps.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-ss", "14.5", "-t", "5", "-i", dsai_car_source_video,
            "-vf", "drawtext=text='CAM_NORTH_GATE 11-18 (30fps)':fontcolor=white:fontsize=22:x=20:y=20",
            "-c:v", "libx264", "-g", "1", "-x264-params", "repeat-headers=1:keyint=1", "-r", "30", "-pix_fmt", "yuv420p", dsai_h264_clip
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 2.2 H.265 (HEVC) @ 30 fps video (Camera 02: Main Ave - Real Red Car Transiting, Downstream Perspective)
        dsai_h265_clip = "/tmp/dsai_test_e2e_red_car_h265_30fps.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-ss", "15.0", "-t", "5", "-i", dsai_car_source_video,
            "-vf", "crop=in_w*0.9:in_h*0.9:in_w*0.05:in_h*0.05,drawtext=text='CAM_MAIN_AVE 11-22 (30fps)':fontcolor=white:fontsize=22:x=20:y=20",
            "-c:v", "libx265", "-x265-params", "repeat-headers=1:keyint=1", "-tag:v", "hvc1", "-r", "30", "-pix_fmt", "yuv420p", dsai_h265_clip
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 2.3 Negative Control @ 30 fps (Camera 04: Lobby Pedestrians - Real Indoor Surveillance)
        dsai_ctrl_clip = "/tmp/dsai_test_e2e_control_h264_30fps.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-ss", "0", "-t", "5", "-i", dsai_people_source_video,
            "-vf", "drawtext=text='CAM_LOBBY 11-20 (30fps)':fontcolor=yellow:fontsize=22:x=20:y=20",
            "-c:v", "libx264", "-g", "1", "-x264-params", "repeat-headers=1:keyint=1", "-r", "30", "-pix_fmt", "yuv420p", dsai_ctrl_clip
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Extract representative real red car frame for edge push embedding (Camera 03: East Perimeter)
        dsai_real_car_frame = "/tmp/dsai_test_e2e_real_east_car.jpg"
        subprocess.run([
            "ffmpeg", "-y", "-ss", "17.5", "-i", dsai_car_source_video,
            "-vframes", "1", dsai_real_car_frame
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 2.4 Start MediaMTX container
        dsai_log("Starting MediaMTX RTSP Server on port 8554...")
        subprocess.run([
            "docker", "run", "-d", "--name", "dsai_test_mediamtx",
            "-p", f"{DSAI_MEDIAMTX_PORT}:8554",
            "bluenviron/mediamtx:latest"
        ], check=True, stdout=subprocess.DEVNULL)
        dsai_wait_for_port(DSAI_MEDIAMTX_PORT, dsai_name="MediaMTX RTSP")

        # 2.5 Publish 30 fps RTSP streams via ffmpeg
        dsai_log("Publishing 30 fps RTSP feeds via ffmpeg loops...")
        dsai_streams = [
            (dsai_h264_clip, "rtsp://localhost:8554/live/cam_north_gate"),
            (dsai_h265_clip, "rtsp://localhost:8554/live/cam_main_ave"),
            (dsai_ctrl_clip, "rtsp://localhost:8554/live/cam_lobby_indoor")
        ]
        for dsai_input_clip, dsai_rtsp_target in dsai_streams:
            dsai_ffmpeg_proc = subprocess.Popen([
                "ffmpeg", "-re", "-stream_loop", "-1", "-i", dsai_input_clip,
                "-c", "copy", "-rtsp_transport", "tcp", "-f", "rtsp", dsai_rtsp_target
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            dsai_spawned_processes.append(dsai_ffmpeg_proc)

        # Gate 1: each feed must actually be served by MediaMTX with the expected codec at ~30 fps.
        for dsai_rtsp_target, dsai_expected_codec in [
            ("rtsp://localhost:8554/live/cam_north_gate", "h264"),
            ("rtsp://localhost:8554/live/cam_main_ave", "hevc"),
            ("rtsp://localhost:8554/live/cam_lobby_indoor", "h264"),
        ]:
            dsai_codec, dsai_fps = dsai_probe_rtsp(dsai_rtsp_target)
            dsai_log(f"Probed {dsai_rtsp_target}: codec={dsai_codec}, fps={dsai_fps:.2f}")
            assert dsai_codec == dsai_expected_codec, f"{dsai_rtsp_target}: expected {dsai_expected_codec}, got {dsai_codec}"
            assert 29.0 <= dsai_fps <= 31.0, f"{dsai_rtsp_target}: expected ~30 fps, got {dsai_fps}"
        dsai_gate_results["gate_1_cctv_ingress_30fps"] = True
        dsai_log("Gate 1 Passed: all 3 RTSP feeds served with expected codec at ~30 fps.")

        # =====================================================================
        # PHASE 3: Service Startup with CPU Mode & Safe Ports
        # =====================================================================
        dsai_log("=== PHASE 3: Microservice Startup (CPU Inference Only) ===")
        dsai_env = os.environ.copy()
        dsai_env["CUDA_VISIBLE_DEVICES"] = ""
        dsai_env["REDIS_URL"] = DSAI_REDIS_URL
        dsai_env["DATABASE_URL"] = DSAI_DB_URL
        dsai_env["MINIO_URL"] = DSAI_MINIO_URL
        dsai_env["MILVUS_HOST"] = "localhost"
        dsai_env["MILVUS_PORT"] = str(DSAI_MILVUS_PORT)
        dsai_env["REGISTRY_URL"] = "http://localhost:8000"
        dsai_env["EXTRACTION_FPS"] = "5"
        dsai_env["EMBEDDING_DIM"] = "512"
        dsai_env["RTSP_CAPACITY"] = "10"
        dsai_env["RTSP_HARD_LIMIT"] = "10"
        # Test-only: lets base_timestamp place frames at fixed scenario times (north, main, lobby).
        dsai_env["DSAI_ALLOW_CLIENT_FRAME_TIMESTAMPS"] = "true"

        dsai_repo_root = DSAI_REPO_ROOT

        # 3.1 Extractor Service (Port 8001)
        dsai_log("Starting Extractor Service (:8001)...")
        dsai_extractor_proc = subprocess.Popen([
            sys.executable, "-m", "uvicorn",
            "deepSightAI.Trinetra.ServerAndExtractor.extractor:app",
            "--host", "127.0.0.1", "--port", str(DSAI_EXTRACTOR_PORT),
            "--log-level", "warning"
        ], env=dsai_env, cwd=dsai_repo_root, start_new_session=True)
        dsai_spawned_processes.append(dsai_extractor_proc)
        dsai_wait_for_port(DSAI_EXTRACTOR_PORT, dsai_name="Extractor Service")

        # 3.2 Embedder Daemon (CPU OpenCLIP)
        dsai_log("Starting Embedder Daemon...")
        dsai_embedder_proc = subprocess.Popen([
            sys.executable, "-m", "deepSightAI.Trinetra.Embedder.embedder"
        ], env=dsai_env, cwd=dsai_repo_root, start_new_session=True)
        dsai_spawned_processes.append(dsai_embedder_proc)

        # 3.3 Edge Ingestion Service (Port 8003)
        dsai_log("Starting Edge Ingestion Service (:8003)...")
        dsai_edge_proc = subprocess.Popen([
            sys.executable, "-m", "uvicorn",
            "deepSightAI.Trinetra.ServerAndExtractor.main_api:app",
            "--host", "127.0.0.1", "--port", str(DSAI_EDGE_INGEST_PORT),
            "--log-level", "warning"
        ], env=dsai_env, cwd=dsai_repo_root, start_new_session=True)
        dsai_spawned_processes.append(dsai_edge_proc)
        dsai_wait_for_port(DSAI_EDGE_INGEST_PORT, dsai_name="Edge Ingestion Service")

        # 3.4 Search Service (Port 8081)
        dsai_log("Starting Search Service (:8081)...")
        dsai_search_proc = subprocess.Popen([
            sys.executable, "-m", "uvicorn",
            "deepSightAI.Trinetra.SearchService.main:app",
            "--host", "127.0.0.1", "--port", str(DSAI_SEARCH_PORT),
            "--log-level", "warning"
        ], env=dsai_env, cwd=dsai_repo_root, start_new_session=True)
        dsai_spawned_processes.append(dsai_search_proc)
        dsai_wait_for_port(DSAI_SEARCH_PORT, dsai_name="Search Service")
        dsai_log("Phase 3 complete: All services running on safe ports with CPU inference.")

        # =====================================================================
        # PHASE 4: Pull & Push Path Ingestion
        # =====================================================================
        dsai_log("=== PHASE 4: Dual-Path Ingestion & 5 fps GStreamer Decimation ===")

        # 4.1 Trigger Pull Streams
        dsai_extractor_token = create_access_token({
            "sub": "test_operator",
            "tenant_id": DSAI_TENANT_ID,
            "roles": ["admin"],
            "permissions": ["search:read", "extract:write"]
        })
        dsai_extractor_headers = {"Authorization": f"Bearer {dsai_extractor_token}"}

        dsai_log(f"Triggering RTSP extraction for North Gate (H.264 @ 30fps -> 5fps, {dsai_fmt_ts(DSAI_TS_NORTH)})...")
        dsai_resp_ng = httpx.post(
            f"http://127.0.0.1:{DSAI_EXTRACTOR_PORT}/extract_stream",
            json={
                "rtsp_url": "rtsp://localhost:8554/live/cam_north_gate",
                "camera_id": "cam_north_gate",
                "tenant_id": DSAI_TENANT_ID,
                "codec": "h264",
                "base_timestamp": DSAI_TS_NORTH
            },
            headers=dsai_extractor_headers,
            timeout=10.0
        )
        assert dsai_resp_ng.status_code == 200, f"Failed starting North Gate extraction: {dsai_resp_ng.text}"

        dsai_log(f"Triggering RTSP extraction for Main Avenue (H.265 @ 30fps -> 5fps, {dsai_fmt_ts(DSAI_TS_MAIN)})...")
        dsai_resp_ma = httpx.post(
            f"http://127.0.0.1:{DSAI_EXTRACTOR_PORT}/extract_stream",
            json={
                "rtsp_url": "rtsp://localhost:8554/live/cam_main_ave",
                "camera_id": "cam_main_ave",
                "tenant_id": DSAI_TENANT_ID,
                "codec": "h265",
                "base_timestamp": DSAI_TS_MAIN
            },
            headers=dsai_extractor_headers,
            timeout=10.0
        )
        assert dsai_resp_ma.status_code == 200, f"Failed starting Main Avenue extraction: {dsai_resp_ma.text}"

        dsai_log(f"Triggering RTSP extraction for Lobby Indoor (Negative Control @ 30fps -> 5fps, {dsai_fmt_ts(DSAI_TS_LOBBY)})...")
        dsai_resp_ctrl = httpx.post(
            f"http://127.0.0.1:{DSAI_EXTRACTOR_PORT}/extract_stream",
            json={
                "rtsp_url": "rtsp://localhost:8554/live/cam_lobby_indoor",
                "camera_id": "cam_lobby_indoor",
                "tenant_id": DSAI_TENANT_ID,
                "codec": "h264",
                "base_timestamp": DSAI_TS_LOBBY
            },
            headers=dsai_extractor_headers,
            timeout=10.0
        )
        assert dsai_resp_ctrl.status_code == 200, f"Failed starting Lobby extraction: {dsai_resp_ctrl.text}"

        # 4.2 Per-camera decimation rate from the Redis 'frames' stream
        dsai_r = redis.Redis(host="localhost", port=DSAI_REDIS_PORT)
        dsai_pull_cams = ["cam_north_gate", "cam_main_ave", "cam_lobby_indoor"]
        dsai_wait_frames_start = time.time()
        dsai_first_counts: Dict[str, int] = {}
        while time.time() - dsai_wait_frames_start < 60.0:
            dsai_first_counts = dsai_frame_events_by_camera(dsai_r, 0)
            if all(dsai_first_counts.get(dsai_c, 0) > 0 for dsai_c in dsai_pull_cams):
                break
            time.sleep(1.0)
        assert all(dsai_first_counts.get(dsai_c, 0) > 0 for dsai_c in dsai_pull_cams), \
            f"Not every pull camera produced frames within 60s: {dsai_first_counts}"

        dsai_sample_seconds = 6.0
        dsai_log(f"Sampling per-camera frame rate over {dsai_sample_seconds:.0f}s...")
        dsai_since_ms = int(time.time() * 1000)
        time.sleep(dsai_sample_seconds)
        dsai_counts = dsai_frame_events_by_camera(dsai_r, dsai_since_ms)
        for dsai_c in dsai_pull_cams:
            dsai_rate = dsai_counts.get(dsai_c, 0) / dsai_sample_seconds
            dsai_log(f"  {dsai_c}: {dsai_counts.get(dsai_c, 0)} frames -> {dsai_rate:.2f} fps")
            assert 3.5 <= dsai_rate <= 6.5, f"{dsai_c}: expected ~5 fps after decimation, observed {dsai_rate:.2f} fps"
        dsai_gate_results["gate_2_gstreamer_5fps_decimation"] = True
        dsai_log("Gate 2 Passed: every pull camera decimated to ~5 fps.")

        # 4.3 Push Path: Submit Camera 03 (East Perimeter, captured 30s ago)
        dsai_log("Computing OpenCLIP reference embedding for East Perimeter push path...")
        dsai_clip_model, _, dsai_clip_preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
        dsai_im_pil = Image.open(dsai_real_car_frame)
        with torch.no_grad():
            dsai_tensor = dsai_clip_preprocess(dsai_im_pil).unsqueeze(0)
            dsai_vec = dsai_clip_model.encode_image(dsai_tensor)
            dsai_vec = dsai_vec / dsai_vec.norm(dim=-1, keepdim=True)
            dsai_vector_list = dsai_vec.cpu().numpy().flatten().tolist()

        # Captured 30s before now: inside the default 300s clock-skew limit, so the timestamp is
        # stored as sent (Gate 9 checks this), not clamped.
        dsai_ts_east = float(int(time.time())) - 30.0
        dsai_log(f"Posting pre-computed edge embedding to POST /v1/edge/embeddings (captured_at {dsai_fmt_ts(dsai_ts_east)})...")
        dsai_push_payload = {
            "tenant_id": DSAI_TENANT_ID,
            "camera_id": "cam_east_perimeter",
            "event_id": "evt_push_redcar_112800",
            "captured_at": dsai_ts_east,
            "model_id": "ViT-B-32",
            "model_version": "1",
            "embedding_dim": 512,
            "embedding_vector": dsai_vector_list
        }
        dsai_push_headers = {
            "Content-Type": "application/json",
            "X-API-Key": dsai_edge_key,
            "X-Device-ID": "edge_dev_east_01"
        }
        dsai_push_resp = httpx.post(
            f"http://127.0.0.1:{DSAI_EDGE_INGEST_PORT}/v1/edge/embeddings",
            json=dsai_push_payload,
            headers=dsai_push_headers,
            timeout=10.0
        )
        assert dsai_push_resp.status_code == 200, f"Edge push failed: {dsai_push_resp.text}"
        dsai_gate_results["gate_5_edge_device_push"] = True
        dsai_log("Gate 5 Passed: Camera 03 (East Perimeter) edge embedding ingested successfully.")

        # 4.4 Negative Path: Path Conflict (Push to 'cam_north_gate' which is assigned to 'pull')
        dsai_log("Testing Negative Path: Attempting push ingestion to 'cam_north_gate' (assigned to pull)...")
        dsai_conflict_payload = dict(dsai_push_payload)
        dsai_conflict_payload["camera_id"] = "cam_north_gate"
        dsai_conflict_payload["event_id"] = "evt_conflict_north_gate"
        dsai_conflict_resp = httpx.post(
            f"http://127.0.0.1:{DSAI_EDGE_INGEST_PORT}/v1/edge/embeddings",
            json=dsai_conflict_payload,
            headers=dsai_push_headers,
            timeout=10.0
        )
        assert dsai_conflict_resp.status_code == 403, f"Expected 403 Forbidden on path conflict, got {dsai_conflict_resp.status_code}"
        dsai_gate_results["gate_6_negative_path_conflict"] = True
        dsai_log("Gate 6 Passed: Path conflict rejected with HTTP 403 Forbidden.")

        # =====================================================================
        # PHASE 5: Executing Search & Trajectory Reconstruction
        # =====================================================================
        dsai_log("=== PHASE 5: Time-Bounded Milvus Vector Search & Trajectory Reconstruction ===")

        # Wait for Embedder to process frames into Milvus
        dsai_log("Waiting for Milvus collection to index vectors from pull & push streams...")
        dsai_coll_name = get_collection_name(DSAI_TENANT_ID)
        connections.connect(alias="default", host="localhost", port=str(DSAI_MILVUS_PORT))
        dsai_coll = Collection(dsai_coll_name)
        
        dsai_all_cams = ["cam_north_gate", "cam_main_ave", "cam_east_perimeter", "cam_lobby_indoor"]
        dsai_indexed: Dict[str, bool] = {}
        dsai_wait_start = time.time()
        while time.time() - dsai_wait_start < 120.0:
            dsai_coll.flush()
            dsai_indexed = {
                dsai_c: len(dsai_coll.query(expr=f'camera_id == "{dsai_c}"', output_fields=["pk"], limit=1)) > 0
                for dsai_c in dsai_all_cams
            }
            if all(dsai_indexed.values()):
                break
            time.sleep(2.0)
        dsai_log(f"Milvus collection '{dsai_coll_name}' entity count: {dsai_coll.num_entities}; indexed per camera: {dsai_indexed}")
        assert all(dsai_indexed.values()), f"Not every camera reached Milvus within 120s: {dsai_indexed}"
        # Gates 3/4: each codec's camera went RTSP -> decode -> MinIO -> Redis -> embedder -> Milvus.
        dsai_gate_results["gate_3_h264_pull_ingestion"] = True
        dsai_gate_results["gate_4_h265_pull_ingestion"] = True
        dsai_log("Gates 3 & 4 Passed: H.264 and H.265 cameras indexed in Milvus.")

        # Generate JWT Bearer Token for SearchService with search:read permission
        dsai_search_token = create_access_token({
            "sub": "test_operator",
            "tenant_id": DSAI_TENANT_ID,
            "roles": ["operator"],
            "permissions": ["search:read"]
        })
        dsai_auth_header = {"Authorization": f"Bearer {dsai_search_token}"}

        # 5.1 In-window query ("a red car" from the window start until now)
        dsai_time_start = DSAI_WINDOW_START
        dsai_time_end = time.time()

        dsai_log(f"Executing text search: 'a red car' between {dsai_fmt_ts(dsai_time_start)} and {dsai_fmt_ts(dsai_time_end)} UTC...")
        dsai_hits = dsai_search_text(dsai_auth_header, dsai_time_start, dsai_time_end)
        dsai_log(f"Search returned {len(dsai_hits)} total hits inside the query window.")
        assert len(dsai_hits) > 0, "In-window search returned no hits"
        for dsai_idx, dsai_hit in enumerate(dsai_hits):
            dsai_log(f"Hit #{dsai_idx}: cam={dsai_hit.get('camera_id')}, video={dsai_hit.get('video_id')}, score={dsai_hit.get('score')}, ts={dsai_hit.get('frame_timestamp')}")

        # 5.2 Negative path: a window before any sighting must return 0 hits. This only means
        # something because the same query returned hits in-window above, and search now
        # returns 503 (not []) on failure.
        dsai_oob_start = DSAI_WINDOW_START - 60 * 60
        dsai_oob_end = DSAI_WINDOW_START - 30 * 60
        dsai_log(f"Testing Negative Path: window {dsai_fmt_ts(dsai_oob_start)}-{dsai_fmt_ts(dsai_oob_end)} UTC (before any sighting)...")
        dsai_oob_hits = dsai_search_text(dsai_auth_header, dsai_oob_start, dsai_oob_end)
        assert len(dsai_oob_hits) == 0, f"Expected 0 hits out of window, got {len(dsai_oob_hits)}"
        dsai_gate_results["gate_7_negative_temporal_filter"] = True
        dsai_log("Gate 7 Passed: Out-of-window sightings strictly excluded by scalar bounds.")

        # 5.3 Content control: query the lobby camera on its own, so its scores are measured
        # directly rather than only if a lobby frame happens to land in the global top 30.
        dsai_lobby_hits = dsai_search_text(dsai_auth_header, dsai_time_start, dsai_time_end,
                                           dsai_camera_ids=["cam_lobby_indoor"], dsai_top_k=100)
        assert len(dsai_lobby_hits) > 0, "Lobby control camera returned no frames; the control was not exercised"
        dsai_lobby_max = max(float(dsai_h.get("score", 0.0)) for dsai_h in dsai_lobby_hits)
        dsai_log(f"Lobby control: {len(dsai_lobby_hits)} frames scored, max score {dsai_lobby_max:.4f} (threshold {DSAI_CONFIDENCE_THRESHOLD})")
        assert dsai_lobby_max < DSAI_CONFIDENCE_THRESHOLD, f"Lobby control scored {dsai_lobby_max:.4f} >= threshold"

        dsai_sightings = {}

        for dsai_hit in dsai_hits:
            dsai_cam = dsai_hit.get("camera_id") or dsai_hit.get("video_id")
            dsai_score = float(dsai_hit.get("score", 0.0))
            dsai_ts = float(dsai_hit.get("frame_timestamp", 0.0))

            if dsai_cam == "cam_lobby_indoor":
                # Ensure control stream is excluded or significantly lower confidence
                assert dsai_score < 0.20, f"Lobby control camera exceeded threshold with score {dsai_score}"

            if dsai_score >= DSAI_CONFIDENCE_THRESHOLD:
                if dsai_cam not in dsai_sightings or dsai_ts < dsai_sightings[dsai_cam]["first_seen"]:
                    dsai_sightings[dsai_cam] = {
                        "first_seen": dsai_ts,
                        "max_score": dsai_score,
                        "time_iso": datetime.fromtimestamp(dsai_ts, tz=timezone.utc).strftime("%H:%M:%S")
                    }

        dsai_gate_results["gate_8_negative_content_control"] = True
        dsai_log("Gate 8 Passed: Negative control stream (lobby indoor) excluded from target matches.")

        # Sort sightings chronologically
        dsai_sorted_trajectory = sorted(dsai_sightings.items(), key=lambda x: x[1]["first_seen"])
        dsai_reported_cams = [cam_id for cam_id, _ in dsai_sorted_trajectory]
        dsai_log(f"Reporting Cameras in Trajectory: {dsai_reported_cams}")

        assert "cam_north_gate" in dsai_reported_cams, "cam_north_gate missing from trajectory"
        assert "cam_main_ave" in dsai_reported_cams, "cam_main_ave missing from trajectory"
        assert "cam_east_perimeter" in dsai_reported_cams, "cam_east_perimeter missing from trajectory"
        assert "cam_lobby_indoor" not in dsai_reported_cams, "cam_lobby_indoor must not appear in target vehicle trajectory"

        # Verify chronological order: cam_north_gate -> cam_main_ave -> cam_east_perimeter
        assert dsai_reported_cams.index("cam_north_gate") < dsai_reported_cams.index("cam_main_ave") < dsai_reported_cams.index("cam_east_perimeter"), \
            f"Trajectory not in chronological sequence: {dsai_reported_cams}"

        # The order is set by the test's base timestamps; what this gate really proves is that
        # each camera's frame times survived extractor/edge -> Milvus -> search unchanged.
        for dsai_cam_id, dsai_base, dsai_slack in [
            ("cam_north_gate", DSAI_TS_NORTH, 300.0),
            ("cam_main_ave", DSAI_TS_MAIN, 300.0),
            ("cam_east_perimeter", dsai_ts_east, 1.0),
        ]:
            dsai_first = dsai_sightings[dsai_cam_id]["first_seen"]
            assert dsai_base <= dsai_first <= dsai_base + dsai_slack, \
                f"{dsai_cam_id}: first sighting {dsai_first} not within [{dsai_base}, {dsai_base + dsai_slack}]"

        dsai_gate_results["gate_9_trajectory_chronological_ordering"] = True
        dsai_log("Gate 9 Passed: Cross-camera chronological vehicle trajectory verified.")

        # Print Executive Vehicle Tracking Report
        print("\n================ MULTI-CAMERA VEHICLE TRACKING REPORT ================", flush=True)
        print(f"Target Description: 'a red car'", flush=True)
        print(f"Time Window: {dsai_fmt_ts(dsai_time_start)} - {dsai_fmt_ts(dsai_time_end)} UTC", flush=True)
        print(f"Total Reporting Cameras: {len(dsai_sorted_trajectory)}", flush=True)
        print("----------------------------------------------------------------------", flush=True)
        for dsai_step, (dsai_cid, dsai_info) in enumerate(dsai_sorted_trajectory, 1):
            print(f"  Step {dsai_step}: [{dsai_info['time_iso']}] Camera '{dsai_cid}' (Confidence: {dsai_info['max_score']:.3f})", flush=True)
            dsai_trajectory_report.append({
                "step": dsai_step,
                "camera_id": dsai_cid,
                "time_iso": dsai_info["time_iso"],
                "confidence": round(dsai_info["max_score"], 3)
            })
        print("======================================================================\n", flush=True)

        # 5.4 Verify Host System Safeguards (Zero Host Harm)
        dsai_final_vram = dsai_get_gpu_vram_mb()
        dsai_vram_delta = dsai_final_vram - dsai_initial_vram
        dsai_log(f"Final Host Verification: VRAM Delta = {dsai_vram_delta} MB (Baseline: {dsai_initial_vram} MB, Current: {dsai_final_vram} MB)")
        assert dsai_vram_delta <= 10, f"GPU VRAM increased unexpectedly during CPU-only run: {dsai_vram_delta} MB"
        dsai_final_containers = dsai_list_other_containers()
        assert dsai_final_containers == dsai_initial_containers, \
            f"Host containers changed during the run: before={dsai_initial_containers}, after={dsai_final_containers}"
        dsai_gate_results["gate_10_zero_host_harm"] = True
        dsai_log(f"Gate 10 Passed: VRAM delta {dsai_vram_delta} MB; other host containers unchanged ({dsai_final_containers}).")

        return {
            "success": True,
            "gates": dsai_gate_results,
            "trajectory": dsai_trajectory_report
        }

    finally:
        dsai_cleanup_all()


if __name__ == "__main__":
    dsai_res = dsai_run_e2e_pipeline()
    if all(dsai_res["gates"].values()):
        dsai_log("ALL 10 VERIFICATION GATES PASSED! Enterprise Ingestion V3 Live E2E Test SUCCESSFUL.")
        sys.exit(0)
    else:
        dsai_log(f"TEST FAILED: Some gates did not pass: {dsai_res['gates']}")
        sys.exit(1)
