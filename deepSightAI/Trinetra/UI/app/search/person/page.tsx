"use client";

/**
 * Person Re-Identification (Re-ID) Search page.
 *
 * Allows operators to upload a person reference crop, define spatial and
 * temporal constraints, and discover cross-camera sightings ranked by
 * similarity. Results are displayed both in a card grid and a chronological
 * journey timeline across camera locations.
 *
 * Calls POST /search/person on SearchService:8081.
 *
 * Issue: #31 — Person Re-ID & Reference-Crop Search UI
 */

import React, { useCallback, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { ChevronDown, ChevronRight, Loader2, MapPin, Search, Upload, X } from "lucide-react";
import { CameraSelector } from "@/components/camera/CameraSelector";
import { dsai_apiPost } from "@/lib/api/dsai_client";
import { cn } from "@/lib/dsai_utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DsaiPersonSighting {
  dsai_frameId: string;
  dsai_cameraId: string;
  dsai_timestamp: string;
  dsai_score: number;
  dsai_thumbnailUrl: string;
}

interface DsaiPersonSearchPayload {
  crop_image_base64: string;
  top_k: number;
  threshold: number;
  camera_ids?: string[];
  start_time?: string;
  end_time?: string;
}

interface DsaiPersonApiResponse {
  results: Array<{
    frame_id: string;
    camera_id: string;
    timestamp: string;
    score: number;
    thumbnail_url: string;
  }>;
}

const DSAI_TIME_PRESETS = [
  { dsai_label: "Last 1 hour", dsai_hours: 1 },
  { dsai_label: "Last 6 hours", dsai_hours: 6 },
  { dsai_label: "Last 24 hours", dsai_hours: 24 },
  { dsai_label: "Custom range", dsai_hours: -1 },
];

const DSAI_TOP_K_OPTIONS = [10, 25, 50, 100] as const;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function dsai_toProxyUrl(dsai_rawUrl: string): string {
  try {
    const dsai_parsed = new URL(dsai_rawUrl);
    return `/api/media${dsai_parsed.pathname}`;
  } catch {
    return `/api/media/${dsai_rawUrl.replace(/^\//, "")}`;
  }
}

function dsai_fileToBase64(dsai_file: File): Promise<string> {
  return new Promise((dsai_resolve, dsai_reject) => {
    const dsai_reader = new FileReader();
    dsai_reader.onload = () => dsai_resolve(dsai_reader.result as string);
    dsai_reader.onerror = dsai_reject;
    dsai_reader.readAsDataURL(dsai_file);
  });
}

function dsai_getTimeRange(dsai_hours: number): { dsai_start: string; dsai_end: string } {
  const dsai_now = new Date();
  const dsai_start = new Date(dsai_now.getTime() - dsai_hours * 60 * 60 * 1000);
  return {
    dsai_start: dsai_start.toISOString().slice(0, 16),
    dsai_end: dsai_now.toISOString().slice(0, 16),
  };
}

// ---------------------------------------------------------------------------
// Journey Timeline
// ---------------------------------------------------------------------------

