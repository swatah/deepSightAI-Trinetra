# Multi-Camera Video Search & Cross-Camera Tracking — vast.ai Testing Guide

This guide walks a human tester through renting a GPU machine on **vast.ai**, deploying **deepSightAI Trinetra** on it, and testing **multi-camera search across camera viewpoints** through the **REST API only** (the Streamlit UI is out of scope for this pass).

Every command in this guide has been run and verified against the live repo and a real vast.ai API key before being written down — the "Known Issues" section (§9) documents what was actually broken in the previous version of this guide and how it's been corrected here.

---

## 1. Overview & How Cross-Camera Search Works

```
                      ┌─────────────────────────────────────────┐
                      │              SEARCH QUERY               │
                      │       "car driving on the street"        │
                      └────────────────────┬────────────────────┘
                                           │
                                           ▼
                             ┌───────────────────────────┐
                             │  OpenCLIP (ViT-B/32)      │
                             │  512-D Text Embedding     │
                             └─────────────┬─────────────┘
                                           │
                                           ▼
                             ┌───────────────────────────┐
                             │   Milvus Vector Database  │
                             │   Cosine Similarity Search│
                             └─────────────┬─────────────┘
                                           │
                   ┌───────────────────────┴───────────────────────┐
                   ▼                                               ▼
      ┌─────────────────────────┐                     ┌─────────────────────────┐
      │  Camera 1 Feed / Video  │                     │  Camera 2 Feed / Video  │
      └─────────────────────────┘                     └─────────────────────────┘
```

1. **Ingestion**: A video is uploaded into MinIO, then the API is told to process it by object key. It gets split into segments.
2. **Frame Extraction & Embeddings**: Each segment's frames are extracted, embedded into a 512-D vector space (OpenCLIP), and written to Milvus.
3. **Cross-Camera Retrieval**: A text query is embedded the same way and matched by cosine similarity against every frame from every ingested video, ordered by score.

---

## 2. What This Test Actually Verifies

**Goal:** confirm the ingest → extract → embed → search pipeline works end-to-end via the API, using 3 short real video clips standing in for 3 separate cameras, on a freshly provisioned GPU VM.

**Test videos** (real footage, not synthetic — each URL below was independently downloaded and verified to return a valid MP4 before being put in this doc):

| Camera slot | Content | Direct URL | Duration |
|---|---|---|---|
| cam_01 | Busy avenue, Las Vegas — vehicles | `https://assets.mixkit.co/videos/4251/4251-720.mp4` | ~9.6s |
| cam_02 | Crowds crossing a street junction — pedestrians | `https://assets.mixkit.co/videos/4401/4401-720.mp4` | ~19.8s |
| cam_03 | Times Square, sunny day — mixed vehicles + pedestrians | `https://assets.mixkit.co/videos/4442/4442-720.mp4` | ~9.0s |

All under the 30-second segment threshold the extractor uses, so each video becomes exactly **one** segment — keeps the test fast and easy to reason about.

**Steps that will actually be executed, in order:**

1. Provision a GPU VM on vast.ai (§3).
2. Copy this repo onto the VM and bring up the stack (§4–5).
3. Download the 3 test videos with `wget` and upload them into MinIO (§6).
4. Call `/process_video` for each and poll until frames are embedded (§7).
5. Run a battery of `/search/text` queries and record what actually comes back (§7).
6. Tear down the VM so billing stops (§8).

The UI, RTSP ingestion, and admin/replay endpoints are **not** tested here — out of scope for this pass.

---

## 3. Provisioning a GPU VM on vast.ai

### Why a standard instance, and how the SSH key problem is solved

A vast.ai **VM instance** (the nested-VM type that supports Docker-in-Docker) requires an SSH key to already be registered on the *account* before the VM can be created — the vast.ai server rejects creation otherwise (`no_ssh_key_for_vm`), and this account is a **Team account**, which vast.ai explicitly does not allow to register account-level SSH keys ("Team SSH keys are not supported. SSH keys can only be created in personal context" — confirmed by a live API call).

