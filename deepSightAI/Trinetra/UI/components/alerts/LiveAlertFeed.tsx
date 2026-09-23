"use client";

/**
 * LiveAlertFeed — Issue #36.
 *
 * Live real-time alert feed using the custom vanilla SSE client (sseClient.ts).
 * Falls back to polling GET /alerts/poll?last_seen_id=... every 5s if SSE fails.
 *
 * Zero external streaming packages. @microsoft/fetch-event-source is FORBIDDEN.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { Bell, BellOff, Loader2, Wifi, WifiOff } from "lucide-react";
import { dsai_connectSse, dsai_parseSseChunk } from "@/lib/streaming/sseClient";
import { dsai_isAdmin } from "@/lib/auth/dsai_rbac";
import { dsai_buildHeaders } from "@/lib/api/dsai_client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DsaiAlertItem {
  dsai_alertId: string;
  dsai_entryId: number;
  dsai_identifier: string;
  dsai_priority: string;
  dsai_cameraId: string;
  dsai_confidence: number;
  dsai_thumbnailUrl: string | null;
  dsai_timestamp: string;
  dsai_acknowledged: boolean;
}

interface DsaiAlertApiItem {
  alert_id?: string;
  id?: string;
  watchlist_entry_id?: number;
  identifier?: string;
  priority?: string;
  camera_id?: string;
  confidence?: number;
  thumbnail_url?: string | null;
  created_at?: string;
  timestamp?: string;
  acknowledged?: boolean;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DSAI_MAX_FEED_SIZE = 50;
const DSAI_POLL_INTERVAL_MS = 5_000;

const DSAI_PRIORITY_BADGE: Record<string, string> = {
  CRITICAL: "bg-red-600 text-white",
  HIGH: "bg-orange-500 text-white",
  MEDIUM: "bg-yellow-400 text-black",
  LOW: "bg-blue-500 text-white",
};

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

function dsai_mapAlert(dsai_raw: DsaiAlertApiItem): DsaiAlertItem {
  return {
    dsai_alertId: String(dsai_raw.alert_id ?? dsai_raw.id ?? Math.random()),
    dsai_entryId: dsai_raw.watchlist_entry_id ?? 0,
    dsai_identifier: dsai_raw.identifier ?? "",
    dsai_priority: (dsai_raw.priority ?? "LOW").toUpperCase(),
    dsai_cameraId: dsai_raw.camera_id ?? "",
    dsai_confidence: dsai_raw.confidence ?? 0,
    dsai_thumbnailUrl: dsai_raw.thumbnail_url ?? null,
    dsai_timestamp: dsai_raw.created_at ?? dsai_raw.timestamp ?? new Date().toISOString(),
    dsai_acknowledged: dsai_raw.acknowledged ?? false,
  };
}

// ---------------------------------------------------------------------------
// Alert card
// ---------------------------------------------------------------------------

function DsaiAlertCard({ dsai_alert }: { dsai_alert: DsaiAlertItem }) {
  const dsai_thumbUrl = dsai_toProxyUrl(dsai_alert.dsai_thumbnailUrl);
  const dsai_priorityClass =
    DSAI_PRIORITY_BADGE[dsai_alert.dsai_priority] ?? "bg-gray-500 text-white";
  const dsai_confidence = Math.round(dsai_alert.dsai_confidence * 100);

  return (
    <div className="flex gap-3 rounded-lg border bg-card p-3 shadow-sm hover:shadow-md transition-shadow">
      {/* Thumbnail */}
      <div className="flex-shrink-0 h-16 w-20 rounded border overflow-hidden bg-muted">
        {dsai_thumbUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={dsai_thumbUrl}
            alt="alert crop"
            className="h-full w-full object-cover"
            onError={(dsai_e) => {
              (dsai_e.target as HTMLImageElement).style.display = "none";
            }}
          />
        ) : (
          <div className="h-full w-full flex items-center justify-center text-xs text-muted-foreground">
            No img
          </div>
        )}
      </div>

      {/* Details */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <span className="font-mono text-sm font-medium truncate">{dsai_alert.dsai_identifier}</span>
          <span
            className={`flex-shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold ${dsai_priorityClass}`}
          >
            {dsai_alert.dsai_priority}
          </span>
        </div>
        <div className="text-xs text-muted-foreground mt-0.5">
          {dsai_alert.dsai_cameraId} &bull; Match: {dsai_confidence}%
        </div>
        <div className="text-xs text-muted-foreground mt-0.5">
          {new Date(dsai_alert.dsai_timestamp).toLocaleTimeString()}
        </div>
        {dsai_alert.dsai_acknowledged && (
          <span className="mt-1 inline-block text-xs text-muted-foreground italic">acknowledged</span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LiveAlertFeed component
// ---------------------------------------------------------------------------

interface DsaiLiveAlertFeedProps {
  /** Maximum number of alerts to display (default 20). */
  dsai_maxAlerts?: number;
}

export function LiveAlertFeed({ dsai_maxAlerts = 20 }: DsaiLiveAlertFeedProps) {
  const { data: dsai_session } = useSession();
  const dsai_accessToken = (dsai_session as any)?.dsai_accessToken as string | undefined;
  const dsai_tenantId = (dsai_session as any)?.dsai_tenantId as string | undefined;
  const dsai_userIsAdmin = dsai_isAdmin(dsai_session);

  const [dsai_alerts, dsai_setAlerts] = useState<DsaiAlertItem[]>([]);
  const [dsai_connected, dsai_setConnected] = useState(false);
  const [dsai_usingPollFallback, dsai_setUsingPollFallback] = useState(false);
  const [dsai_newCount, dsai_setNewCount] = useState(0);
  const [dsai_sseError, dsai_setSseError] = useState<string | null>(null);

  const dsai_sseRef = useRef<ReturnType<typeof dsai_connectSse> | null>(null);
  const dsai_pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const dsai_lastSeenIdRef = useRef<string | null>(null);

  // ------------------------------------------------------------------
  // Prepend new alerts to feed
  // ------------------------------------------------------------------
  const dsai_addAlerts = useCallback((dsai_newAlerts: DsaiAlertItem[]) => {
    if (dsai_newAlerts.length === 0) return;
    dsai_setNewCount((dsai_prev) => dsai_prev + dsai_newAlerts.length);
    dsai_setAlerts((dsai_prev) => {
      const dsai_combined = [...dsai_newAlerts, ...dsai_prev];
      return dsai_combined.slice(0, DSAI_MAX_FEED_SIZE);
    });
    if (dsai_newAlerts.length > 0) {
      dsai_lastSeenIdRef.current = dsai_newAlerts[0].dsai_alertId;
    }
  }, []);

  // ------------------------------------------------------------------
  // Start polling fallback
  // ------------------------------------------------------------------
  const dsai_startPolling = useCallback(() => {
    if (!dsai_accessToken || !dsai_tenantId) return;
    dsai_setUsingPollFallback(true);
    dsai_setConnected(false);

    const dsai_poll = async () => {
      try {
        const dsai_url =
          `/api/backend/watchlist/alerts/poll` +
          (dsai_lastSeenIdRef.current ? `?last_seen_id=${encodeURIComponent(dsai_lastSeenIdRef.current)}` : "");
        const dsai_response = await fetch(dsai_url, {
          headers: {
            Authorization: `Bearer ${dsai_accessToken}`,
            "X-Tenant-ID": dsai_tenantId,
          },
        });
        if (!dsai_response.ok) return;
        const dsai_data = await dsai_response.json();
        const dsai_rawItems: DsaiAlertApiItem[] = Array.isArray(dsai_data)
          ? dsai_data
          : dsai_data?.alerts ?? dsai_data?.items ?? [];
        dsai_addAlerts(dsai_rawItems.map(dsai_mapAlert));
      } catch {
        /* silent — will retry */
      }
    };

    dsai_poll();
    dsai_pollTimerRef.current = setInterval(dsai_poll, DSAI_POLL_INTERVAL_MS);
  }, [dsai_accessToken, dsai_tenantId, dsai_addAlerts]);

  // ------------------------------------------------------------------
  // Start SSE
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!dsai_accessToken || !dsai_tenantId || !dsai_userIsAdmin) return;

    const dsai_headers = Object.fromEntries(
      dsai_buildHeaders(dsai_accessToken, dsai_tenantId).entries()
    );

    let dsai_sseFailed = false;

    dsai_sseRef.current = dsai_connectSse(
      "/api/backend/watchlist/alerts/stream",
      dsai_headers,
      (dsai_event) => {
        dsai_setConnected(true);
        dsai_setUsingPollFallback(false);
        dsai_setSseError(null);

        // Clear polling if SSE is working
        if (dsai_pollTimerRef.current) {
          clearInterval(dsai_pollTimerRef.current);
          dsai_pollTimerRef.current = null;
        }

        try {
          const dsai_rawItem = JSON.parse(dsai_event.dsai_data) as DsaiAlertApiItem;
          dsai_addAlerts([dsai_mapAlert(dsai_rawItem)]);
        } catch {
          // Try parsing as a batch
          try {
            const dsai_rawItems = JSON.parse(dsai_event.dsai_data) as DsaiAlertApiItem[];
            if (Array.isArray(dsai_rawItems)) dsai_addAlerts(dsai_rawItems.map(dsai_mapAlert));
          } catch {
            /* parse error — ignore malformed event */
          }
        }
      },
      (dsai_err) => {
        dsai_setConnected(false);
        dsai_setSseError(dsai_err instanceof Error ? dsai_err.message : "Stream error");
        if (!dsai_sseFailed) {
          dsai_sseFailed = true;
          dsai_startPolling();
        }
      }
    );

    // Give SSE 3 seconds to connect before enabling polling fallback
    const dsai_fallbackTimer = setTimeout(() => {
      if (!dsai_sseRef.current?.dsai_isConnected()) {
        dsai_startPolling();
      }
    }, 3_000);

    return () => {
      clearTimeout(dsai_fallbackTimer);
      dsai_sseRef.current?.dsai_disconnect();
      if (dsai_pollTimerRef.current) clearInterval(dsai_pollTimerRef.current);
    };
  }, [dsai_accessToken, dsai_tenantId, dsai_userIsAdmin, dsai_addAlerts, dsai_startPolling]);

  const dsai_handleClearCount = () => dsai_setNewCount(0);

  // Non-admin: show access-denied message
  if (!dsai_userIsAdmin) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground text-sm gap-2">
        <BellOff className="h-8 w-8" />
        <p>Admin role required to view the alert feed.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Status bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm">
          {dsai_connected ? (
            <>
              <Wifi className="h-4 w-4 text-green-500" />
              <span className="text-green-600 font-medium">Live</span>
            </>
          ) : dsai_usingPollFallback ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin text-yellow-500" />
              <span className="text-yellow-600 font-medium">Polling fallback</span>
            </>
          ) : (
            <>
              <WifiOff className="h-4 w-4 text-muted-foreground" />
              <span className="text-muted-foreground">Connecting…</span>
            </>
          )}
          {dsai_sseError && (
            <span className="text-xs text-muted-foreground ml-2">({dsai_sseError})</span>
          )}
        </div>
        {dsai_newCount > 0 && (
          <button
            onClick={dsai_handleClearCount}
            className="flex items-center gap-1.5 text-xs text-primary hover:underline"
          >
            <Bell className="h-3.5 w-3.5" />
            {dsai_newCount} new {dsai_newCount === 1 ? "alert" : "alerts"} — clear badge
          </button>
        )}
      </div>

      {/* Feed */}
      {dsai_alerts.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-muted-foreground text-sm gap-2">
          <Bell className="h-8 w-8" />
          <p>Awaiting live alerts…</p>
        </div>
      ) : (
        <div className="space-y-2 overflow-y-auto max-h-[70vh] pr-1">
          {dsai_alerts.slice(0, dsai_maxAlerts).map((dsai_a) => (
            <DsaiAlertCard key={dsai_a.dsai_alertId} dsai_alert={dsai_a} />
          ))}
        </div>
      )}
    </div>
  );
}

export default LiveAlertFeed;
