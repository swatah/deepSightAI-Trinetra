"use client";

/**
 * VideoUploader — Issue #38.
 *
 * Drag-and-drop video staging component with:
 *   - Visual drop target supporting dragover highlight and click-to-browse
 *   - Supported extensions: .mp4, .mkv, .avi, .mov
 *   - Max file size validation (2GB)
 *   - Client-side video preview: hidden <video> element to extract duration and canvas thumbnail
 *   - Staged queue: filename, size, duration, status badge
 *   - Camera selector dropdown to assign camera ID
 *   - Batch upload "Start All" button
 *
 * Props:
 *   dsai_onStartUpload(dsai_items) — called when operator clicks "Start All"
 */

import React, { useCallback, useRef, useState } from "react";
import { Film, Loader2, Upload, X } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type DsaiUploadStatus = "pending" | "uploading" | "processing" | "complete" | "failed";

export interface DsaiStagedVideo {
  dsai_id: string;
  dsai_file: File;
  dsai_name: string;
  dsai_sizeMb: number;
  dsai_durationSec: number | null;
  dsai_thumbnailDataUrl: string | null;
  dsai_cameraId: string;
  dsai_status: DsaiUploadStatus;
  dsai_errorMessage: string | null;
}

export interface DsaiVideoUploaderProps {
  /** Called with staged items when the operator presses "Start All". */
  dsai_onStartUpload: (dsai_items: DsaiStagedVideo[]) => void;
  /** Available camera IDs to assign. Empty array shows a free-text input. */
  dsai_cameraOptions?: string[];
  /** Default camera ID for newly staged videos. */
  dsai_defaultCameraId?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DSAI_ALLOWED_EXTENSIONS = [".mp4", ".mkv", ".avi", ".mov"];
const DSAI_ALLOWED_MIME_TYPES = ["video/mp4", "video/x-matroska", "video/x-msvideo", "video/quicktime"];
const DSAI_MAX_SIZE_BYTES = 2 * 1024 * 1024 * 1024; // 2GB
const DSAI_MAX_SIZE_LABEL = "2GB";

const DSAI_STATUS_BADGE: Record<DsaiUploadStatus, { dsai_label: string; dsai_class: string }> = {
  pending: { dsai_label: "Pending", dsai_class: "bg-gray-100 text-gray-700" },
  uploading: { dsai_label: "Uploading", dsai_class: "bg-blue-100 text-blue-700" },
  processing: { dsai_label: "Processing", dsai_class: "bg-yellow-100 text-yellow-800" },
  complete: { dsai_label: "Complete", dsai_class: "bg-green-100 text-green-700" },
  failed: { dsai_label: "Failed", dsai_class: "bg-red-100 text-red-700" },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function dsai_formatBytes(dsai_bytes: number): string {
  if (dsai_bytes < 1024) return `${dsai_bytes} B`;
  if (dsai_bytes < 1024 * 1024) return `${(dsai_bytes / 1024).toFixed(1)} KB`;
  if (dsai_bytes < 1024 * 1024 * 1024) return `${(dsai_bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(dsai_bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function dsai_formatDuration(dsai_sec: number): string {
  const dsai_m = Math.floor(dsai_sec / 60);
  const dsai_s = Math.floor(dsai_sec % 60);
  return `${dsai_m}:${String(dsai_s).padStart(2, "0")}`;
}

function dsai_isAllowedFile(dsai_file: File): boolean {
  const dsai_ext = "." + dsai_file.name.split(".").pop()?.toLowerCase();
  return (
    DSAI_ALLOWED_EXTENSIONS.includes(dsai_ext) ||
    DSAI_ALLOWED_MIME_TYPES.some((dsai_m) => dsai_file.type.startsWith(dsai_m.split("/")[0]) && dsai_m === dsai_file.type)
  );
}

/**
 * dsai_extractVideoMeta — loads the file into a hidden <video> element
 * to extract duration and capture a canvas thumbnail at the 1-second mark.
 */
async function dsai_extractVideoMeta(
  dsai_file: File
): Promise<{ dsai_durationSec: number | null; dsai_thumbnailDataUrl: string | null }> {
  return new Promise((dsai_resolve) => {
    const dsai_video = document.createElement("video");
    dsai_video.muted = true;
    dsai_video.preload = "metadata";
    const dsai_objectUrl = URL.createObjectURL(dsai_file);
    dsai_video.src = dsai_objectUrl;

    const dsai_cleanup = () => {
      URL.revokeObjectURL(dsai_objectUrl);
    };

    dsai_video.addEventListener("loadedmetadata", () => {
      dsai_video.currentTime = Math.min(1, dsai_video.duration * 0.1);
    });

    dsai_video.addEventListener("seeked", () => {
      try {
        const dsai_canvas = document.createElement("canvas");
        dsai_canvas.width = 320;
        dsai_canvas.height = Math.round((dsai_video.videoHeight / dsai_video.videoWidth) * 320) || 180;
        const dsai_ctx = dsai_canvas.getContext("2d");
        dsai_ctx?.drawImage(dsai_video, 0, 0, dsai_canvas.width, dsai_canvas.height);
        const dsai_dataUrl = dsai_canvas.toDataURL("image/jpeg", 0.7);
        dsai_cleanup();
        dsai_resolve({
          dsai_durationSec: isFinite(dsai_video.duration) ? dsai_video.duration : null,
          dsai_thumbnailDataUrl: dsai_dataUrl,
        });
      } catch {
        dsai_cleanup();
        dsai_resolve({ dsai_durationSec: null, dsai_thumbnailDataUrl: null });
      }
    });

    dsai_video.addEventListener("error", () => {
      dsai_cleanup();
      dsai_resolve({ dsai_durationSec: null, dsai_thumbnailDataUrl: null });
    });

    // Timeout safety
    setTimeout(() => {
      dsai_cleanup();
      dsai_resolve({ dsai_durationSec: null, dsai_thumbnailDataUrl: null });
    }, 5_000);
  });
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function DsaiStatusBadge({ dsai_status }: { dsai_status: DsaiUploadStatus }) {
  const dsai_config = DSAI_STATUS_BADGE[dsai_status];
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${dsai_config.dsai_class}`}>
      {dsai_status === "uploading" && <Loader2 className="h-3 w-3 animate-spin" />}
      {dsai_config.dsai_label}
    </span>
  );
}

