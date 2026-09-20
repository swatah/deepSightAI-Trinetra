# deepSightAI Trinetra Coding Standards & Architecture Guidelines

> **CRITICAL RULE FOR ALL AI AGENTS AND DEVELOPERS**:
> Before writing, modifying, creating, or refactoring ANY code in this repository, you **MUST** read, reference, and adhere strictly to the rules documented in this file.
> Failure to follow these naming conventions, import structures, and architectural standards is considered a build-breaking defect.

---

## 1. Repository Structure & Package Hierarchy

All Python source code for the Trinetra platform resides inside the canonical package hierarchy:

```text
deepSightAI-Trinetra/                      # Repository Root
├── CODING_STANDARDS.md                   # This specification file (Authority)
├── AGENTS.md                             # Agent guidance & rule loader
├── GEMINI.md                             # Antigravity rule loader
├── CLAUDE.md                             # Claude guidance file
├── setup.py                              # Package installer (name="deepSightAI")
├── pyproject.toml                        # Build & test configuration
├── config/                               # Global configuration files
│   └── global_config.yaml                # Canonical global defaults
├── deepSightAI/                          # Canonical root Python package
│   ├── __init__.py
│   └── Trinetra/                         # Core platform namespace
│       ├── __init__.py
│       ├── ServerAndExtractor/           # Ingestion, RTSP extraction, worker registry
│       ├── AuthService/                  # Authentication, RBAC, tenant management
│       ├── SearchService/                # Semantic text/image vector search
│       ├── Embedder/                     # Visual feature extraction (CLIP/ONNX)
│       ├── AuditService/                 # Security audit logging
│       ├── UI/                           # Frontend user interface
│       └── Shared/                       # Shared utilities, DB models, streaming, storage
└── tests/                                # Test suites
```

---

## 2. Naming Conventions

### 2.1 Services & Directories (PascalCase / CamelCase)
All microservices and major module directories under `deepSightAI/Trinetra/` **MUST** follow PascalCase (CamelCase):
* ✅ `deepSightAI/Trinetra/ServerAndExtractor/`
* ✅ `deepSightAI/Trinetra/AuthService/`
* ✅ `deepSightAI/Trinetra/SearchService/`
* ✅ `deepSightAI/Trinetra/Embedder/`
* ✅ `deepSightAI/Trinetra/AuditService/`
* ✅ `deepSightAI/Trinetra/Shared/`
* ✅ `deepSightAI/Trinetra/UI/`
* ❌ NEVER use spaces: `"Server and Extractor"` is forbidden.
* ❌ NEVER use all lowercase for microservice directories: `authservice`, `shared`.

### 2.2 Mandatory `dsai_` Prefix Requirement
* **ALL variable names, module/script filenames, and function/method names MUST start with the prefix `dsai_`.**
  * **File Names**: All Python module and script filenames must be prefixed with `dsai_` (e.g., `dsai_extractor.py`, `dsai_embedder.py`, `dsai_ingest_service.py`, `dsai_main_api.py`, `dsai_milvus.py`, `dsai_middleware.py`, `dsai_schema.py`, `dsai_producer.py`, `dsai_consumer.py`).
  * **Function & Method Names**: All functions and class methods must be prefixed with `dsai_` (e.g., `def dsai_process_segment_frames(...)`, `def dsai_ensure_tenant_collection(...)`, `def dsai_get_config(...)`, `def dsai_connect_milvus(...)`).
  * **Variable & Attribute Names**: All local variables, function arguments, dictionary keys, and instance attributes must be prefixed with `dsai_` (e.g., `dsai_tenant_id`, `dsai_camera_id`, `dsai_frame_path`, `dsai_video_id`, `dsai_minio_client`, `dsai_collection`).

### 2.3 Classes & Models (PascalCase)
* All classes, Pydantic schemas, SQLAlchemy models, and exception classes **MUST** use PascalCase.
* Examples:
  * `HttpRtspRequest`
  * `HttpFileRequest`
  * `FrameReadyEvent`
  * `IngestJobStarted`
  * `StreamProducer`
  * `StreamConsumer`
  * `SearchRequest`
  * `SearchResult`
  * `CameraRepository`

### 2.4 Functions & Methods (`dsai_` snake_case)
* Function and method names: `def dsai_process_segment_frames(...)`, `def dsai_ensure_tenant_collection(...)`
* Private/internal helpers: prefix with `_dsai_`, e.g., `_dsai_heartbeat_thread`, `_dsai_cleanup_redis`

### 2.5 Variables & Attributes (`dsai_` snake_case)
* Local variables, function parameters, and dictionary keys: `dsai_tenant_id`, `dsai_camera_id`, `dsai_frame_path`, `dsai_video_object_pk`
* Model attributes: `self.dsai_milvus_collection`, `self.dsai_minio_client`