function DsaiJourneyTimeline({ dsai_sightings }: { dsai_sightings: DsaiPersonSighting[] }) {
  // Sort chronologically
  const dsai_sorted = [...dsai_sightings].sort(
    (dsai_a, dsai_b) =>
      new Date(dsai_a.dsai_timestamp).getTime() - new Date(dsai_b.dsai_timestamp).getTime()
  );

  return (
    <div className="space-y-2">
      {dsai_sorted.map((dsai_s, dsai_idx) => (
        <div key={dsai_s.dsai_frameId} className="flex items-start gap-3">
          {/* Timeline connector */}
          <div className="flex flex-col items-center">
            <div className="h-4 w-4 rounded-full bg-primary flex-shrink-0 flex items-center justify-center">
              <span className="text-[10px] text-primary-foreground font-bold">{dsai_idx + 1}</span>
            </div>
            {dsai_idx < dsai_sorted.length - 1 && (
              <div className="w-0.5 flex-1 bg-border mt-1 min-h-[2rem]" />
            )}
          </div>
          {/* Sighting card */}
          <div className="flex-1 pb-3">
            <div className="rounded-lg border bg-card p-3 flex gap-3">
              <div className="flex-shrink-0">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={dsai_toProxyUrl(dsai_s.dsai_thumbnailUrl)}
                  alt={`Sighting ${dsai_idx + 1}`}
                  className="h-16 w-16 rounded object-cover"
                />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 text-sm font-medium">
                  <MapPin className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                  <span className="truncate">{dsai_s.dsai_cameraId}</span>
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  {new Date(dsai_s.dsai_timestamp).toLocaleString()}
                </div>
                <div className="mt-1">
                  <span className={cn(
                    "text-xs font-bold px-2 py-0.5 rounded-full",
                    dsai_s.dsai_score >= 0.8 ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                      : dsai_s.dsai_score >= 0.5 ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200"
                      : "bg-muted text-muted-foreground"
                  )}>
                    {Math.round(dsai_s.dsai_score * 100)}% match
                  </span>
                </div>
              </div>
              {dsai_idx < dsai_sorted.length - 1 && (
                <ChevronRight className="h-4 w-4 text-muted-foreground self-center flex-shrink-0" />
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function PersonSearchPage() {
  const { data: dsai_session } = useSession();
  const dsai_accessToken = (dsai_session as any)?.dsai_accessToken as string | undefined;
  const dsai_tenantId = (dsai_session as any)?.dsai_tenantId as string | undefined;

  const [dsai_cropFile, dsai_setCropFile] = useState<File | null>(null);
  const [dsai_cropPreview, dsai_setCropPreview] = useState<string | null>(null);
  const dsai_fileInputRef = useRef<HTMLInputElement>(null);

  const [dsai_timePreset, dsai_setTimePreset] = useState(0); // index into DSAI_TIME_PRESETS
  const [dsai_startTime, dsai_setStartTime] = useState("");
  const [dsai_endTime, dsai_setEndTime] = useState("");
  const [dsai_cameraIds, dsai_setCameraIds] = useState<string[]>([]);
  const [dsai_topK, dsai_setTopK] = useState<number>(10);
  const [dsai_threshold, dsai_setThreshold] = useState(0.3);

  const [dsai_results, dsai_setResults] = useState<DsaiPersonSighting[]>([]);
  const [dsai_isSearching, dsai_setIsSearching] = useState(false);
  const [dsai_error, dsai_setError] = useState<string | null>(null);
  const [dsai_searched, dsai_setSearched] = useState(false);
  const [dsai_viewMode, dsai_setViewMode] = useState<"grid" | "timeline">("grid");

  const dsai_handleCropSelect = useCallback(async (dsai_file: File) => {
    dsai_setCropFile(dsai_file);
    try {
      const dsai_dataUrl = await dsai_fileToBase64(dsai_file);
      dsai_setCropPreview(dsai_dataUrl);
    } catch {
      dsai_setError("Failed to read image file.");
    }
  }, []);

  const dsai_clearCrop = useCallback(() => {
    dsai_setCropFile(null);
    dsai_setCropPreview(null);
    if (dsai_fileInputRef.current) dsai_fileInputRef.current.value = "";
  }, []);

  const dsai_handlePresetChange = useCallback((dsai_idx: number) => {
    dsai_setTimePreset(dsai_idx);
    const dsai_preset = DSAI_TIME_PRESETS[dsai_idx];
    if (dsai_preset.dsai_hours > 0) {
      const dsai_range = dsai_getTimeRange(dsai_preset.dsai_hours);
      dsai_setStartTime(dsai_range.dsai_start);
      dsai_setEndTime(dsai_range.dsai_end);
    }
  }, []);

  const dsai_handleSearch = useCallback(async () => {
    if (!dsai_cropPreview) {
      dsai_setError("Please upload a reference person crop image.");
      return;
    }
    if (!dsai_accessToken || !dsai_tenantId) {
      dsai_setError("Session expired. Please log in again.");
      return;
    }

    dsai_setIsSearching(true);
    dsai_setError(null);
    dsai_setSearched(false);

    try {
      const dsai_payload: DsaiPersonSearchPayload = {
        crop_image_base64: dsai_cropPreview,
        top_k: dsai_topK,
        threshold: dsai_threshold,
      };
      if (dsai_cameraIds.length > 0) dsai_payload.camera_ids = dsai_cameraIds;
      if (dsai_startTime) dsai_payload.start_time = dsai_startTime;
      if (dsai_endTime) dsai_payload.end_time = dsai_endTime;

      const dsai_data = await dsai_apiPost<DsaiPersonApiResponse>(
        "search/search/person",
        dsai_accessToken,
        dsai_tenantId,
        dsai_payload
      );

      dsai_setResults(
        (dsai_data?.results ?? []).map((dsai_r) => ({
          dsai_frameId: dsai_r.frame_id,
          dsai_cameraId: dsai_r.camera_id,
          dsai_timestamp: dsai_r.timestamp,
          dsai_score: dsai_r.score,
          dsai_thumbnailUrl: dsai_r.thumbnail_url,
        }))
      );
    } catch (dsai_err) {
      dsai_setError(
        dsai_err instanceof Error ? dsai_err.message : "Search failed. Please try again."
      );
    } finally {
      dsai_setIsSearching(false);
      dsai_setSearched(true);
    }
  }, [
    dsai_cropPreview, dsai_topK, dsai_threshold, dsai_cameraIds,
    dsai_startTime, dsai_endTime, dsai_accessToken, dsai_tenantId,
  ]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Person Re-ID Search</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Upload a person reference crop to track sightings across cameras.
        </p>
      </div>

      <div className="rounded-lg border bg-card p-5 space-y-4">
        {/* Crop uploader */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Reference Crop <span className="text-destructive">*</span></label>
          {dsai_cropPreview ? (
            <div className="relative inline-block">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={dsai_cropPreview} alt="Reference person crop"
                className="h-40 w-auto rounded border object-contain" />
              <button onClick={dsai_clearCrop}
                className="absolute -top-2 -right-2 rounded-full bg-destructive text-destructive-foreground p-0.5 shadow">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <div
              className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-input p-8 text-sm text-muted-foreground hover:border-primary/50 transition-colors"
              onClick={() => dsai_fileInputRef.current?.click()}
              onDrop={(dsai_e) => {
                dsai_e.preventDefault();
                const dsai_f = dsai_e.dataTransfer.files[0];
                if (dsai_f) dsai_handleCropSelect(dsai_f);
              }}
              onDragOver={(dsai_e) => dsai_e.preventDefault()}
            >
              <Upload className="h-8 w-8" />
              <span>Drop person crop or click to upload</span>
              <span className="text-xs">Supports JPEG, PNG, WebP</span>
            </div>
          )}
          <input ref={dsai_fileInputRef} type="file" accept="image/*" className="hidden"
            onChange={(dsai_e) => { const dsai_f = dsai_e.target.files?.[0]; if (dsai_f) dsai_handleCropSelect(dsai_f); }} />
        </div>

        {/* Time preset */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Time Window</label>
          <div className="flex flex-wrap gap-2">
            {DSAI_TIME_PRESETS.map((dsai_p, dsai_idx) => (
              <button key={dsai_idx} type="button"
                onClick={() => dsai_handlePresetChange(dsai_idx)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-xs font-medium border transition-colors",
                  dsai_timePreset === dsai_idx
                    ? "bg-primary text-primary-foreground border-primary"
                    : "border-input text-muted-foreground hover:bg-accent"
                )}>
                {dsai_p.dsai_label}
              </button>
            ))}
          </div>
          {DSAI_TIME_PRESETS[dsai_timePreset].dsai_hours === -1 && (
            <div className="grid grid-cols-2 gap-4 mt-2">
              <input type="datetime-local" value={dsai_startTime}
                onChange={(dsai_e) => dsai_setStartTime(dsai_e.target.value)}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
              <input type="datetime-local" value={dsai_endTime}
                onChange={(dsai_e) => dsai_setEndTime(dsai_e.target.value)}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
            </div>
          )}
        </div>

        {/* Cameras + controls */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Cameras</label>
            <CameraSelector dsai_value={dsai_cameraIds} dsai_onChange={dsai_setCameraIds} dsai_placeholder="All cameras" />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Results</label>
            <select value={dsai_topK} onChange={(dsai_e) => dsai_setTopK(Number(dsai_e.target.value))}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring">
              {DSAI_TOP_K_OPTIONS.map((dsai_n) => (
                <option key={dsai_n} value={dsai_n}>Top {dsai_n}</option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Min Similarity: {dsai_threshold.toFixed(2)}</label>
            <input type="range" min={0} max={1} step={0.05} value={dsai_threshold}
              onChange={(dsai_e) => dsai_setThreshold(Number(dsai_e.target.value))}
              className="w-full" />
          </div>
        </div>

        <button onClick={dsai_handleSearch} disabled={dsai_isSearching || !dsai_cropPreview}
          className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed">
          {dsai_isSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          Search Sightings
        </button>
      </div>

      {/* Error */}
      {dsai_error && (
        <div className="rounded-md border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {dsai_error}
        </div>
      )}

      {/* Results */}
      {dsai_searched && !dsai_isSearching && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              {dsai_results.length === 0
                ? "No sightings found."
                : `${dsai_results.length} sighting${dsai_results.length !== 1 ? "s" : ""} across ${[...new Set(dsai_results.map((dsai_r) => dsai_r.dsai_cameraId))].length} camera(s)`}
            </p>
            {dsai_results.length > 0 && (
              <div className="flex gap-2">
                <button onClick={() => dsai_setViewMode("grid")}
                  className={cn("text-xs px-3 py-1 rounded border",
                    dsai_viewMode === "grid" ? "bg-primary text-primary-foreground border-primary" : "border-input text-muted-foreground")}>
                  Grid
                </button>
                <button onClick={() => dsai_setViewMode("timeline")}
                  className={cn("text-xs px-3 py-1 rounded border",
                    dsai_viewMode === "timeline" ? "bg-primary text-primary-foreground border-primary" : "border-input text-muted-foreground")}>
                  Journey
                </button>
              </div>
            )}
          </div>

          {dsai_viewMode === "timeline" ? (
            <DsaiJourneyTimeline dsai_sightings={dsai_results} />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {dsai_results.map((dsai_r) => {
                const dsai_proxy = dsai_toProxyUrl(dsai_r.dsai_thumbnailUrl);
                return (
                  <div key={dsai_r.dsai_frameId} className="rounded-lg border bg-card overflow-hidden shadow-sm">
                    <div className="aspect-[3/4] bg-muted relative">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={dsai_proxy} alt={`Sighting ${dsai_r.dsai_frameId}`}
                        className="w-full h-full object-cover" loading="lazy" />
                      <span className={cn(
                        "absolute top-2 right-2 text-xs font-bold px-2 py-0.5 rounded-full",
                        dsai_r.dsai_score >= 0.8 ? "bg-green-600 text-white"
                          : dsai_r.dsai_score >= 0.5 ? "bg-yellow-500 text-black"
                          : "bg-gray-600 text-white"
                      )}>
                        {Math.round(dsai_r.dsai_score * 100)}%
                      </span>
                    </div>
                    <div className="p-3 space-y-1">
                      <div className="text-xs font-mono text-muted-foreground truncate flex items-center gap-1">
                        <MapPin className="h-3 w-3" />{dsai_r.dsai_cameraId}
                      </div>
                      <div className="text-xs text-muted-foreground">{new Date(dsai_r.dsai_timestamp).toLocaleString()}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