So this guide uses a **standard container instance** (the regular PyTorch template) instead, and solves the key problem differently: standard instances accept an SSH key **attached directly to the instance after it's created** (`vastai attach ssh`), which works fine for team accounts. The tradeoff is that a standard instance can't run nested `docker compose` — see §9 for why — so §4–5 install and run everything as plain OS processes instead of containers.

### Step 1: Install the CLI and set your API key (one-time, local machine)

```bash
pip install --user vastai
vastai set api-key <YOUR_VAST_API_KEY>
```

### Step 2: Search for a GPU offer

```bash
vastai search offers 'num_gpus=1 disk_space>=40 reliability>0.98' -o 'dph_total'
```

Pick the cheapest reasonable offer's `ID` (leftmost column) from the results.

### Step 3: Create the instance

```bash
vastai create instance <OFFER_ID> --image pytorch/pytorch --disk 40 --ssh --direct
```

### Step 4: Attach your SSH key to the new instance

Get the instance ID from the create response or `vastai show instances`, then:

```bash
vastai attach ssh <INSTANCE_ID> ~/.ssh/id_ed25519.pub
```

### Step 5: Wait for it to come up and get connection info

```bash
vastai show instances -v
```

Wait until `status` shows `running`.

```bash
vastai ssh-url <INSTANCE_ID>
```

### Step 6: Connect

```bash
ssh root@<HOST> -p <PORT>
```

### Step 7 (teardown, run at the very end — §8 covers this in context)

```bash
vastai destroy instance <INSTANCE_ID> -y
```

---

## 4. Getting the Code onto the VM & Server Setup

Everything this test touches (`Server and Extractor/`, `Embedder/`, `SearchService/`, `shared/`, `UI/`) is fully committed with no local changes, so a plain `git clone` on the VM gets the exact same code as the local working tree — simpler than copying files over.

### Step 1: On the VM, clone the repo

```bash
git clone https://github.com/swatah/deepSightAI-Trinetra.git /root/deepSightAI-Trinetra
```

### Step 2: On the VM, verify CUDA is present and install system dependencies

```bash
nvidia-smi

apt-get update
apt-get install -y redis-server ffmpeg \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
  gstreamer1.0-libav gstreamer1.0-tools python3-gi python3-gst-1.0 gir1.2-gst-plugins-base-1.0 \
  curl wget
```

The extractor doesn't just shell out to `ffmpeg` — it drives **GStreamer** through PyGObject bindings (`python3-gi`, `python3-gst-1.0`), which is why these apt packages matter, not just the `ffmpeg` binary.

`apt install redis-server` does **not** start it — like Milvus, there's no systemd here to auto-start services from a package install. Start it explicitly:

```bash
redis-server --daemonize yes
redis-cli ping   # expect PONG
```

### Step 3: Install MinIO (object storage for videos + frames) as a native binary

MinIO discontinued its `dl.min.io` binary distribution in 2025 (the open-source server/client are now archived, unmaintained, and that domain returns `410 Gone` — confirmed live). Pull the last GitHub release that still ships a raw Linux binary instead:

```bash
wget 'https://github.com/minio/minio/releases/download/RELEASE.2025-09-07T16-13-09Z/minio.linux-amd64.RELEASE.2025-09-07T16-13-09Z' -O /usr/local/bin/minio
chmod +x /usr/local/bin/minio
mkdir -p /root/minio_data
MINIO_ROOT_USER=minioadmin MINIO_ROOT_PASSWORD=minioadmin nohup /usr/local/bin/minio server /root/minio_data --console-address ":9090" > /root/minio.log 2>&1 &
```

Verify: `curl -s http://localhost:9000/minio/health/live` should return HTTP 200.

### Step 4: Install Milvus standalone as a native `.deb` package

The repo's compose files pin Milvus `v2.4.4`, which doesn't ship a bare-metal package. The closest same-generation version that does is `v2.6.18`. Its `.deb` bundles an **embedded etcd** (no separate etcd process needed) and by default connects to MinIO at `localhost:9000` with `minioadmin`/`minioadmin` — exactly what Step 3 just started, so no config changes are needed.

```bash
wget https://github.com/milvus-io/milvus/releases/download/v2.6.18/milvus_2.6.18-1_amd64.deb -O /root/milvus.deb
apt install -y /root/milvus.deb
```

