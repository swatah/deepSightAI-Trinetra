"use client";

/**
 * Text Semantic Search page — natural language query against CLIP embeddings.
 *
 * Calls POST /search/text on SearchService:8081 and renders results in a
 * card grid. Thumbnails are proxied via /api/media/[...path] to resolve
 * internal MinIO URLs (Phase 0 Decision 8).
 *
 * Issue: #29 — Text Semantic Search UI with MinIO Media Proxy Thumbnail Rendering
 */

import React, { useCallback, useState } from "react";
import { useSession } from "next-auth/react";
import { Search, Loader2, Download, X } from "lucide-react";
import { CameraSelector } from "@/components/camera/CameraSelector";
import { dsai_apiPost } from "@/lib/api/dsai_client";
import { cn } from "@/lib/dsai_utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DsaiSearchResultItem {
  dsai_frameId: string;
  dsai_videoId: string;
  dsai_cameraId: string;
  dsai_timestamp: string;
  dsai_score: number;
  dsai_thumbnailUrl: string;
}

interface DsaiTextSearchPayload {
  query: string;
  top_k: number;
  threshold: number;
  camera_ids?: string[];
  start_time?: string;
  end_time?: string;
}

interface DsaiSearchApiResponse {
  results: Array<{
    frame_id: string;
    video_id: string;
    camera_id: string;
    timestamp: string;
    score: number;
    thumbnail_url: string;
  }>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * dsai_toProxyUrl — converts an internal MinIO URL to a browser-accessible
 * path through the Next.js media proxy.
 *
 * e.g. http://minio:9000/frames/tenant-1/frame.jpg
 *   → /api/media/frames/tenant-1/frame.jpg
 */
function dsai_toProxyUrl(dsai_rawUrl: string): string {
  try {
    const dsai_parsed = new URL(dsai_rawUrl);
    // Strip scheme + host, keep the path (remove leading slash)
    return `/api/media${dsai_parsed.pathname}`;
  } catch {
    // Relative path or non-URL string — proxy as-is
    return `/api/media/${dsai_rawUrl.replace(/^\//, "")}`;
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function DsaiResultCard({
  dsai_result,
  dsai_onPreview,
}: {
  dsai_result: DsaiSearchResultItem;
  dsai_onPreview: (dsai_r: DsaiSearchResultItem) => void;
}) {
  const dsai_scorePercent = Math.round(dsai_result.dsai_score * 100);
  const dsai_proxyUrl = dsai_toProxyUrl(dsai_result.dsai_thumbnailUrl);

  return (
    <div className="group rounded-lg border bg-card overflow-hidden shadow-sm hover:shadow-md transition-shadow">
      {/* Thumbnail */}
      <div
        className="relative aspect-video cursor-pointer bg-muted"
        onClick={() => dsai_onPreview(dsai_result)}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={dsai_proxyUrl}
          alt={`Frame ${dsai_result.dsai_frameId}`}
          className="object-cover w-full h-full"
          loading="lazy"
          onError={(dsai_e) => {
            (dsai_e.target as HTMLImageElement).src =
              "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='320' height='180'%3E%3Crect width='320' height='180' fill='%23374151'/%3E%3Ctext x='50%25' y='50%25' fill='%236B7280' font-size='14' text-anchor='middle' dy='.3em'%3ENo preview%3C/text%3E%3C/svg%3E";
          }}
        />
        {/* Score badge */}
        <span
          className={cn(
            "absolute top-2 right-2 text-xs font-bold px-2 py-0.5 rounded-full",
            dsai_scorePercent >= 80
              ? "bg-green-600 text-white"
              : dsai_scorePercent >= 50
              ? "bg-yellow-500 text-black"
              : "bg-gray-600 text-white"
          )}
        >
          {dsai_scorePercent}%
        </span>
      </div>

      {/* Meta */}
      <div className="p-3 space-y-1">
        <div className="text-xs font-mono text-muted-foreground truncate">
          {dsai_result.dsai_cameraId}
        </div>
        <div className="text-xs text-muted-foreground">
          {new Date(dsai_result.dsai_timestamp).toLocaleString()}
        </div>
        <div className="flex items-center justify-between pt-1">
          <button
            className="text-xs text-primary hover:underline"
            onClick={() => dsai_onPreview(dsai_result)}
          >
            Preview
          </button>
          <a
            href={dsai_proxyUrl}
            download={`frame-${dsai_result.dsai_frameId}.jpg`}
            className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
          >
            <Download className="h-3 w-3" />
            Download
          </a>
        </div>
      </div>
    </div>
  );
}

function DsaiPreviewModal({
  dsai_result,
  dsai_onClose,
}: {
  dsai_result: DsaiSearchResultItem | null;
  dsai_onClose: () => void;
}) {
  if (!dsai_result) return null;
  const dsai_proxyUrl = dsai_toProxyUrl(dsai_result.dsai_thumbnailUrl);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
      onClick={dsai_onClose}
    >
      <div
        className="relative max-w-4xl w-full mx-4 rounded-xl overflow-hidden bg-card shadow-2xl"
        onClick={(dsai_e) => dsai_e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <div className="text-sm font-medium">
            Frame {dsai_result.dsai_frameId}
          </div>
          <button
            onClick={dsai_onClose}
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={dsai_proxyUrl}
          alt={`Full preview ${dsai_result.dsai_frameId}`}
          className="w-full object-contain max-h-[70vh]"
        />
        <div className="px-4 py-3 border-t flex items-center justify-between text-sm">
          <div className="text-muted-foreground">
            {dsai_result.dsai_cameraId} &bull;{" "}
            {new Date(dsai_result.dsai_timestamp).toLocaleString()}
          </div>
          <a
            href={dsai_proxyUrl}
            download={`frame-${dsai_result.dsai_frameId}.jpg`}
            className="flex items-center gap-1.5 text-primary hover:underline"
          >
            <Download className="h-4 w-4" />
            Download
          </a>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

/** Top-K options for the results selector */
const DSAI_TOP_K_OPTIONS = [10, 25, 50, 100] as const;

export default function TextSearchPage() {
  const { data: dsai_session } = useSession();
  const dsai_accessToken = (dsai_session as any)?.dsai_accessToken as string | undefined;
  const dsai_tenantId = (dsai_session as any)?.dsai_tenantId as string | undefined;

  const [dsai_query, dsai_setQuery] = useState("");
  const [dsai_topK, dsai_setTopK] = useState<number>(10);
  const [dsai_threshold, dsai_setThreshold] = useState(0.3);
  const [dsai_cameraIds, dsai_setCameraIds] = useState<string[]>([]);
  const [dsai_startTime, dsai_setStartTime] = useState("");
  const [dsai_endTime, dsai_setEndTime] = useState("");

  const [dsai_results, dsai_setResults] = useState<DsaiSearchResultItem[]>([]);
  const [dsai_isSearching, dsai_setIsSearching] = useState(false);
  const [dsai_error, dsai_setError] = useState<string | null>(null);
  const [dsai_searched, dsai_setSearched] = useState(false);
  const [dsai_previewItem, dsai_setPreviewItem] = useState<DsaiSearchResultItem | null>(null);

  const dsai_handleSearch = useCallback(async () => {
    if (!dsai_query.trim()) {
      dsai_setError("Please enter a search query.");
      return;
    }
    if (!dsai_accessToken || !dsai_tenantId) {
      dsai_setError("Session expired. Please log in again.");
      return;
    }

    dsai_setIsSearching(true);
    dsai_setError(null);
    dsai_setSearched(false);

    const dsai_payload: DsaiTextSearchPayload = {
      query: dsai_query.trim(),
      top_k: dsai_topK,
      threshold: dsai_threshold,
    };
    if (dsai_cameraIds.length > 0) dsai_payload.camera_ids = dsai_cameraIds;
    if (dsai_startTime) dsai_payload.start_time = dsai_startTime;
    if (dsai_endTime) dsai_payload.end_time = dsai_endTime;

    try {
      const dsai_data = await dsai_apiPost<DsaiSearchApiResponse>(
        "search/search/text",
        dsai_accessToken,
        dsai_tenantId,
        dsai_payload
      );

      dsai_setResults(
        (dsai_data?.results ?? []).map((dsai_r) => ({
          dsai_frameId: dsai_r.frame_id,
          dsai_videoId: dsai_r.video_id,
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
    dsai_query,
    dsai_topK,
    dsai_threshold,
    dsai_cameraIds,
    dsai_startTime,
    dsai_endTime,
    dsai_accessToken,
    dsai_tenantId,
  ]);

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold">Text Semantic Search</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Describe what you&apos;re looking for in natural language. Results are ranked by
          visual similarity.
        </p>
      </div>

      {/* Search form */}
      <div className="rounded-lg border bg-card p-5 space-y-4">
        {/* Query input */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Search Query</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={dsai_query}
              onChange={(dsai_e) => dsai_setQuery(dsai_e.target.value)}
              onKeyDown={(dsai_e) => dsai_e.key === "Enter" && dsai_handleSearch()}
              placeholder="e.g. red motorcycle speeding through intersection"
              className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <button
              onClick={dsai_handleSearch}
              disabled={dsai_isSearching || !dsai_query.trim()}
              className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {dsai_isSearching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              Search
            </button>
          </div>
        </div>

        {/* Controls row */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {/* Top-K */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Results</label>
            <select
              value={dsai_topK}
              onChange={(dsai_e) => dsai_setTopK(Number(dsai_e.target.value))}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              {DSAI_TOP_K_OPTIONS.map((dsai_n) => (
                <option key={dsai_n} value={dsai_n}>
                  Top {dsai_n}
                </option>
              ))}
            </select>
          </div>

          {/* Threshold slider */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">
              Min Similarity: {dsai_threshold.toFixed(2)}
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={dsai_threshold}
              onChange={(dsai_e) => dsai_setThreshold(Number(dsai_e.target.value))}
              className="w-full"
            />
          </div>

          {/* Camera selector */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Cameras</label>
            <CameraSelector
              dsai_value={dsai_cameraIds}
              dsai_onChange={dsai_setCameraIds}
              dsai_placeholder="All cameras"
            />
          </div>
        </div>

        {/* Date range */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Start Time</label>
            <input
              type="datetime-local"
              value={dsai_startTime}
              onChange={(dsai_e) => dsai_setStartTime(dsai_e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">End Time</label>
            <input
              type="datetime-local"
              value={dsai_endTime}
              onChange={(dsai_e) => dsai_setEndTime(dsai_e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
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
              ? "No results found. Try adjusting your query or lowering the similarity threshold."
              : `${dsai_results.length} result${dsai_results.length !== 1 ? "s" : ""} found`}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {dsai_results.map((dsai_r) => (
              <DsaiResultCard
                key={dsai_r.dsai_frameId}
                dsai_result={dsai_r}
                dsai_onPreview={dsai_setPreviewItem}
              />
            ))}
          </div>
        </div>
      )}

      {/* Loading skeleton */}
      {dsai_isSearching && (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {Array.from({ length: dsai_topK > 8 ? 8 : dsai_topK }).map((_, dsai_i) => (
            <div key={dsai_i} className="rounded-lg border bg-card overflow-hidden">
              <div className="aspect-video bg-muted animate-pulse" />
              <div className="p-3 space-y-2">
                <div className="h-3 w-2/3 bg-muted animate-pulse rounded" />
                <div className="h-3 w-1/2 bg-muted animate-pulse rounded" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Preview modal */}
      <DsaiPreviewModal
        dsai_result={dsai_previewItem}
        dsai_onClose={() => dsai_setPreviewItem(null)}
      />
    </div>
  );
}
