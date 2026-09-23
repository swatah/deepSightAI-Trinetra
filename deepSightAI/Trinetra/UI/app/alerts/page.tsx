"use client";

/**
 * Alerts page — Phase 5, Issue #37.
 *
 * Operator alert acknowledgment workflow:
 * - Tabs: "Active Alerts" (pending acknowledgment) and "Acknowledged History"
 * - Acknowledge modal with full frame, detection crop, camera details, match confidence
 * - Audio chime for CRITICAL and HIGH severity alerts (browser Audio API)
 * - PATCH /alerts/{id}/acknowledge with notes + disposition
 * - Role gating: roles.includes("admin") required to acknowledge
 * - Live feed powered by LiveAlertFeed (Issue #36) embedded on this page
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import {
  Bell,
  BellOff,
  Check,
  Filter,
  Loader2,
  Search,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { dsai_apiFetch, dsai_apiGet } from "@/lib/api/dsai_client";
import { dsai_isAdmin } from "@/lib/auth/dsai_rbac";
import { LiveAlertFeed } from "@/components/alerts/LiveAlertFeed";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DsaiAlertRecord {
  dsai_alertId: string;
  dsai_identifier: string;
  dsai_priority: string;
  dsai_cameraId: string;
  dsai_confidence: number;
  dsai_thumbnailUrl: string | null;
  dsai_frameUrl: string | null;
  dsai_timestamp: string;
  dsai_acknowledged: boolean;
  dsai_acknowledgedBy: string | null;
  dsai_acknowledgedAt: string | null;
  dsai_notes: string | null;
}

interface DsaiAlertApiRecord {
  alert_id?: string;
  id?: string;
  identifier?: string;
  priority?: string;
  camera_id?: string;
  confidence?: number;
  thumbnail_url?: string | null;
  frame_url?: string | null;
  created_at?: string;
  timestamp?: string;
  acknowledged?: boolean;
  acknowledged_by?: string | null;
  acknowledged_at?: string | null;
  notes?: string | null;
}

type DsaiDisposition = "true_positive" | "false_positive" | "escalated";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DSAI_PRIORITY_BADGE: Record<string, string> = {
  CRITICAL: "bg-red-600 text-white",
  HIGH: "bg-orange-500 text-white",
  MEDIUM: "bg-yellow-400 text-black",
  LOW: "bg-blue-500 text-white",
};

const DSAI_DISPOSITION_OPTIONS: { dsai_value: DsaiDisposition; dsai_label: string }[] = [
  { dsai_value: "true_positive", dsai_label: "True Positive" },
  { dsai_value: "false_positive", dsai_label: "False Alarm" },
  { dsai_value: "escalated", dsai_label: "Escalated" },
];

// ---------------------------------------------------------------------------
// Audio chime (browser Audio API — no external deps)
// ---------------------------------------------------------------------------

/**
 * dsai_playChime — plays a simple oscillator-based chime using the Web Audio API.
 * Only audible for CRITICAL and HIGH priority alerts.
 */
