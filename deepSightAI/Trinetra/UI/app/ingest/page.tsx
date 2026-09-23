"use client";

/**
 * Ingest page — Phase 6, Issue #39.
 *
 * Two-step direct-to-MinIO upload flow (Zero AWS SDKs):
 *   Step 1: POST /upload/request-url  → { upload_url, video_uri }
 *   Step 2: Browser PUT directly to MinIO presigned URL via native fetch + progress tracking
 *   Step 3: POST /process_video       → dispatch segment extraction
 *
 * Uses the VideoUploader component (Issue #38) for drag-and-drop staging.
 * Zero AWS SDKs — only native fetch is used.
 */

import React, { useCallback, useState } from "react";
import { useSession } from "next-auth/react";
import { CheckCircle2, Loader2 } from "lucide-react";
import { VideoUploader, DsaiStagedVideo, DsaiUploadStatus } from "@/components/upload/VideoUploader";
import { dsai_apiPost } from "@/lib/api/dsai_client";
import { CameraSelector } from "@/components/camera/CameraSelector";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DsaiPresignResponse {
  upload_url: string;
  video_uri: string;
}

interface DsaiUploadItemState {
  dsai_id: string;
  dsai_status: DsaiUploadStatus;
  dsai_progress: number;
  dsai_errorMessage: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * dsai_putFileToMinio — uploads a file directly to a MinIO presigned URL
 * using native fetch with a ReadableStream body for progress tracking.
 *
 * Note: XHR is used here because fetch() does not expose upload progress events.
 */
function dsai_putFileToMinio(
  dsai_presignedUrl: string,
  dsai_file: File,
  dsai_onProgress: (dsai_percent: number) => void
): Promise<void> {
  return new Promise((dsai_resolve, dsai_reject) => {
    const dsai_xhr = new XMLHttpRequest();
    dsai_xhr.open("PUT", dsai_presignedUrl);
    dsai_xhr.setRequestHeader("Content-Type", dsai_file.type || "video/mp4");

    dsai_xhr.upload.addEventListener("progress", (dsai_e) => {
      if (dsai_e.lengthComputable) {
        dsai_onProgress(Math.round((dsai_e.loaded / dsai_e.total) * 100));
      }
    });

    dsai_xhr.addEventListener("load", () => {
      if (dsai_xhr.status >= 200 && dsai_xhr.status < 300) {
        dsai_onProgress(100);
        dsai_resolve();
      } else {
        dsai_reject(new Error(`MinIO PUT failed: HTTP ${dsai_xhr.status}`));
      }
    });

    dsai_xhr.addEventListener("error", () => {
      dsai_reject(new Error("Network error during MinIO upload"));
    });

    dsai_xhr.send(dsai_file);
  });
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function IngestPage() {
  const { data: dsai_session } = useSession();
  const dsai_accessToken = (dsai_session as any)?.dsai_accessToken as string | undefined;
  const dsai_tenantId = (dsai_session as any)?.dsai_tenantId as string | undefined;

  const [dsai_itemStates, dsai_setItemStates] = useState<Map<string, DsaiUploadItemState>>(new Map());
  const [dsai_globalError, dsai_setGlobalError] = useState<string | null>(null);
  const [dsai_selectedCameras, dsai_setSelectedCameras] = useState<string[]>([]);

  // Update a single item's state
  const dsai_updateItem = useCallback(
    (dsai_id: string, dsai_patch: Partial<DsaiUploadItemState>) => {
      dsai_setItemStates((dsai_prev) => {
        const dsai_next = new Map(dsai_prev);
        const dsai_existing = dsai_next.get(dsai_id) ?? {
          dsai_id,
          dsai_status: "pending" as DsaiUploadStatus,
          dsai_progress: 0,
          dsai_errorMessage: null,
        };
        dsai_next.set(dsai_id, { ...dsai_existing, ...dsai_patch });
        return dsai_next;
      });
    },
    []
  );

  // ------------------------------------------------------------------
  // Upload one video through the two-step flow
  // ------------------------------------------------------------------
  const dsai_uploadOne = useCallback(
    async (dsai_item: DsaiStagedVideo) => {
      if (!dsai_accessToken || !dsai_tenantId) return;

      dsai_updateItem(dsai_item.dsai_id, { dsai_status: "uploading", dsai_progress: 0 });

      try {
        // Step 1: Request presigned URL
        const dsai_presign = await dsai_apiPost<DsaiPresignResponse>(
          "server/upload/request-url",
          dsai_accessToken,
          dsai_tenantId,
          {
            filename: dsai_item.dsai_name,
            content_type: dsai_item.dsai_file.type || "video/mp4",
            tenant_id: dsai_tenantId,
          }
        );

        if (!dsai_presign?.upload_url || !dsai_presign?.video_uri) {
          throw new Error("Backend did not return a valid presigned URL.");
        }

        // Step 2: Browser PUT directly to MinIO (zero AWS SDKs)
        await dsai_putFileToMinio(
          dsai_presign.upload_url,
          dsai_item.dsai_file,
          (dsai_pct) => dsai_updateItem(dsai_item.dsai_id, { dsai_progress: dsai_pct })
        );

        // Step 3: Dispatch processing
        dsai_updateItem(dsai_item.dsai_id, { dsai_status: "processing", dsai_progress: 100 });

        await dsai_apiPost(
          "server/process_video",
          dsai_accessToken,
          dsai_tenantId,
          {
            video_uri: dsai_presign.video_uri,
            camera_id: dsai_item.dsai_cameraId,
            tenant_id: dsai_tenantId,
          }
        );

        dsai_updateItem(dsai_item.dsai_id, { dsai_status: "complete" });
      } catch (dsai_err) {
        dsai_updateItem(dsai_item.dsai_id, {
          dsai_status: "failed",
          dsai_errorMessage: dsai_err instanceof Error ? dsai_err.message : "Upload failed",
        });
      }
    },
    [dsai_accessToken, dsai_tenantId, dsai_updateItem]
  );

  // ------------------------------------------------------------------
  // Start all staged uploads (concurrent, up to 3 at a time)
  // ------------------------------------------------------------------
  const dsai_handleStartUpload = useCallback(
    async (dsai_items: DsaiStagedVideo[]) => {
      dsai_setGlobalError(null);
      if (!dsai_accessToken || !dsai_tenantId) {
        dsai_setGlobalError("Session expired. Please log in again.");
        return;
      }

      // Sequential uploads to avoid hammering MinIO
      for (const dsai_item of dsai_items) {
        await dsai_uploadOne(dsai_item);
      }
    },
    [dsai_accessToken, dsai_tenantId, dsai_uploadOne]
  );

  // Count completions
  const dsai_completeCount = Array.from(dsai_itemStates.values()).filter(
    (dsai_s) => dsai_s.dsai_status === "complete"
  ).length;
  const dsai_totalCount = dsai_itemStates.size;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Video Ingest</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Upload video files directly to MinIO — zero cloud SDK dependencies.
        </p>
      </div>

      {/* Architecture note */}
      <div className="rounded-lg bg-muted/40 border px-4 py-3 text-xs text-muted-foreground space-y-0.5">
        <p className="font-medium text-foreground">Two-step upload flow (Zero AWS SDKs)</p>
        <p>1. UI requests a presigned PUT URL from the backend (POST /upload/request-url).</p>
        <p>2. Browser uploads the video file directly to MinIO via native XHR — no AWS SDK.</p>
        <p>3. Backend dispatches segmentation via POST /process_video.</p>
      </div>

      {/* Global error */}
      {dsai_globalError && (
        <div className="rounded-md border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {dsai_globalError}
        </div>
      )}

      {/* Completion summary */}
      {dsai_totalCount > 0 && dsai_completeCount > 0 && (
        <div className="flex items-center gap-2 rounded-md bg-green-50 border border-green-200 px-4 py-3 text-sm text-green-700">
          <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
          {dsai_completeCount} of {dsai_totalCount} video{dsai_totalCount !== 1 ? "s" : ""} dispatched
          for processing.
        </div>
      )}

      {/* VideoUploader */}
      <VideoUploader
        dsai_onStartUpload={dsai_handleStartUpload}
        dsai_cameraOptions={dsai_selectedCameras}
      />

      {/* Camera pre-selection helper */}
      <div className="rounded-lg border bg-card p-4 space-y-3">
        <h2 className="text-sm font-semibold">Camera Pre-selection</h2>
        <p className="text-xs text-muted-foreground">
          Select cameras to pre-populate the camera dropdown for each staged video.
        </p>
        <CameraSelector
          dsai_value={dsai_selectedCameras}
          dsai_onChange={dsai_setSelectedCameras}
          dsai_placeholder="Select cameras"
        />
      </div>

      {/* Per-item progress (live feedback) */}
      {dsai_itemStates.size > 0 && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold">Upload Progress</h2>
          {Array.from(dsai_itemStates.values()).map((dsai_s) => (
            <div key={dsai_s.dsai_id} className="rounded-md border bg-card p-3 space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="font-mono text-muted-foreground truncate max-w-xs">{dsai_s.dsai_id.split("-")[0]}</span>
                <span className="capitalize font-medium">{dsai_s.dsai_status}</span>
              </div>
              {(dsai_s.dsai_status === "uploading" || dsai_s.dsai_status === "processing") && (
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full bg-primary transition-all"
                      style={{ width: `${dsai_s.dsai_progress}%` }}
                    />
                  </div>
                  <span className="text-xs text-muted-foreground w-8 text-right">
                    {dsai_s.dsai_status === "uploading" ? `${dsai_s.dsai_progress}%` : <Loader2 className="h-3 w-3 animate-spin inline" />}
                  </span>
                </div>
              )}
              {dsai_s.dsai_errorMessage && (
                <p className="text-xs text-destructive">{dsai_s.dsai_errorMessage}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