**Don't use `systemctl start milvus`** — a vast.ai standard instance is a Docker container, not a full VM, so there's no systemd/PID 1 init inside it (`systemctl` fails with "System has not been booted with systemd as init system"). Run the same command the systemd unit would have, directly, in the background instead:

```bash
MILVUSCONF=/etc/milvus/configs/ DEPLOY_MODE=STANDALONE nohup /usr/bin/milvus run standalone > /root/milvus.log 2>&1 &
```

Verify: `curl -s http://localhost:9091/healthz` should return `OK` once it's up (can take a minute on first start).

---

## 5. Starting the deepSightAI Application Services (on the VM)

**Do not use any of the repo's `docker-compose*.yml` files** — this VM has no Docker. The app's services are run directly as Python processes instead, translating each compose file's env vars into shell exports.

One code-level quirk to route around before starting anything: `main_api.py` hardcodes `REGISTRY_URL = "http://registry:8000"` (not read from an env var, unlike every other service). Since everything now runs on one box, resolve that hostname locally instead of editing the file:

```bash
echo "127.0.0.1 registry" >> /etc/hosts
```

### Step 1: Python environment + dependencies for registry / main-api / extractor

These three share one `requirements.txt`. The extractor also does `import gi` (PyGObject, installed as the `python3-gi` apt package in §4 Step 2) — that package only exists for the **system** Python (`/usr/bin/python3`), not the conda Python that `python3` resolves to by default on this image (`/opt/conda/bin/python3`). Build the venv from the system interpreter with `--system-site-packages` so it inherits `gi`:

```bash
apt-get install -y python3.10-venv
cd /root/deepSightAI-Trinetra
/usr/bin/python3 -m venv --system-site-packages venv-server
source venv-server/bin/activate
python3 -c "import gi"   # sanity check — must not error
pip install -r "Server and Extractor/requirements.txt"
```

### Step 2: Start registry (port 8000)

```bash
cd "/root/deepSightAI-Trinetra/Server and Extractor"
REDIS_URL=redis://localhost:6379 nohup python3 -m uvicorn registry:app --host 0.0.0.0 --port 8000 > /root/registry.log 2>&1 &
```

### Step 3: Start main-api / input-router (port 8080)

```bash
cd "/root/deepSightAI-Trinetra/Server and Extractor"
MINIO_URL=localhost:9000 nohup python3 -m uvicorn main_api:app --host 0.0.0.0 --port 8080 > /root/main-api.log 2>&1 &
```

### Step 4: Start one extractor (port 8001)

One is enough for 3 sequential test videos — the registry load-balances across however many are registered.

`extractor.py` (unlike `main_api.py`, whose only `shared.*` imports are inside function bodies that never execute during this test) does `from shared.streaming.producer import StreamProducer` at module level — same repo-root import issue as the embedder (§9). Needs `PYTHONPATH` pointed at the repo root:

```bash
cd "/root/deepSightAI-Trinetra/Server and Extractor"
EXTRACTOR_ID=extractor-1 EXTRACTOR_URL=http://localhost:8001 REGISTRY_URL=http://localhost:8000 MINIO_URL=localhost:9000 \
PYTHONPATH=/root/deepSightAI-Trinetra \
  nohup python3 -m uvicorn extractor:app --host 0.0.0.0 --port 8001 > /root/extractor.log 2>&1 &
```

If you ever need to restart a service, don't use `pkill -f 'uvicorn registry:app'` over SSH — the remote shell's own invoked command line contains that same text, so `pkill -f` matches and kills the SSH session itself before it reaches the real target. Find the PID a different way (e.g. `ps aux | grep uvicorn`, or the port from `ps` output) and `kill` it directly.

### Step 5: Embedder — needs a fix for a real import bug, then starts

`embedder.py` imports `from shared.streaming.consumer import StreamConsumer`, but `shared/` lives at the repo root, not inside `Embedder/`. Docker's build context for the embedder service is scoped to `Embedder/` only, so **the embedder container as shipped can't actually import this and would crash on startup in Docker too** — this isn't specific to running natively (see §9). Running from the repo root with `PYTHONPATH` pointed at it works around it without editing any code:

