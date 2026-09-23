"use client";

/**
 * RTSP Stream Manager page — Phase 6, Issue #40.
 *
 * Ingestion-only control panel (browsers cannot render raw RTSP per Phase 0 decision 6).
 *
 * Features:
 *   - RTSP URL validation: rtsp://[user:pass@]host[:port]/path
 *   - Start ingestion: POST /process_rtsp_stream
 *   - Stop ingestion: POST /rtsp/stop
 *   - Stream health: poll GET /rtsp_status every 5s
 *   - Status badges: Active (Green), Stalled (Yellow), Stopped (Gray)
 *   - Metrics cards: Ingested Frames, Current FPS, Worker PID/Status, Uptime, Error Count
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock,
  Cpu,
  Loader2,
  Play,
  RefreshCw,
  Square,
  Wifi,
  WifiOff,
} from "lucide-react";
import { dsai_apiFetch, dsai_apiGet, dsai_apiPost } from "@/lib/api/dsai_client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DsaiRtspStatusEntry {
  dsai_cameraId: string;
  dsai_rtspUrl: string;
  dsai_workerPid: number | null;
  dsai_status: "active" | "stalled" | "stopped" | "error" | string;
  dsai_ingestedFrames: number;
  dsai_currentFps: number;
  dsai_uptimeSec: number;
  dsai_errorCount: number;
}

interface DsaiRtspStatusApiEntry {
  camera_id?: string;
  rtsp_url?: string;
  worker_pid?: number | null;
  status?: string;
  ingested_frames?: number;
  current_fps?: number;
  uptime_sec?: number;
  error_count?: number;
  frames_ingested?: number;
  fps?: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Polling interval for stream health */
const DSAI_STATUS_POLL_MS = 5_000;

/** RTSP URL regex — accepts rtsp://[user:pass@]host[:port]/path */
const DSAI_RTSP_URL_REGEX = /^rtsp:\/\/([^@]+@)?[a-zA-Z0-9.\-_]+(:\d+)?(\/[^\s]*)?$/;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function dsai_mapStatus(dsai_raw: DsaiRtspStatusApiEntry): DsaiRtspStatusEntry {
  return {
    dsai_cameraId: dsai_raw.camera_id ?? "",
    dsai_rtspUrl: dsai_raw.rtsp_url ?? "",
    dsai_workerPid: dsai_raw.worker_pid ?? null,
    dsai_status: dsai_raw.status ?? "stopped",
    dsai_ingestedFrames: dsai_raw.ingested_frames ?? dsai_raw.frames_ingested ?? 0,
    dsai_currentFps: dsai_raw.current_fps ?? dsai_raw.fps ?? 0,
    dsai_uptimeSec: dsai_raw.uptime_sec ?? 0,
    dsai_errorCount: dsai_raw.error_count ?? 0,
  };
}

function dsai_formatUptime(dsai_sec: number): string {
  const dsai_h = Math.floor(dsai_sec / 3600);
  const dsai_m = Math.floor((dsai_sec % 3600) / 60);
  const dsai_s = Math.floor(dsai_sec % 60);
  if (dsai_h > 0) return `${dsai_h}h ${dsai_m}m`;
  if (dsai_m > 0) return `${dsai_m}m ${dsai_s}s`;
  return `${dsai_s}s`;
}

function dsai_getStatusBadge(dsai_status: string): { dsai_label: string; dsai_class: string } {
  switch (dsai_status) {
    case "active":
      return { dsai_label: "Active", dsai_class: "bg-green-100 text-green-700 border-green-200" };
    case "stalled":
      return { dsai_label: "Stalled", dsai_class: "bg-yellow-100 text-yellow-800 border-yellow-200" };
    case "error":
      return { dsai_label: "Error", dsai_class: "bg-red-100 text-red-700 border-red-200" };
    default:
      return { dsai_label: "Stopped", dsai_class: "bg-gray-100 text-gray-600 border-gray-200" };
  }
}

// ---------------------------------------------------------------------------
// Metric card
// ---------------------------------------------------------------------------