### 2.6 Constants & Configuration Keys (UPPER_SNAKE_CASE with DSAI_ prefix)
* Module-level constants: `DSAI_FRAME_BUCKET = "frames"`, `DSAI_VIDEO_BUCKET = "videos"`, `DSAI_DEFAULT_EMBEDDING_DIM = 512`
* Environment variables: `DSAI_REGISTRY_URL`, `DSAI_MILVUS_HOST`, `DSAI_MINIO_URL`, `DSAI_REDIS_URL`

---

## 3. Import Standards (Zero Tolerance for Broken Imports)

### 3.1 Canonical Imports Required
All cross-service and shared imports **MUST** use the canonical full package path:
```python
# CORRECT:
from deepSightAI.Trinetra.Shared.Streaming.Producer import StreamProducer
from deepSightAI.Trinetra.Shared.Streaming.Consumer import StreamConsumer
from deepSightAI.Trinetra.Shared.Streaming.Schema import FrameReadyEvent, IngestJobStarted
from deepSightAI.Trinetra.Shared.Config import get as get_config
from deepSightAI.Trinetra.Shared.Storage import configure_bucket_lifecycle
from deepSightAI.Trinetra.Shared.Middleware import require_auth
from deepSightAI.Trinetra.Shared.Milvus import ensure_tenant_collection, connect_milvus_with_retry
from deepSightAI.Trinetra.Shared.DB import get_tenant_connection
from deepSightAI.Trinetra.Shared.Repositories.CameraRepository import CameraRepository
```

### 3.2 Strictly Prohibited Import Patterns
* ❌ **NO un-namespaced shared imports**: `from shared... import ...` or `from Shared... import ...` are forbidden in production services.
* ❌ **NO relative root crawling**: `from ...Shared import ...` is forbidden.
* ❌ **NO `sys.path` hacking**: `sys.path.insert(0, ...)` or `sys.path.append(...)` in service code is prohibited.
* ❌ **NO symlinks**: Using `ln -s` in the filesystem to bridge naming differences is strictly prohibited. The package structure itself must be clean and valid.
* ❌ **NO `PYTHONPATH` dependency**: Relying on `PYTHONPATH` environment variables or setting `ENV PYTHONPATH` is strictly prohibited. The codebase is modular and fully packaged; resolution must happen natively via standard Python package installation (`pip install -e .`).
* ❌ **NO duplicate shim files**: Do NOT maintain duplicate lowercase and PascalCase files (e.g. `milvus.py` alongside `Milvus.py` or `repositories/` alongside `Repositories/`). Always maintain strictly the single canonical PascalCase module file.

---

## 4. Multi-Tenancy & Data Isolation Standards

Every event, database record, Milvus collection, and storage object **MUST** be tenant-aware:
1. **Milvus Collections**: Every tenant collection name is formed via `get_collection_name(tenant_id)` (e.g., `trinetra_vectors_{tenant_id}`).
2. **MinIO Object Keys**: Object keys must follow hierarchical prefixes: `{tenant_id}/{camera_id}/{date}/{video_id}_{timestamp}.jpg`.
3. **Redis Keys**: All keys must use tenant prefixes via `make_tenant_prefix(tenant_id)`.
4. **Relational Repositories**: All repository operations (PostgreSQL/SQLite) must scope queries with `tenant_id`.

---

## 5. Docker & Containerization Standards

1. **Build Context**:
   - Compose files located inside service directories (e.g., `deepSightAI/Trinetra/ServerAndExtractor/docker-compose.extractor.yml`) must declare `context: ../../..` so that the repository root is the build context.
   - All Dockerfile paths in compose files must specify the canonical path:
     `dockerfile: deepSightAI/Trinetra/ServerAndExtractor/Dockerfile`
2. **Package Installation in Images**:
   - Dockerfiles must copy `setup.py`, `pyproject.toml`, and the `deepSightAI/` package tree.
   - Execute `pip install --no-deps -e .` in `/app` or `/workspace` so `import deepSightAI` works natively in containers via standard `site-packages`.
   - ❌ **NO `PYTHONPATH` in Dockerfiles**: Do **NOT** set `ENV PYTHONPATH=/app` (or `/workspace`). Going modular with native `pip install -e .` completely eliminates the need for `PYTHONPATH` and `sys.path` hacks.

---

## 6. Pre-Commit Verification Checklist for Agents

Before completing any task or declaring success:
- [ ] Have you verified that all imports match `deepSightAI.Trinetra.*`?
- [ ] Have you ensured no `PYTHONPATH` environment variables, `sys.path.insert`, or symlinks were added?
- [ ] Have you verified all 4 Dockerfiles (`Embedder/Dockerfile`, `ServerAndExtractor/Dockerfile`, `Dockerfile.test`, `Dockerfile.auth-test`) reference correct paths and do not set `PYTHONPATH`?
- [ ] Have you verified `docker-compose.extractor.yml` build contexts and dockerfile paths?
- [ ] Have all relevant test suites passed (`pytest tests/test_phase0_groundwork.py`, etc.)?