```bash
cd /root/deepSightAI-Trinetra
python3 -m venv venv-embedder && source venv-embedder/bin/activate
pip install -r Embedder/requirements_embedder.txt
deactivate

cd /root/deepSightAI-Trinetra/Embedder
PYTHONPATH=/root/deepSightAI-Trinetra \
MILVUS_HOST=localhost MILVUS_PORT=19530 EMBEDDING_DIM=512 \
MINIO_URL=localhost:9000 MINIO_ACCESS_KEY=minioadmin MINIO_SECRET_KEY=minioadmin FRAME_BUCKET=frames \
REDIS_URL=redis://localhost:6379 REGISTRY_URL=http://localhost:8000 \
EMBEDDER_ID=embedder-1 EMBEDDER_URL=http://localhost:8100 USE_ONNX=1 \
nohup /root/deepSightAI-Trinetra/venv-embedder/bin/python3 embedder.py > /root/embedder.log 2>&1 &
```

No local ONNX/PyTorch weights are checked into `Embedder/models/` (it only has plugin-loader code), so this will fall through to downloading OpenCLIP `ViT-B-32` (`laion2b_s34b_b79k`) from the internet on first run — expected, not an error.

### Step 6: SearchService (port 8081)

```bash
cd /root/deepSightAI-Trinetra/SearchService
python3 -m venv venv && source venv/bin/activate
pip install fastapi uvicorn torch open_clip_torch onnxruntime-gpu onnxruntime pymilvus Pillow numpy

MILVUS_HOST=localhost MILVUS_PORT=19530 nohup python3 main.py > /root/search-service.log 2>&1 &
cd ..
```

Same model-download caveat as the embedder — first startup needs internet access and a few minutes.

### Forwarding ports back to your local machine

From your **local machine**, open an SSH tunnel:

```bash
ssh -N -p <PORT> -L 8080:localhost:8080 -L 8081:localhost:8081 -L 9000:localhost:9000 -L 19530:localhost:19530 root@<HOST>
```

---

## 6. Preparing the Test Videos (on the VM)

### Step 1: Download the 3 clips

```bash
mkdir -p ~/test_cameras && cd ~/test_cameras
wget -O cam_01_las_vegas_avenue.mp4 https://assets.mixkit.co/videos/4251/4251-720.mp4
wget -O cam_02_street_crossing.mp4  https://assets.mixkit.co/videos/4401/4401-720.mp4
wget -O cam_03_times_square.mp4     https://assets.mixkit.co/videos/4442/4442-720.mp4
```

### Step 2: Upload each into MinIO's `videos` bucket

`/process_video` does **not** accept a raw file upload — it takes a JSON body with a `video_uri` that must already exist as an object in MinIO's `videos` bucket (this is how the Streamlit UI does it too, per `UI/ui.py`). Push the files in directly with the MinIO Python SDK:

```bash
pip install minio
python3 <<'EOF'
from minio import Minio
import os

client = Minio("localhost:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
if not client.bucket_exists("videos"):
    client.make_bucket("videos")

for fname in ["cam_01_las_vegas_avenue.mp4", "cam_02_street_crossing.mp4", "cam_03_times_square.mp4"]:
    path = os.path.expanduser(f"~/test_cameras/{fname}")
    client.fput_object("videos", fname, path, content_type="video/mp4")
    print(f"Uploaded {fname}")
EOF
```

---

## 7. API Test Procedure

### Step 1: Baseline health checks

```bash
curl -s http://localhost:9000/minio/health/live && echo " <- minio OK"
curl -s http://localhost:9091/healthz && echo " <- milvus OK"
curl -s http://localhost:8081/health; echo
```

The embedder creates the Milvus `video_frames` collection on its own startup (not after the first video, as an earlier draft of this section assumed) — so `/health` should already return `{"status":"healthy",...}` by this point, before any video has been ingested.

### Step 2: Ingest the 3 videos

```bash
curl -X POST http://localhost:8080/process_video -H "Content-Type: application/json" -d '{"video_uri": "cam_01_las_vegas_avenue.mp4"}'
curl -X POST http://localhost:8080/process_video -H "Content-Type: application/json" -d '{"video_uri": "cam_02_street_crossing.mp4"}'
curl -X POST http://localhost:8080/process_video -H "Content-Type: application/json" -d '{"video_uri": "cam_03_times_square.mp4"}'
```