function dsai_playChime(dsai_priority: string): void {
  if (typeof window === "undefined" || typeof AudioContext === "undefined") return;
  if (dsai_priority !== "CRITICAL" && dsai_priority !== "HIGH") return;

  try {
    const dsai_ctx = new AudioContext();
    const dsai_osc = dsai_ctx.createOscillator();
    const dsai_gain = dsai_ctx.createGain();
    dsai_osc.connect(dsai_gain);
    dsai_gain.connect(dsai_ctx.destination);

    dsai_osc.type = "sine";
    dsai_osc.frequency.setValueAtTime(880, dsai_ctx.currentTime);
    dsai_osc.frequency.exponentialRampToValueAtTime(440, dsai_ctx.currentTime + 0.3);
    dsai_gain.gain.setValueAtTime(0.4, dsai_ctx.currentTime);
    dsai_gain.gain.exponentialRampToValueAtTime(0.001, dsai_ctx.currentTime + 0.5);

    dsai_osc.start(dsai_ctx.currentTime);
    dsai_osc.stop(dsai_ctx.currentTime + 0.5);
    dsai_osc.onended = () => dsai_ctx.close();
  } catch {
    /* Audio API not available in this environment */
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function dsai_toProxyUrl(dsai_rawUrl: string | null | undefined): string | null {
  if (!dsai_rawUrl) return null;
  try {
    const dsai_parsed = new URL(dsai_rawUrl);
    return `/api/media${dsai_parsed.pathname}`;
  } catch {
    return `/api/media/${dsai_rawUrl.replace(/^\//, "")}`;
  }
}

function dsai_mapAlert(dsai_raw: DsaiAlertApiRecord): DsaiAlertRecord {
  return {
    dsai_alertId: String(dsai_raw.alert_id ?? dsai_raw.id ?? Math.random()),
    dsai_identifier: dsai_raw.identifier ?? "",
    dsai_priority: (dsai_raw.priority ?? "LOW").toUpperCase(),
    dsai_cameraId: dsai_raw.camera_id ?? "",
    dsai_confidence: dsai_raw.confidence ?? 0,
    dsai_thumbnailUrl: dsai_raw.thumbnail_url ?? null,
    dsai_frameUrl: dsai_raw.frame_url ?? null,
    dsai_timestamp: dsai_raw.created_at ?? dsai_raw.timestamp ?? new Date().toISOString(),
    dsai_acknowledged: dsai_raw.acknowledged ?? false,
    dsai_acknowledgedBy: dsai_raw.acknowledged_by ?? null,
    dsai_acknowledgedAt: dsai_raw.acknowledged_at ?? null,
    dsai_notes: dsai_raw.notes ?? null,
  };
}

// ---------------------------------------------------------------------------
// Acknowledge Modal
// ---------------------------------------------------------------------------

function DsaiAcknowledgeModal({
  dsai_alert,
  dsai_onClose,
  dsai_onSubmit,
}: {
  dsai_alert: DsaiAlertRecord;
  dsai_onClose: () => void;
  dsai_onSubmit: (dsai_id: string, dsai_notes: string, dsai_disposition: DsaiDisposition) => Promise<void>;
}) {
  const [dsai_notes, dsai_setNotes] = useState("");
  const [dsai_disposition, dsai_setDisposition] = useState<DsaiDisposition>("true_positive");
  const [dsai_submitting, dsai_setSubmitting] = useState(false);
  const [dsai_error, dsai_setError] = useState<string | null>(null);

  const dsai_thumbUrl = dsai_toProxyUrl(dsai_alert.dsai_thumbnailUrl);
  const dsai_frameUrl = dsai_toProxyUrl(dsai_alert.dsai_frameUrl ?? dsai_alert.dsai_thumbnailUrl);
  const dsai_priorityClass = DSAI_PRIORITY_BADGE[dsai_alert.dsai_priority] ?? "bg-gray-500 text-white";
  const dsai_confidence = Math.round(dsai_alert.dsai_confidence * 100);

  const dsai_handleSubmit = useCallback(async () => {
    dsai_setSubmitting(true);
    dsai_setError(null);
    try {
      await dsai_onSubmit(dsai_alert.dsai_alertId, dsai_notes, dsai_disposition);
      dsai_onClose();
    } catch (dsai_err) {
      dsai_setError(dsai_err instanceof Error ? dsai_err.message : "Acknowledgment failed.");
    } finally {
      dsai_setSubmitting(false);
    }
  }, [dsai_notes, dsai_disposition, dsai_alert, dsai_onSubmit, dsai_onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
      onClick={dsai_onClose}
    >
      <div
        className="relative w-full max-w-2xl rounded-xl bg-card border shadow-2xl overflow-hidden"
        onClick={(dsai_e) => dsai_e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold">Acknowledge Alert</h2>
            <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${dsai_priorityClass}`}>
              {dsai_alert.dsai_priority}
            </span>
          </div>
          <button onClick={dsai_onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Full parent frame */}
        {dsai_frameUrl && (
          <div className="bg-black">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={dsai_frameUrl}
              alt="parent frame"
              className="w-full object-contain max-h-64"
            />
          </div>
        )}

        {/* Details + crop */}
        <div className="flex gap-4 px-5 py-4">
          {dsai_thumbUrl && (
            <div className="flex-shrink-0 rounded border overflow-hidden h-24 w-20">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={dsai_thumbUrl} alt="detection crop" className="h-full w-full object-cover" />
            </div>
          )}
          <div className="space-y-1 text-sm">
            <p><span className="text-muted-foreground">Target:</span> <span className="font-mono font-medium">{dsai_alert.dsai_identifier}</span></p>
            <p><span className="text-muted-foreground">Camera:</span> {dsai_alert.dsai_cameraId}</p>
            <p><span className="text-muted-foreground">Match confidence:</span> {dsai_confidence}%</p>
            <p><span className="text-muted-foreground">Detected at:</span> {new Date(dsai_alert.dsai_timestamp).toLocaleString()}</p>
          </div>
        </div>

        {/* Acknowledgment form */}
        <div className="px-5 pb-5 space-y-4 border-t pt-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Disposition</label>
            <select
              value={dsai_disposition}
              onChange={(dsai_e) => dsai_setDisposition(dsai_e.target.value as DsaiDisposition)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              {DSAI_DISPOSITION_OPTIONS.map((dsai_opt) => (
                <option key={dsai_opt.dsai_value} value={dsai_opt.dsai_value}>
                  {dsai_opt.dsai_label}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">Notes</label>
            <textarea
              value={dsai_notes}
              onChange={(dsai_e) => dsai_setNotes(dsai_e.target.value)}
              rows={3}
              placeholder="e.g. False alarm — maintenance vehicle"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring resize-none"
            />
          </div>

          {dsai_error && (
            <p className="text-sm text-destructive">{dsai_error}</p>
          )}

          <div className="flex justify-end gap-2">
            <button
              onClick={dsai_onClose}
              className="rounded-md border px-4 py-2 text-sm hover:bg-muted"
            >
              Cancel
            </button>
            <button
              onClick={dsai_handleSubmit}
              disabled={dsai_submitting}
              className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {dsai_submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Check className="h-4 w-4" />
              )}
              Acknowledge
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// History row
// ---------------------------------------------------------------------------

function DsaiHistoryRow({ dsai_alert }: { dsai_alert: DsaiAlertRecord }) {
  const dsai_priorityClass = DSAI_PRIORITY_BADGE[dsai_alert.dsai_priority] ?? "bg-gray-500 text-white";
  return (
    <tr className="border-b last:border-0 hover:bg-muted/30 text-sm">
      <td className="px-4 py-3 font-mono">{dsai_alert.dsai_identifier}</td>
      <td className="px-4 py-3">
        <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${dsai_priorityClass}`}>
          {dsai_alert.dsai_priority}
        </span>
      </td>
      <td className="px-4 py-3 text-muted-foreground">{dsai_alert.dsai_cameraId}</td>
      <td className="px-4 py-3 text-muted-foreground">
        {Math.round(dsai_alert.dsai_confidence * 100)}%
      </td>
      <td className="px-4 py-3 text-muted-foreground">
        {dsai_alert.dsai_acknowledgedBy ?? "—"}
      </td>
      <td className="px-4 py-3 text-muted-foreground">
        {dsai_alert.dsai_acknowledgedAt
          ? new Date(dsai_alert.dsai_acknowledgedAt).toLocaleString()
          : "—"}
      </td>
      <td className="px-4 py-3 text-muted-foreground max-w-xs truncate">
        {dsai_alert.dsai_notes ?? "—"}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type DsaiTab = "active" | "history";

export default function AlertsPage() {
  const { data: dsai_session } = useSession();
  const dsai_accessToken = (dsai_session as any)?.dsai_accessToken as string | undefined;
  const dsai_tenantId = (dsai_session as any)?.dsai_tenantId as string | undefined;
  const dsai_userIsAdmin = dsai_isAdmin(dsai_session);

  const [dsai_tab, dsai_setTab] = useState<DsaiTab>("active");
  const [dsai_history, dsai_setHistory] = useState<DsaiAlertRecord[]>([]);
  const [dsai_historyLoading, dsai_setHistoryLoading] = useState(false);
  const [dsai_historyError, dsai_setHistoryError] = useState<string | null>(null);

  // Filters for history
  const [dsai_filterCamera, dsai_setFilterCamera] = useState("");
  const [dsai_filterSeverity, dsai_setFilterSeverity] = useState("");

  // Audio toggle
  const [dsai_audioEnabled, dsai_setAudioEnabled] = useState(true);

  // Acknowledge modal
  const [dsai_ackAlert, dsai_setAckAlert] = useState<DsaiAlertRecord | null>(null);

  // Ref to play chime
  const dsai_audioRef = useRef(dsai_audioEnabled);
  dsai_audioRef.current = dsai_audioEnabled;

  // ------------------------------------------------------------------
  // Load history
  // ------------------------------------------------------------------
  const dsai_loadHistory = useCallback(async () => {
    if (!dsai_accessToken || !dsai_tenantId) return;
    dsai_setHistoryLoading(true);
    dsai_setHistoryError(null);
    try {
      const dsai_params = new URLSearchParams({ acknowledged: "true" });
      if (dsai_filterCamera.trim()) dsai_params.set("camera_id", dsai_filterCamera.trim());
      if (dsai_filterSeverity) dsai_params.set("priority", dsai_filterSeverity);

      const dsai_data = await dsai_apiGet<DsaiAlertApiRecord[] | { items?: DsaiAlertApiRecord[] }>(
        `watchlist/alerts?${dsai_params.toString()}`,
        dsai_accessToken,
        dsai_tenantId
      );
      const dsai_rawItems: DsaiAlertApiRecord[] = Array.isArray(dsai_data)
        ? dsai_data
        : (dsai_data as any)?.items ?? [];
      dsai_setHistory(dsai_rawItems.map(dsai_mapAlert));
    } catch (dsai_err) {
      dsai_setHistoryError(dsai_err instanceof Error ? dsai_err.message : "Failed to load history.");
    } finally {
      dsai_setHistoryLoading(false);
    }
  }, [dsai_accessToken, dsai_tenantId, dsai_filterCamera, dsai_filterSeverity]);

  useEffect(() => {
    if (dsai_tab === "history") dsai_loadHistory();
  }, [dsai_tab, dsai_loadHistory]);

  // ------------------------------------------------------------------
  // Acknowledge
  // ------------------------------------------------------------------
  const dsai_handleAcknowledge = useCallback(
    async (dsai_alertId: string, dsai_notes: string, dsai_disposition: DsaiDisposition) => {
      if (!dsai_accessToken || !dsai_tenantId) return;
      await dsai_apiFetch(
        `watchlist/alerts/${encodeURIComponent(dsai_alertId)}/acknowledge`,
        dsai_accessToken,
        dsai_tenantId,
        {
          method: "PATCH",
          body: JSON.stringify({ notes: dsai_notes, disposition: dsai_disposition }),
        }
      );
    },
    [dsai_accessToken, dsai_tenantId]
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Alerts</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Live surveillance alert feed and acknowledgment history.
          </p>
        </div>
        <button
          onClick={() => dsai_setAudioEnabled((dsai_prev) => !dsai_prev)}
          className="flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm hover:bg-muted"
          title={dsai_audioEnabled ? "Mute alert chimes" : "Unmute alert chimes"}
        >
          {dsai_audioEnabled ? (
            <Volume2 className="h-4 w-4 text-primary" />
          ) : (
            <VolumeX className="h-4 w-4 text-muted-foreground" />
          )}
          {dsai_audioEnabled ? "Audio On" : "Audio Off"}
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b">
        {(["active", "history"] as DsaiTab[]).map((dsai_t) => (
          <button
            key={dsai_t}
            onClick={() => dsai_setTab(dsai_t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              dsai_tab === dsai_t
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {dsai_t === "active" ? (
              <span className="flex items-center gap-1.5">
                <Bell className="h-3.5 w-3.5" /> Active Alerts
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                <BellOff className="h-3.5 w-3.5" /> Acknowledged History
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab: Active Alerts */}
      {dsai_tab === "active" && (
        <div>
          {!dsai_userIsAdmin && (
            <div className="rounded-md bg-muted px-4 py-3 text-sm text-muted-foreground mb-4">
              Admin role required to acknowledge alerts.
            </div>
          )}
          <LiveAlertFeed />
        </div>
      )}

      {/* Tab: Acknowledged History */}
      {dsai_tab === "history" && (
        <div className="space-y-4">
          {/* Filters */}
          <div className="flex flex-wrap gap-3">
            <div className="flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <input
                type="text"
                value={dsai_filterCamera}
                onChange={(dsai_e) => dsai_setFilterCamera(dsai_e.target.value)}
                placeholder="Filter by camera ID"
                className="bg-transparent outline-none w-36 text-sm"
              />
            </div>
            <select
              value={dsai_filterSeverity}
              onChange={(dsai_e) => dsai_setFilterSeverity(dsai_e.target.value)}
              className="rounded-md border px-3 py-2 text-sm bg-background"
            >
              <option value="">All severities</option>
              {["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((dsai_p) => (
                <option key={dsai_p} value={dsai_p}>{dsai_p}</option>
              ))}
            </select>
            <button
              onClick={dsai_loadHistory}
              className="flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm hover:bg-muted"
            >
              <Search className="h-4 w-4" /> Search
            </button>
          </div>

          {/* Error */}
          {dsai_historyError && (
            <div className="rounded-md border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {dsai_historyError}
            </div>
          )}

          {/* History table */}
          <div className="rounded-lg border overflow-hidden">
            {dsai_historyLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : dsai_history.length === 0 ? (
              <div className="flex items-center justify-center py-12 text-muted-foreground text-sm">
                No acknowledged alerts found.
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-muted text-muted-foreground text-xs uppercase">
                  <tr>
                    <th className="px-4 py-3 text-left">Target</th>
                    <th className="px-4 py-3 text-left">Priority</th>
                    <th className="px-4 py-3 text-left">Camera</th>
                    <th className="px-4 py-3 text-left">Confidence</th>
                    <th className="px-4 py-3 text-left">Acknowledged By</th>
                    <th className="px-4 py-3 text-left">Acknowledged At</th>
                    <th className="px-4 py-3 text-left">Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {dsai_history.map((dsai_a) => (
                    <DsaiHistoryRow key={dsai_a.dsai_alertId} dsai_alert={dsai_a} />
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* Acknowledge modal */}
      {dsai_ackAlert && (
        <DsaiAcknowledgeModal
          dsai_alert={dsai_ackAlert}
          dsai_onClose={() => dsai_setAckAlert(null)}
          dsai_onSubmit={dsai_handleAcknowledge}
        />
      )}
    </div>
  );
}
