# ADR 0001: Trinetra Enterprise UI Phase 0 Architectural Decisions & Backend Contracts

* **Status**: Approved & Signed Off
* **Date**: 2026-09-21
* **Related Issue**: [#17 (Phase 0: Architectural Sign-off & Backend Contract Alignment)](https://github.com/swatah/deepSightAI-Trinetra/issues/17)
* **Plan Reference**: `/home/abhinav/.claude/plans/trinetra-enterprise-ui-nextjs-plan.md` (§3, §5 Phase 0)

---

## Context

Before transitioning the frontend from Streamlit to Next.js 14 (TypeScript, App Router), a ground-truth audit of the backend microservices (`AuthService:8002`, `SearchService:8081`, `WatchlistMatcherService:8083`, `ServerAndExtractor:8080`, and `MinIO:9000`) identified 11 critical architectural requirements, platform constraints, and backend integration gaps.

---

## Approved Architectural Decisions

| # | Topic | Approved Decision | Detailed Rationale |
|:---:|---|---|---|
| **1** | **App Router Naming Exemption** | **Approve Exemption** | Next.js 14 App Router strictly requires reserved filenames (`page.tsx`, `layout.tsx`, `route.ts`, `loading.tsx`, `error.tsx`, `middleware.ts`). Renaming them to `dsai_` breaks routing completely. Formally exempt Next.js reserved files and React components under `deepSightAI/Trinetra/UI/` from the Python `dsai_` prefix rule. Update `.gitignore` and `pyproject.toml` so Python linters do not scan the JS/TS tree. |
| **2** | **Auth & RBAC Model** | **Native AuthService + Role Check** | Authenticate against native `AuthService:8002` (`POST /auth/login`, RS256 JWT with `tenant_id`/`roles` claims). There is no Keycloak in this stack. Crucially, `AuthService` issues only `roles` and **never issues a `permissions` array**. Downstream permission checks (`watchlist:write`, `alerts:acknowledge`, admin panel) must evaluate role membership (`roles.includes("admin")`), not a non-existent `permissions` claim. |
| **3** | **Search Query API** | **Proceed as-is** | `SearchService:8081` routes (`/search/text`, `/search/vehicle`, `/search/person`, `/search/plate`, `/cameras`) are already built, tested, and operational. Proceed directly with full multi-modal search parity in Phase 4. |
| **4** | **Quota Strategy for v1** | **Informational Display** | Grep across the codebase confirmed 0 hits for "quota": no backend service tracks video quotas, search rates, or storage limits. Display usage and tier quotas with an explicit disclaimer: *"Informational metrics — Backend enforcement pending"* in v1 to avoid false enforcement claims until a dedicated backend quota service is built. |
| **5** | **Tenant Sector Strategy** | **Use `plugin_config` JSON Blob** | The `Tenant` table in `auth_service.py` has no `sector` column. Store the tenant sector inside the existing `plugin_config` JSON column (e.g. `{"sector": "law_enforcement"}`) for v1, avoiding immediate database schema migrations while maintaining backend persistence. |
| **6** | **RTSP Playback & Stop** | **Ingestion-only UI + Backend Stop Route** | Browsers cannot play raw `rtsp://` streams natively without a transcode bridge. Scope the UI to starting/stopping background ingestion and displaying live stream health metrics (FPS, active worker, ingested frames). Backend adds `POST /rtsp/stop` in `main_api.py` and `POST /stop_stream/{stream_id}` / `POST /stop_camera/{camera_id}` in `extractor.py` to stop running stream workers. |
| **7** | **Direct MinIO Video Upload** | **Backend Presigning + Browser PUT (Zero AWS SDKs)** | Eliminate all AWS vendor SDKs (`@aws-sdk/client-s3`) in the frontend. Backend endpoint `POST /upload/request-url` generates presigned PUT URLs via Python's native `minio.Minio.presigned_put_object()`. The frontend streams video directly to MinIO using standard browser `fetch(PUT)` with upload progress tracking, preventing Node.js proxy memory exhaustion. |
| **8** | **MinIO Thumbnail Resolution** | **Next.js Media Proxy** | Internal MinIO URLs (`http://minio:9000/...`) returned by `SearchService` cannot be resolved by client browsers outside the Docker/Kubernetes network (`ERR_NAME_NOT_RESOLVED`). Implement an authenticated Next.js proxy route (`/api/media/[...path]`) that fetches the image server-side from internal MinIO and streams it to the browser with standard caching headers. |
| **9** | **Backend CORS Strategy** | **Next.js Rewrites** | FastAPI services lack `CORSMiddleware`. Direct browser calls from `localhost:3000` to microservice ports would fail with CORS errors. Configure Next.js same-origin reverse-proxy rewrites in `next.config.js` (`/api/backend/*`), completely eliminating CORS preflight overhead and errors. |
| **10** | **Alert SSE Streaming** | **Native Web Streams (Zero Microsoft SDKs)** | Eliminate Microsoft vendor packages (`@microsoft/fetch-event-source`). Standard browser `EventSource` cannot send custom headers (`Authorization: Bearer <token>` is required by `dsai_stream_alerts`). Implement a lightweight 15-line vanilla TypeScript helper using native Web Streams (`fetch` + `ReadableStream` / `TextDecoder`) to stream events with standard Bearer authorization. |
| **11** | **60-Minute Token Expiry** | **Global 401 Interceptor** | `auth_service.py` sets `ACCESS_TOKEN_EXPIRE_MINUTES = 60` with no `/auth/refresh` endpoint. Implement a global 401 response interceptor in the API client to catch expired token errors and display a graceful re-login modal or clean redirect instead of crashing operator sessions. |

---

## Implemented Backend Bridges & Configurations

1. **`deepSightAI/Trinetra/ServerAndExtractor/main_api.py`**:
   * Added `UploadRequestUrlModel` and `POST /upload/request-url` (presigned PUT URL generator).
   * Added `RtspStopRequest` and `POST /rtsp/stop` (RTSP stream termination router).
2. **`deepSightAI/Trinetra/ServerAndExtractor/extractor.py`**:
   * Added `_active_camera_streams` tracking dictionary.
   * Added `POST /stop_stream/{stream_id}` and `POST /stop_camera/{camera_id}`.
3. **`.gitignore`**:
   * Ignored `deepSightAI/Trinetra/UI/node_modules/`, `deepSightAI/Trinetra/UI/.next/`, and `out/`.
4. **`pyproject.toml`**:
   * Excluded `deepSightAI/Trinetra/UI/*` from `pytest` discovery, test coverage reporting, and `mypy` type scans.