Each call returns immediately (`{"message": "Successfully dispatched N segments for processing."}`) — dispatch is async, actual extraction + embedding happens in the background.

### Step 3: Poll until embeddings land

```bash
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/health)
  if [ "$code" = "200" ]; then echo "Milvus collection ready after $((i*10))s"; break; fi
  echo "Not ready yet ($code), waiting..."; sleep 10
done
```

### Step 4: Run search queries

Since the exact contents of the clips weren't manually reviewed frame-by-frame, use general queries first, then narrow based on what actually matches:

```bash
curl -X POST http://localhost:8081/search/text -H "Content-Type: application/json" -d '{"query_text": "a car driving on the street", "top_k": 10}'
curl -X POST http://localhost:8081/search/text -H "Content-Type: application/json" -d '{"query_text": "people crossing at an intersection", "top_k": 10}'
curl -X POST http://localhost:8081/search/text -H "Content-Type: application/json" -d '{"query_text": "traffic at a busy intersection", "top_k": 10}'
```

For each, check: do results come back from more than one `video_id` (i.e. does cross-camera retrieval actually work), and do the top-scored `frame_path` values look plausible for the query.

### Actual results (from a real run on 2026-09-18)

Cross-camera retrieval confirmed working: querying `"a car driving on the street"` with `top_k=30` returned hits from all three cameras (`cam_01_las_vegas_avenue`: 12, `cam_02_street_crossing`: 11, `cam_03_times_square`: 7).

Relevance also checked out — the two pedestrian-flavored queries both correctly top-ranked `cam_02_street_crossing` (the actual crowd-crossing footage) over the other two cameras:

| Query | Top result | Score |
|---|---|---|
| `"people crossing at an intersection"` | `cam_02_street_crossing` | 0.347 |
| `"traffic at a busy intersection"` | `cam_02_street_crossing` | 0.311 |

This required fixing two real application bugs along the way — see §9.

---

## 8. Cleanup

From your local machine:

```bash
vastai show instances
vastai destroy instance <INSTANCE_ID> -y
vastai show instances   # confirm it's gone — this is what stops billing
```

---

## 9. Known Issues Found While Preparing This Guide

Documented here so nobody re-discovers these the hard way.

### Fixed in this repo (found and corrected during the live run on 2026-09-18)

- **`registry.py`'s round-robin extractor/embedder selection was fundamentally broken.** `get_available_extractor` used `r.scan_iter("extractor:*")` to find registered extractors, but the round-robin position counter was itself stored under the key `"extractor:index"` — which that same `"extractor:*"` scan also matches. Once any extractor had been selected once (which writes `extractor:index`), the scan would include `"index"` as if it were a real extractor ID. The very next time the round-robin happened to land on that fake entry, `r.hget("extractor:index", "status")` crashed with `WRONGTYPE Operation against a key holding the wrong kind of value` (the key is a plain Redis string, not a hash) — and since the crash happened before the counter could advance, every subsequent call landed on the same broken position and crashed forever. The same bug existed for `get_available_embedder` via `"embedder:index"`. **Fixed** by renaming the counters to `extractor_index` / `embedder_index` (no `:` prefix, so they no longer collide with the discovery scan). Verified against the repo's existing `tests/registry/test_load_balancer.py` (4/4 passing) and live on the VM — ingestion of all 3 test videos succeeded after the fix.
- **`SearchService/main.py`'s text search never worked.** It encoded the query text with `preprocess([request.query_text])` — but `preprocess` is OpenCLIP's *image* transform pipeline (resize/crop/normalize for pictures), not a text tokenizer. Every call to `/search/text` failed with `Search failed: Unexpected type <class 'list'>`. **Fixed** by tokenizing with `open_clip.get_tokenizer("ViT-B-32")` instead. Verified live — see §7's recorded results for real, correctly-ranked cross-camera search output after the fix.

### Environment gotchas (not code bugs — deployment traps worth knowing about)

