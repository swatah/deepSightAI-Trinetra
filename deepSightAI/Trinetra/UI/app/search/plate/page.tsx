"use client";

/**
 * License Plate Search page — exact string and fuzzy trigram matching.
 *
 * Search modes:
 *   - Exact: strict alphanumeric equality
 *   - Fuzzy: trigram similarity with adjustable threshold slider (0.5–1.0)
 *
 * Calls POST /search/plate on SearchService:8081.
 * Result cards show plate crop previews, OCR text, confidence, and
 * full parent scene frame modal.
 *
 * Issue: #32 — License Plate Search UI with Exact & Fuzzy Trigram Matching
 */

import React, { useCallback, useState } from "react";
import { useSession } from "next-auth/react";
import { Loader2, Search, X, ZoomIn } from "lucide-react";
import { CameraSelector } from "@/components/camera/CameraSelector";
import { dsai_apiPost } from "@/lib/api/dsai_client";
import { cn } from "@/lib/dsai_utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type DsaiSearchMode = "exact" | "fuzzy";

interface DsaiPlateResult {
  dsai_frameId: string;
  dsai_cameraId: string;
  dsai_timestamp: string;
  dsai_score: number;
  dsai_plateText: string;
  dsai_thumbnailUrl: string;
  dsai_sceneThumbnailUrl?: string;
}

interface DsaiPlateSearchPayload {
  plate_number: string;
  mode: DsaiSearchMode;
  threshold?: number;
  top_k: number;
  camera_ids?: string[];
  start_time?: string;
  end_time?: string;
}

interface DsaiPlateApiResponse {
  results: Array<{
    frame_id: string;
    camera_id: string;
    timestamp: string;
    score: number;
    plate_text: string;
    thumbnail_url: string;
    scene_thumbnail_url?: string;
  }>;
}

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

/**
 * dsai_highlightMatch — wraps matching characters in a <mark> tag
 * for OCR text display.
 */