function DsaiMetricCard({
  dsai_icon: DsaiIcon,
  dsai_label,
  dsai_value,
}: {
  dsai_icon: React.ElementType;
  dsai_label: string;
  dsai_value: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-4 flex items-center gap-3">
      <div className="rounded-md bg-muted p-2">
        <DsaiIcon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div>
        <p className="text-xs text-muted-foreground">{dsai_label}</p>
        <p className="text-sm font-semibold">{dsai_value}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stream status row
// ---------------------------------------------------------------------------

function DsaiStreamRow({
  dsai_entry,
  dsai_onStop,
  dsai_stopping,
}: {
  dsai_entry: DsaiRtspStatusEntry;
  dsai_onStop: (dsai_cameraId: string) => void;
  dsai_stopping: boolean;
}) {
  const dsai_badge = dsai_getStatusBadge(dsai_entry.dsai_status);

  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      {/* Header row */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="space-y-0.5">
          <p className="font-mono text-sm font-medium">{dsai_entry.dsai_cameraId}</p>
          <p className="text-xs text-muted-foreground truncate max-w-xs" title={dsai_entry.dsai_rtspUrl}>
            {dsai_entry.dsai_rtspUrl}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-medium ${dsai_badge.dsai_class}`}
          >
            {dsai_entry.dsai_status === "active" ? (
              <Wifi className="h-3 w-3" />
            ) : dsai_entry.dsai_status === "stalled" ? (
              <AlertCircle className="h-3 w-3" />
            ) : (
              <WifiOff className="h-3 w-3" />
            )}
            {dsai_badge.dsai_label}
          </span>
          {dsai_entry.dsai_status === "active" || dsai_entry.dsai_status === "stalled" ? (
            <button
              onClick={() => dsai_onStop(dsai_entry.dsai_cameraId)}
              disabled={dsai_stopping}
              className="flex items-center gap-1.5 rounded-md bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
            >
              {dsai_stopping ? <Loader2 className="h-3 w-3 animate-spin" /> : <Square className="h-3 w-3" />}
              Stop
            </button>
          ) : null}
        </div>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <DsaiMetricCard
          dsai_icon={Activity}
          dsai_label="Frames"
          dsai_value={dsai_entry.dsai_ingestedFrames.toLocaleString()}
        />
        <DsaiMetricCard
          dsai_icon={RefreshCw}
          dsai_label="FPS"
          dsai_value={dsai_entry.dsai_currentFps.toFixed(1)}
        />
        <DsaiMetricCard
          dsai_icon={Cpu}
          dsai_label="Worker PID"
          dsai_value={dsai_entry.dsai_workerPid != null ? String(dsai_entry.dsai_workerPid) : "—"}
        />
        <DsaiMetricCard
          dsai_icon={Clock}
          dsai_label="Uptime"
          dsai_value={dsai_entry.dsai_uptimeSec > 0 ? dsai_formatUptime(dsai_entry.dsai_uptimeSec) : "—"}
        />
      </div>
      {dsai_entry.dsai_errorCount > 0 && (
        <p className="text-xs text-destructive flex items-center gap-1">
          <AlertCircle className="h-3 w-3" />
          {dsai_entry.dsai_errorCount} extraction error{dsai_entry.dsai_errorCount !== 1 ? "s" : ""} logged
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function RtspPage() {
  const { data: dsai_session } = useSession();
  const dsai_accessToken = (dsai_session as any)?.dsai_accessToken as string | undefined;
  const dsai_tenantId = (dsai_session as any)?.dsai_tenantId as string | undefined;

  // Form state
  const [dsai_rtspUrl, dsai_setRtspUrl] = useState("");
  const [dsai_cameraId, dsai_setCameraId] = useState("");
  const [dsai_formError, dsai_setFormError] = useState<string | null>(null);
  const [dsai_starting, dsai_setStarting] = useState(false);
  const [dsai_startSuccess, dsai_setStartSuccess] = useState<string | null>(null);

  // Stream status
  const [dsai_streams, dsai_setStreams] = useState<DsaiRtspStatusEntry[]>([]);
  const [dsai_statusLoading, dsai_setStatusLoading] = useState(true);
  const [dsai_statusError, dsai_setStatusError] = useState<string | null>(null);
  const [dsai_stoppingId, dsai_setStoppingId] = useState<string | null>(null);

  const dsai_pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ------------------------------------------------------------------
  // Poll stream health every 5s
  // ------------------------------------------------------------------
  const dsai_fetchStatus = useCallback(async () => {
    if (!dsai_accessToken || !dsai_tenantId) return;
    try {
      const dsai_data = await dsai_apiGet<DsaiRtspStatusApiEntry[] | { streams?: DsaiRtspStatusApiEntry[] }>(
        "server/rtsp_status",
        dsai_accessToken,
        dsai_tenantId
      );
      const dsai_rawItems: DsaiRtspStatusApiEntry[] = Array.isArray(dsai_data)
        ? dsai_data
        : (dsai_data as any)?.streams ?? [];
      dsai_setStreams(dsai_rawItems.map(dsai_mapStatus));
      dsai_setStatusError(null);
    } catch (dsai_err) {
      dsai_setStatusError(dsai_err instanceof Error ? dsai_err.message : "Status fetch failed");
    } finally {
      dsai_setStatusLoading(false);
    }
  }, [dsai_accessToken, dsai_tenantId]);

  useEffect(() => {
    dsai_fetchStatus();
    dsai_pollRef.current = setInterval(dsai_fetchStatus, DSAI_STATUS_POLL_MS);
    return () => {
      if (dsai_pollRef.current) clearInterval(dsai_pollRef.current);
    };
  }, [dsai_fetchStatus]);

  // ------------------------------------------------------------------
  // Start ingestion
  // ------------------------------------------------------------------
  const dsai_handleStart = useCallback(async () => {
    dsai_setFormError(null);
    dsai_setStartSuccess(null);

    if (!dsai_rtspUrl.trim()) {
      dsai_setFormError("RTSP URL is required.");
      return;
    }
    if (!DSAI_RTSP_URL_REGEX.test(dsai_rtspUrl.trim())) {
      dsai_setFormError("Invalid RTSP URL format. Expected: rtsp://[user:pass@]host[:port]/path");
      return;
    }
    if (!dsai_cameraId.trim()) {
      dsai_setFormError("Camera ID is required.");
      return;
    }
    if (!dsai_accessToken || !dsai_tenantId) {
      dsai_setFormError("Session expired. Please log in again.");
      return;
    }

    dsai_setStarting(true);
    try {
      await dsai_apiPost("server/process_rtsp_stream", dsai_accessToken, dsai_tenantId, {
        rtsp_url: dsai_rtspUrl.trim(),
        camera_id: dsai_cameraId.trim(),
        tenant_id: dsai_tenantId,
      });
      dsai_setStartSuccess(`Ingestion started for camera: ${dsai_cameraId.trim()}`);
      dsai_setRtspUrl("");
      dsai_setCameraId("");
      // Refresh status immediately
      await dsai_fetchStatus();
    } catch (dsai_err) {
      dsai_setFormError(dsai_err instanceof Error ? dsai_err.message : "Failed to start ingestion.");
    } finally {
      dsai_setStarting(false);
    }
  }, [dsai_rtspUrl, dsai_cameraId, dsai_accessToken, dsai_tenantId, dsai_fetchStatus]);

  // ------------------------------------------------------------------
  // Stop ingestion
  // ------------------------------------------------------------------
  const dsai_handleStop = useCallback(
    async (dsai_camId: string) => {
      if (!dsai_accessToken || !dsai_tenantId) return;
      dsai_setStoppingId(dsai_camId);
      try {
        await dsai_apiFetch("server/rtsp/stop", dsai_accessToken, dsai_tenantId, {
          method: "POST",
          body: JSON.stringify({ camera_id: dsai_camId, tenant_id: dsai_tenantId }),
        });
        await dsai_fetchStatus();
      } catch (dsai_err) {
        dsai_setStatusError(dsai_err instanceof Error ? dsai_err.message : "Stop failed.");
      } finally {
        dsai_setStoppingId(null);
      }
    },
    [dsai_accessToken, dsai_tenantId, dsai_fetchStatus]
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">RTSP Stream Manager</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Start and stop RTSP ingestion streams. Frame extraction status updates every 5 seconds.
        </p>
        <p className="text-xs text-muted-foreground mt-0.5">
          Note: This is an ingestion-only panel. Browsers cannot render raw RTSP streams (Phase 0 decision 6).
        </p>
      </div>

      {/* Start form */}
      <div className="rounded-lg border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">Start New Ingestion</h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* RTSP URL */}
          <div className="space-y-1.5 sm:col-span-2">
            <label className="text-sm font-medium">RTSP URL</label>
            <input
              type="text"
              value={dsai_rtspUrl}
              onChange={(dsai_e) => {
                dsai_setRtspUrl(dsai_e.target.value);
                dsai_setFormError(null);
              }}
              placeholder="rtsp://user:pass@192.168.1.10:554/stream"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring font-mono"
            />
            <p className="text-xs text-muted-foreground">
              Format: rtsp://[user:pass@]host[:port]/path
            </p>
          </div>

          {/* Camera ID */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Camera ID</label>
            <input
              type="text"
              value={dsai_cameraId}
              onChange={(dsai_e) => {
                dsai_setCameraId(dsai_e.target.value);
                dsai_setFormError(null);
              }}
              placeholder="e.g. cam-entrance-01"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
        </div>

        {dsai_formError && (
          <p className="text-sm text-destructive flex items-center gap-1.5">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            {dsai_formError}
          </p>
        )}

        {dsai_startSuccess && (
          <p className="text-sm text-green-600 flex items-center gap-1.5">
            <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
            {dsai_startSuccess}
          </p>
        )}

        <button
          onClick={dsai_handleStart}
          disabled={dsai_starting || !dsai_rtspUrl.trim() || !dsai_cameraId.trim()}
          className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {dsai_starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          Start Ingestion
        </button>
      </div>

      {/* Stream health monitor */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Active Streams</h2>
          <button
            onClick={dsai_fetchStatus}
            disabled={dsai_statusLoading}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${dsai_statusLoading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>

        {dsai_statusError && (
          <div className="rounded-md border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {dsai_statusError}
          </div>
        )}

        {dsai_statusLoading && dsai_streams.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : dsai_streams.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 rounded-lg border bg-card text-muted-foreground text-sm gap-2">
            <WifiOff className="h-8 w-8" />
            <p>No active RTSP streams. Start one above.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {dsai_streams.map((dsai_s) => (
              <DsaiStreamRow
                key={dsai_s.dsai_cameraId}
                dsai_entry={dsai_s}
                dsai_onStop={dsai_handleStop}
                dsai_stopping={dsai_stoppingId === dsai_s.dsai_cameraId}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