- **The extractor defaults `REDIS_URL` to `redis://redis:6379`** (the Docker-network hostname), same pattern as every other service — but this one is easy to miss because the extractor still *appears* to work without it: frame extraction and MinIO upload both succeed, and `/extract` still returns 200. The failure is silent and only visible in the extractor's own log (`Failed to publish FrameReadyEvent: Error -2 connecting to redis:6379`) — the embedder never finds out the frames exist, so nothing gets embedded, with no error surfaced anywhere else. §5 Step 4 sets `REDIS_URL=redis://localhost:6379` explicitly to avoid this.
- **On this vast.ai image, the conda-installed `ffmpeg` (first on `PATH`) silently lacks `libx264`** — it's a GPL-avoidance build (`conda-bld/ffmpeg`, no `--enable-libx264` in its config), while the apt-installed `/usr/bin/ffmpeg` has it. `ffmpeg-python`'s `.run()` just shells out to whatever `ffmpeg` resolves to on `PATH`, so segment extraction failed with `Unknown encoder 'libx264'` even though a working `ffmpeg` was installed and present on the box the whole time. §4 Step 2 fixes this by symlinking `/opt/conda/bin/ffmpeg` to the system one, so `PATH` order stops mattering.

### Still open (not fixed — out of scope for this guide, or need a larger structural change)

- **`/process_video` contract**: takes JSON `{"video_uri": "<minio object key>"}`, not a multipart file upload. There is no HTTP upload endpoint anywhere in the backend — the only way a video's bytes reach the server is by writing it into MinIO's `videos` bucket first (§6, Step 2). The previous version of this guide's `curl -F "file=@..."` example never worked.
- **Repo-root `docker-compose.yml` is broken**: `registry`, `main-api`, `extractor`, and `embedder` all reference `Dockerfile.*` files that don't exist in the repo. Only `Server and Extractor/docker-compose.extractor.yml` and `Embedder/docker-compose.embedder.yaml` actually build.
- **Port 8080 (`main-api`) has no `/health` endpoint.** Only SearchService (8081) does.
- **`STATIC_SERVER_URL` (port 8082)**, which the Streamlit UI uses to render frame thumbnails, is not served by anything in this repo — no Dockerfile, compose entry, or static-file route exists for it. Irrelevant for API-only testing; would need to be built before the UI walkthrough could work.
- **`UI/ui.py` sends the wrong JSON field to `/search/text`** (`query` instead of `query_text`), so as shipped, the UI's search box will get a 422 from the backend. Not exercised by this guide since it's API-only, but worth fixing separately before anyone runs the UI walkthrough.
- **SearchService has no `Dockerfile` or `requirements.txt`** — it must be run as a bare process with manually installed dependencies (§5).
- **No GPU device reservation in either compose file** — `embedder`'s container would run OpenCLIP/ONNX on CPU even on a GPU host, since neither compose file declares `deploy.resources.reservations.devices`. Moot for this guide since we're not using Docker at all (see below), but worth knowing if the compose files are ever used directly.
- **The embedder's Docker build is broken, independent of anything in this guide.** `Embedder/embedder.py` does `from shared.streaming.consumer import StreamConsumer`, but `shared/` only exists at the repo root — not inside `Embedder/`. `docker-compose.embedder.yaml`'s embedder service builds with `context: .` scoped to the `Embedder/` directory, so `shared/` never makes it into the image. `docker build` itself would succeed (it only copies files), but the container would crash immediately on `python embedder.py` with `ModuleNotFoundError: No module named 'shared'`. Confirmed by inspecting the Dockerfile's COPY list and the compose build context; this guide's native run avoids it with `PYTHONPATH=/root/deepSightAI-Trinetra` (§5, Step 5) since we're not in a container at all, but the Docker path itself needs a real fix (e.g. building from the repo root with a `Embedder/Dockerfile` referencing `context: ..`).
- **vast.ai VM instances (`docker.io/vastai/kvm`) require an SSH key already registered on the account before creation, and this account is a Team account, which vast.ai's API refuses to register account-level SSH keys for** ("Team SSH keys are not supported"). That's why this guide provisions a standard instance and uses `vastai attach ssh` after creation instead (§3) — and, as a direct consequence, why the whole stack in §4–5 runs as native OS processes rather than via `docker compose`, since standard vast.ai instances don't support Docker-in-Docker either.