function DsaiQueueItem({
  dsai_item,
  dsai_cameraOptions,
  dsai_onCameraChange,
  dsai_onRemove,
}: {
  dsai_item: DsaiStagedVideo;
  dsai_cameraOptions: string[];
  dsai_onCameraChange: (dsai_id: string, dsai_cameraId: string) => void;
  dsai_onRemove: (dsai_id: string) => void;
}) {
  const dsai_isActive = dsai_item.dsai_status === "uploading" || dsai_item.dsai_status === "processing";
  return (
    <div className="flex gap-3 rounded-lg border bg-card p-3">
      {/* Thumbnail */}
      <div className="flex-shrink-0 h-16 w-24 rounded border overflow-hidden bg-muted flex items-center justify-center">
        {dsai_item.dsai_thumbnailDataUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={dsai_item.dsai_thumbnailDataUrl}
            alt="video preview"
            className="h-full w-full object-cover"
          />
        ) : (
          <Film className="h-6 w-6 text-muted-foreground" />
        )}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-medium truncate" title={dsai_item.dsai_name}>
            {dsai_item.dsai_name}
          </p>
          <DsaiStatusBadge dsai_status={dsai_item.dsai_status} />
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>{dsai_formatBytes(dsai_item.dsai_file.size)}</span>
          {dsai_item.dsai_durationSec != null && (
            <span>{dsai_formatDuration(dsai_item.dsai_durationSec)}</span>
          )}
        </div>
        {dsai_item.dsai_errorMessage && (
          <p className="text-xs text-destructive">{dsai_item.dsai_errorMessage}</p>
        )}

        {/* Camera selector */}
        <div className="flex items-center gap-2 mt-1">
          <label className="text-xs text-muted-foreground whitespace-nowrap">Camera:</label>
          {dsai_cameraOptions.length > 0 ? (
            <select
              value={dsai_item.dsai_cameraId}
              onChange={(dsai_e) => dsai_onCameraChange(dsai_item.dsai_id, dsai_e.target.value)}
              disabled={dsai_isActive}
              className="text-xs rounded border border-input bg-background px-2 py-1 focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
            >
              {dsai_cameraOptions.map((dsai_c) => (
                <option key={dsai_c} value={dsai_c}>{dsai_c}</option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              value={dsai_item.dsai_cameraId}
              onChange={(dsai_e) => dsai_onCameraChange(dsai_item.dsai_id, dsai_e.target.value)}
              disabled={dsai_isActive}
              placeholder="cam-id"
              className="text-xs rounded border border-input bg-background px-2 py-1 focus:outline-none focus:ring-1 focus:ring-ring w-32 disabled:opacity-50"
            />
          )}
        </div>
      </div>

      {/* Remove */}
      {!dsai_isActive && (
        <button
          onClick={() => dsai_onRemove(dsai_item.dsai_id)}
          className="flex-shrink-0 text-muted-foreground hover:text-destructive self-start mt-0.5"
          title="Remove"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// VideoUploader (exported component)
// ---------------------------------------------------------------------------

export function VideoUploader({
  dsai_onStartUpload,
  dsai_cameraOptions = [],
  dsai_defaultCameraId = "",
}: DsaiVideoUploaderProps) {
  const [dsai_items, dsai_setItems] = useState<DsaiStagedVideo[]>([]);
  const [dsai_isDragOver, dsai_setIsDragOver] = useState(false);
  const [dsai_rejection, dsai_setRejection] = useState<string | null>(null);
  const [dsai_extracting, dsai_setExtracting] = useState(false);

  const dsai_inputRef = useRef<HTMLInputElement>(null);

  // ------------------------------------------------------------------
  // File validation & staging
  // ------------------------------------------------------------------
  const dsai_stageFiles = useCallback(
    async (dsai_files: FileList | File[]) => {
      dsai_setRejection(null);
      const dsai_newItems: DsaiStagedVideo[] = [];
      const dsai_rejections: string[] = [];

      for (const dsai_file of Array.from(dsai_files)) {
        if (!dsai_isAllowedFile(dsai_file)) {
          dsai_rejections.push(`${dsai_file.name}: unsupported format (allowed: ${DSAI_ALLOWED_EXTENSIONS.join(", ")})`);
          continue;
        }
        if (dsai_file.size > DSAI_MAX_SIZE_BYTES) {
          dsai_rejections.push(`${dsai_file.name}: exceeds ${DSAI_MAX_SIZE_LABEL} size limit`);
          continue;
        }

        dsai_newItems.push({
          dsai_id: `${dsai_file.name}-${Date.now()}-${Math.random()}`,
          dsai_file,
          dsai_name: dsai_file.name,
          dsai_sizeMb: dsai_file.size / 1024 / 1024,
          dsai_durationSec: null,
          dsai_thumbnailDataUrl: null,
          dsai_cameraId: dsai_defaultCameraId || (dsai_cameraOptions[0] ?? ""),
          dsai_status: "pending",
          dsai_errorMessage: null,
        });
      }

      if (dsai_rejections.length > 0) {
        dsai_setRejection(dsai_rejections.join(" | "));
      }

      if (dsai_newItems.length === 0) return;

      // Append immediately (without thumbnails)
      dsai_setItems((dsai_prev) => [...dsai_prev, ...dsai_newItems]);

      // Enrich with thumbnails asynchronously
      dsai_setExtracting(true);
      const dsai_enriched = await Promise.all(
        dsai_newItems.map(async (dsai_item) => {
          const dsai_meta = await dsai_extractVideoMeta(dsai_item.dsai_file);
          return { ...dsai_item, ...dsai_meta };
        })
      );
      dsai_setItems((dsai_prev) =>
        dsai_prev.map((dsai_p) => {
          const dsai_updated = dsai_enriched.find((dsai_u) => dsai_u.dsai_id === dsai_p.dsai_id);
          return dsai_updated ?? dsai_p;
        })
      );
      dsai_setExtracting(false);
    },
    [dsai_defaultCameraId, dsai_cameraOptions]
  );

  // ------------------------------------------------------------------
  // Drag-and-drop handlers
  // ------------------------------------------------------------------
  const dsai_handleDragOver = useCallback((dsai_e: React.DragEvent) => {
    dsai_e.preventDefault();
    dsai_setIsDragOver(true);
  }, []);

  const dsai_handleDragLeave = useCallback(() => {
    dsai_setIsDragOver(false);
  }, []);

  const dsai_handleDrop = useCallback(
    async (dsai_e: React.DragEvent) => {
      dsai_e.preventDefault();
      dsai_setIsDragOver(false);
      await dsai_stageFiles(dsai_e.dataTransfer.files);
    },
    [dsai_stageFiles]
  );

  const dsai_handleInputChange = useCallback(
    async (dsai_e: React.ChangeEvent<HTMLInputElement>) => {
      if (dsai_e.target.files) await dsai_stageFiles(dsai_e.target.files);
      // reset input so the same file can be re-added
      dsai_e.target.value = "";
    },
    [dsai_stageFiles]
  );

  // ------------------------------------------------------------------
  // Camera change / remove
  // ------------------------------------------------------------------
  const dsai_handleCameraChange = useCallback((dsai_id: string, dsai_cameraId: string) => {
    dsai_setItems((dsai_prev) =>
      dsai_prev.map((dsai_i) => (dsai_i.dsai_id === dsai_id ? { ...dsai_i, dsai_cameraId } : dsai_i))
    );
  }, []);

  const dsai_handleRemove = useCallback((dsai_id: string) => {
    dsai_setItems((dsai_prev) => dsai_prev.filter((dsai_i) => dsai_i.dsai_id !== dsai_id));
  }, []);

  // ------------------------------------------------------------------
  // Start upload
  // ------------------------------------------------------------------
  const dsai_pendingItems = dsai_items.filter((dsai_i) => dsai_i.dsai_status === "pending");

  const dsai_handleStartAll = useCallback(() => {
    if (dsai_pendingItems.length === 0) return;
    dsai_onStartUpload(dsai_pendingItems);
  }, [dsai_pendingItems, dsai_onStartUpload]);

  return (
    <div className="space-y-4">
      {/* Drop zone */}
      <div
        className={`relative flex flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed px-8 py-10 transition-colors cursor-pointer ${
          dsai_isDragOver
            ? "border-primary bg-primary/5"
            : "border-border hover:border-primary/50 hover:bg-muted/30"
        }`}
        onDragOver={dsai_handleDragOver}
        onDragLeave={dsai_handleDragLeave}
        onDrop={dsai_handleDrop}
        onClick={() => dsai_inputRef.current?.click()}
      >
        <div className={`rounded-full p-4 ${dsai_isDragOver ? "bg-primary/10" : "bg-muted"}`}>
          <Upload className={`h-8 w-8 ${dsai_isDragOver ? "text-primary" : "text-muted-foreground"}`} />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium">
            Drag &amp; drop video files here, or{" "}
            <span className="text-primary hover:underline">browse</span>
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            Supported: {DSAI_ALLOWED_EXTENSIONS.join(", ")} — Max {DSAI_MAX_SIZE_LABEL} per file
          </p>
        </div>
        <input
          ref={dsai_inputRef}
          type="file"
          accept={DSAI_ALLOWED_EXTENSIONS.join(",")}
          multiple
          className="hidden"
          onChange={dsai_handleInputChange}
        />
      </div>

      {/* Validation error */}
      {dsai_rejection && (
        <div className="rounded-md border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {dsai_rejection}
        </div>
      )}

      {/* Extracting indicator */}
      {dsai_extracting && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Extracting video metadata…
        </div>
      )}

      {/* Staged queue */}
      {dsai_items.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">
              Staged Videos ({dsai_items.length})
            </h3>
            <button
              onClick={dsai_handleStartAll}
              disabled={dsai_pendingItems.length === 0 || dsai_extracting}
              className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Upload className="h-4 w-4" />
              Start All ({dsai_pendingItems.length})
            </button>
          </div>

          <div className="space-y-2">
            {dsai_items.map((dsai_item) => (
              <DsaiQueueItem
                key={dsai_item.dsai_id}
                dsai_item={dsai_item}
                dsai_cameraOptions={dsai_cameraOptions}
                dsai_onCameraChange={dsai_handleCameraChange}
                dsai_onRemove={dsai_handleRemove}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default VideoUploader;