function DsaiOcrHighlight({
  dsai_ocrText,
  dsai_query,
}: {
  dsai_ocrText: string;
  dsai_query: string;
}) {
  const dsai_queryUpper = dsai_query.toUpperCase();
  const dsai_ocrUpper = dsai_ocrText.toUpperCase();
  const dsai_idx = dsai_ocrUpper.indexOf(dsai_queryUpper);
  if (dsai_idx === -1 || !dsai_queryUpper) {
    return <span className="font-mono font-bold tracking-widest">{dsai_ocrText}</span>;
  }
  return (
    <span className="font-mono font-bold tracking-widest">
      {dsai_ocrText.slice(0, dsai_idx)}
      <mark className="bg-yellow-200 dark:bg-yellow-700 rounded px-0.5">
        {dsai_ocrText.slice(dsai_idx, dsai_idx + dsai_queryUpper.length)}
      </mark>
      {dsai_ocrText.slice(dsai_idx + dsai_queryUpper.length)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Scene Preview Modal
// ---------------------------------------------------------------------------

function DsaiSceneModal({
  dsai_result,
  dsai_onClose,
}: {
  dsai_result: DsaiPlateResult | null;
  dsai_onClose: () => void;
}) {
  if (!dsai_result) return null;
  const dsai_sceneUrl = dsai_result.dsai_sceneThumbnailUrl
    ? dsai_toProxyUrl(dsai_result.dsai_sceneThumbnailUrl)
    : dsai_toProxyUrl(dsai_result.dsai_thumbnailUrl);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
      onClick={dsai_onClose}>
      <div className="relative max-w-3xl w-full mx-4 rounded-xl overflow-hidden bg-card shadow-2xl"
        onClick={(dsai_e) => dsai_e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <span className="text-sm font-medium">Scene Preview — {dsai_result.dsai_plateText}</span>
          <button onClick={dsai_onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={dsai_sceneUrl} alt="Full scene frame"
          className="w-full object-contain max-h-[65vh]" />
        <div className="px-4 py-3 border-t text-sm text-muted-foreground">
          {dsai_result.dsai_cameraId} &bull; {new Date(dsai_result.dsai_timestamp).toLocaleString()}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function PlateSearchPage() {
  const { data: dsai_session } = useSession();
  const dsai_accessToken = (dsai_session as any)?.dsai_accessToken as string | undefined;
  const dsai_tenantId = (dsai_session as any)?.dsai_tenantId as string | undefined;

  const [dsai_plateText, dsai_setPlateText] = useState("");
  const [dsai_mode, dsai_setMode] = useState<DsaiSearchMode>("exact");
  const [dsai_fuzzyThreshold, dsai_setFuzzyThreshold] = useState(0.7);
  const [dsai_topK, dsai_setTopK] = useState<number>(10);
  const [dsai_cameraIds, dsai_setCameraIds] = useState<string[]>([]);
  const [dsai_startTime, dsai_setStartTime] = useState("");
  const [dsai_endTime, dsai_setEndTime] = useState("");

  const [dsai_results, dsai_setResults] = useState<DsaiPlateResult[]>([]);
  const [dsai_isSearching, dsai_setIsSearching] = useState(false);
  const [dsai_error, dsai_setError] = useState<string | null>(null);
  const [dsai_searched, dsai_setSearched] = useState(false);
  const [dsai_previewItem, dsai_setPreviewItem] = useState<DsaiPlateResult | null>(null);

  const dsai_handleSearch = useCallback(async () => {
    const dsai_cleanPlate = dsai_plateText.trim().toUpperCase();
    if (!dsai_cleanPlate) {
      dsai_setError("Please enter a plate number.");
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
      const dsai_payload: DsaiPlateSearchPayload = {
        plate_number: dsai_cleanPlate,
        mode: dsai_mode,
        top_k: dsai_topK,
      };
      if (dsai_mode === "fuzzy") dsai_payload.threshold = dsai_fuzzyThreshold;
      if (dsai_cameraIds.length > 0) dsai_payload.camera_ids = dsai_cameraIds;
      if (dsai_startTime) dsai_payload.start_time = dsai_startTime;
      if (dsai_endTime) dsai_payload.end_time = dsai_endTime;

      const dsai_data = await dsai_apiPost<DsaiPlateApiResponse>(
        "search/search/plate",
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
          dsai_plateText: dsai_r.plate_text,
          dsai_thumbnailUrl: dsai_r.thumbnail_url,
          dsai_sceneThumbnailUrl: dsai_r.scene_thumbnail_url,
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
    dsai_plateText, dsai_mode, dsai_fuzzyThreshold, dsai_topK,
    dsai_cameraIds, dsai_startTime, dsai_endTime,
    dsai_accessToken, dsai_tenantId,
  ]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">License Plate Search</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Search for vehicles by license plate using exact or fuzzy matching.
        </p>
      </div>

      <div className="rounded-lg border bg-card p-5 space-y-4">
        {/* Mode toggle */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Search Mode</label>
          <div className="flex gap-2">
            {(["exact", "fuzzy"] as const).map((dsai_m) => (
              <button key={dsai_m} type="button"
                onClick={() => dsai_setMode(dsai_m)}
                className={cn(
                  "px-4 py-2 rounded-md text-sm font-medium border transition-colors capitalize",
                  dsai_mode === dsai_m
                    ? "bg-primary text-primary-foreground border-primary"
                    : "border-input text-muted-foreground hover:bg-accent"
                )}>
                {dsai_m}
              </button>
            ))}
          </div>
        </div>

        {/* Plate input */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Plate Number</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={dsai_plateText}
              onChange={(dsai_e) => dsai_setPlateText(dsai_e.target.value.toUpperCase())}
              onKeyDown={(dsai_e) => dsai_e.key === "Enter" && dsai_handleSearch()}
              placeholder="e.g. KA01AB1234"
              className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm font-mono uppercase tracking-widest focus:outline-none focus:ring-2 focus:ring-ring"
              spellCheck={false}
              autoCapitalize="characters"
            />
            <button
              onClick={dsai_handleSearch}
              disabled={dsai_isSearching || !dsai_plateText.trim()}
              className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed">
              {dsai_isSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              Search
            </button>
          </div>
        </div>

        {/* Fuzzy threshold (only in fuzzy mode) */}
        {dsai_mode === "fuzzy" && (
          <div className="space-y-1.5">
            <label className="text-sm font-medium">
              Similarity Threshold: {dsai_fuzzyThreshold.toFixed(2)}
              <span className="ml-2 text-xs text-muted-foreground">
                (lower = more results, higher = stricter match)
              </span>
            </label>
            <input
              type="range" min={0.5} max={1} step={0.05}
              value={dsai_fuzzyThreshold}
              onChange={(dsai_e) => dsai_setFuzzyThreshold(Number(dsai_e.target.value))}
              className="w-full" />
          </div>
        )}

        {/* Controls row */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
        </div>

        {/* Date range */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Start Time</label>
            <input type="datetime-local" value={dsai_startTime}
              onChange={(dsai_e) => dsai_setStartTime(dsai_e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">End Time</label>
            <input type="datetime-local" value={dsai_endTime}
              onChange={(dsai_e) => dsai_setEndTime(dsai_e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
          </div>
        </div>
      </div>

      {/* Error */}
      {dsai_error && (
        <div className="rounded-md border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {dsai_error}
        </div>
      )}

      {/* Results */}
      {dsai_searched && !dsai_isSearching && (
        <div>
          <p className="text-sm text-muted-foreground mb-4">
            {dsai_results.length === 0
              ? "No plates found. Try fuzzy mode or broaden your query."
              : `${dsai_results.length} result${dsai_results.length !== 1 ? "s" : ""} found`}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
            {dsai_results.map((dsai_r) => {
              const dsai_proxy = dsai_toProxyUrl(dsai_r.dsai_thumbnailUrl);
              const dsai_scorePercent = Math.round(dsai_r.dsai_score * 100);
              return (
                <div key={dsai_r.dsai_frameId}
                  className="rounded-lg border bg-card overflow-hidden shadow-sm hover:shadow-md transition-shadow">
                  {/* Plate crop */}
                  <div className="bg-black flex items-center justify-center p-3 min-h-[80px] relative group cursor-pointer"
                    onClick={() => dsai_setPreviewItem(dsai_r)}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={dsai_proxy} alt={`Plate ${dsai_r.dsai_plateText}`}
                      className="max-h-20 w-auto object-contain" loading="lazy" />
                    <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors flex items-center justify-center">
                      <ZoomIn className="h-5 w-5 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                    </div>
                    <span className={cn(
                      "absolute top-2 right-2 text-xs font-bold px-2 py-0.5 rounded-full",
                      dsai_scorePercent >= 80 ? "bg-green-600 text-white"
                        : dsai_scorePercent >= 60 ? "bg-yellow-500 text-black"
                        : "bg-gray-600 text-white"
                    )}>
                      {dsai_scorePercent}%
                    </span>
                  </div>
                  {/* OCR text */}
                  <div className="px-3 py-2 bg-muted/50 text-center">
                    <DsaiOcrHighlight dsai_ocrText={dsai_r.dsai_plateText} dsai_query={dsai_plateText} />
                  </div>
                  {/* Meta */}
                  <div className="p-3 space-y-1">
                    <div className="text-xs font-mono text-muted-foreground truncate">{dsai_r.dsai_cameraId}</div>
                    <div className="text-xs text-muted-foreground">{new Date(dsai_r.dsai_timestamp).toLocaleString()}</div>
                    <button onClick={() => dsai_setPreviewItem(dsai_r)}
                      className="text-xs text-primary hover:underline mt-1">
                      View Scene
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Scene modal */}
      <DsaiSceneModal dsai_result={dsai_previewItem} dsai_onClose={() => dsai_setPreviewItem(null)} />
    </div>
  );
}
