"use client";

/**
 * Raw Image-Based Similarity Search page.
 *
 * Operators drop any scene or object image and discover visually similar
 * frames across the video archive using CLIP embedding similarity via Milvus.
 *
 * Client-side validations:
 *   - Supported formats: JPEG, PNG, WebP
 *   - Max file size: 10 MB (rejected with clear error message before upload)
 *
 * Calls the search service image endpoint (POST /search/image or equivalent
 * configured in SearchService:8081).
 *
 * Issue: #33 — Raw Image-Based Similarity Search UI
 */

import React, { useCallback, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { ImageIcon, Loader2, Search, X } from "lucide-react";
import { CameraSelector } from "@/components/camera/CameraSelector";
import { dsai_apiPost } from "@/lib/api/dsai_client";
import { cn } from "@/lib/dsai_utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DSAI_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024; // 10 MB
const DSAI_ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];
const DSAI_TOP_K_OPTIONS = [10, 25, 50, 100] as const;

const DSAI_TARGET_COLLECTIONS = [
  { dsai_value: "general", dsai_label: "General Scenes (CLIP)" },
  { dsai_value: "vehicle", dsai_label: "Vehicle Embeddings" },
  { dsai_value: "person", dsai_label: "Person Embeddings" },
] as const;

type DsaiTargetCollection = "general" | "vehicle" | "person";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DsaiImageSearchResult {
  dsai_frameId: string;
  dsai_cameraId: string;
  dsai_timestamp: string;
  dsai_score: number;
  dsai_thumbnailUrl: string;
  dsai_videoId?: string;
}

interface DsaiImageSearchPayload {
  image_base64: string;
  target_collection: DsaiTargetCollection;
  top_k: number;
  threshold: number;
  camera_ids?: string[];
}

interface DsaiImageSearchApiResponse {
  results: Array<{
    frame_id: string;
    camera_id: string;
    timestamp: string;
    score: number;
    thumbnail_url: string;
    video_id?: string;
  }>;
}

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

function dsai_validateImageFile(dsai_file: File): string | null {
  if (!DSAI_ACCEPTED_TYPES.includes(dsai_file.type)) {
    return `Unsupported file type: ${dsai_file.type}. Please use JPEG, PNG, or WebP.`;
  }
  if (dsai_file.size > DSAI_MAX_FILE_SIZE_BYTES) {
    const dsai_sizeMb = (dsai_file.size / (1024 * 1024)).toFixed(1);
    return `File too large (${dsai_sizeMb} MB). Maximum allowed size is 10 MB.`;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ImageSearchPage() {
  const { data: dsai_session } = useSession();
  const dsai_accessToken = (dsai_session as any)?.dsai_accessToken as string | undefined;
  const dsai_tenantId = (dsai_session as any)?.dsai_tenantId as string | undefined;

  const [dsai_imageFile, dsai_setImageFile] = useState<File | null>(null);
  const [dsai_imagePreview, dsai_setImagePreview] = useState<string | null>(null);
  const [dsai_imageBase64, dsai_setImageBase64] = useState<string | null>(null);
  const dsai_fileInputRef = useRef<HTMLInputElement>(null);

  const [dsai_collection, dsai_setCollection] = useState<DsaiTargetCollection>("general");
  const [dsai_topK, dsai_setTopK] = useState<number>(10);
  const [dsai_threshold, dsai_setThreshold] = useState(0.3);
  const [dsai_cameraIds, dsai_setCameraIds] = useState<string[]>([]);

  const [dsai_results, dsai_setResults] = useState<DsaiImageSearchResult[]>([]);
  const [dsai_isSearching, dsai_setIsSearching] = useState(false);
  const [dsai_error, dsai_setError] = useState<string | null>(null);
  const [dsai_searched, dsai_setSearched] = useState(false);
  const [dsai_isDragging, dsai_setIsDragging] = useState(false);

  const dsai_handleFileSelect = useCallback(async (dsai_file: File) => {
    const dsai_validationError = dsai_validateImageFile(dsai_file);
    if (dsai_validationError) {
      dsai_setError(dsai_validationError);
      return;
    }
    dsai_setError(null);
    dsai_setImageFile(dsai_file);

    try {
      const dsai_dataUrl = await dsai_fileToBase64(dsai_file);
      dsai_setImagePreview(dsai_dataUrl);
      dsai_setImageBase64(dsai_dataUrl);
    } catch {
      dsai_setError("Failed to read image file.");
    }
  }, []);

  const dsai_clearImage = useCallback(() => {
    dsai_setImageFile(null);
    dsai_setImagePreview(null);
    dsai_setImageBase64(null);
    if (dsai_fileInputRef.current) dsai_fileInputRef.current.value = "";
  }, []);

  const dsai_handleSearch = useCallback(async () => {
    if (!dsai_imageBase64) {
      dsai_setError("Please upload a query image.");
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
      const dsai_payload: DsaiImageSearchPayload = {
        image_base64: dsai_imageBase64,
        target_collection: dsai_collection,
        top_k: dsai_topK,
        threshold: dsai_threshold,
      };
      if (dsai_cameraIds.length > 0) dsai_payload.camera_ids = dsai_cameraIds;

      const dsai_data = await dsai_apiPost<DsaiImageSearchApiResponse>(
        "search/search/image",
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
          dsai_videoId: dsai_r.video_id,
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
  }, [dsai_imageBase64, dsai_collection, dsai_topK, dsai_threshold, dsai_cameraIds, dsai_accessToken, dsai_tenantId]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Image Similarity Search</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Drop any scene or object image to discover visually similar frames across the video archive.
        </p>
      </div>

      <div className="rounded-lg border bg-card p-5 space-y-4">
        {/* Image dropzone */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Query Image</label>
          {dsai_imagePreview ? (
            <div className="relative inline-block">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={dsai_imagePreview} alt="Query image preview"
                className="max-h-48 w-auto rounded border object-contain" />
              <button onClick={dsai_clearImage}
                className="absolute -top-2 -right-2 rounded-full bg-destructive text-destructive-foreground p-0.5 shadow">
                <X className="h-3.5 w-3.5" />
              </button>
              <div className="mt-1 text-xs text-muted-foreground">
                {dsai_imageFile?.name} ({((dsai_imageFile?.size ?? 0) / (1024 * 1024)).toFixed(2)} MB)
              </div>
            </div>
          ) : (
            <div
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-10 text-sm text-muted-foreground transition-colors",
                dsai_isDragging ? "border-primary bg-primary/5" : "border-input hover:border-primary/50"
              )}
              onClick={() => dsai_fileInputRef.current?.click()}
              onDrop={(dsai_e) => {
                dsai_e.preventDefault();
                dsai_setIsDragging(false);
                const dsai_f = dsai_e.dataTransfer.files[0];
                if (dsai_f) dsai_handleFileSelect(dsai_f);
              }}
              onDragOver={(dsai_e) => { dsai_e.preventDefault(); dsai_setIsDragging(true); }}
              onDragLeave={() => dsai_setIsDragging(false)}
            >
              <ImageIcon className="h-10 w-10 text-muted-foreground/60" />
              <div className="text-center">
                <div className="font-medium">Drop an image here or click to browse</div>
                <div className="text-xs mt-1">JPEG, PNG, WebP — max 10 MB</div>
              </div>
            </div>
          )}
          <input ref={dsai_fileInputRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden"
            onChange={(dsai_e) => { const dsai_f = dsai_e.target.files?.[0]; if (dsai_f) dsai_handleFileSelect(dsai_f); }} />
        </div>

        {/* Search target collection */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Target Collection</label>
          <div className="flex flex-wrap gap-2">
            {DSAI_TARGET_COLLECTIONS.map((dsai_col) => (
              <button key={dsai_col.dsai_value} type="button"
                onClick={() => dsai_setCollection(dsai_col.dsai_value)}
                className={cn(
                  "px-3 py-1.5 rounded-md text-sm border transition-colors",
                  dsai_collection === dsai_col.dsai_value
                    ? "bg-primary text-primary-foreground border-primary"
                    : "border-input text-muted-foreground hover:bg-accent"
                )}>
                {dsai_col.dsai_label}
              </button>
            ))}
          </div>
        </div>

        {/* Controls */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
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
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Cameras</label>
            <CameraSelector dsai_value={dsai_cameraIds} dsai_onChange={dsai_setCameraIds} dsai_placeholder="All cameras" />
          </div>
        </div>

        <button onClick={dsai_handleSearch}
          disabled={dsai_isSearching || !dsai_imageBase64}
          className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed">
          {dsai_isSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          Find Similar Frames
        </button>
      </div>

      {/* Error */}
      {dsai_error && (
        <div className="rounded-md border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {dsai_error}
        </div>
      )}

      {/* Results — masonry-style grid */}
      {dsai_searched && !dsai_isSearching && (
        <div>
          <p className="text-sm text-muted-foreground mb-4">
            {dsai_results.length === 0
              ? "No similar frames found. Try a different image or lower the similarity threshold."
              : `${dsai_results.length} visually similar frame${dsai_results.length !== 1 ? "s" : ""} found`}
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
            {dsai_results.map((dsai_r) => {
              const dsai_proxy = dsai_toProxyUrl(dsai_r.dsai_thumbnailUrl);
              return (
                <div key={dsai_r.dsai_frameId}
                  className="group rounded-lg border bg-card overflow-hidden shadow-sm hover:shadow-md transition-shadow cursor-pointer">
                  <div className="aspect-video bg-muted relative overflow-hidden">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={dsai_proxy} alt={`Similar frame ${dsai_r.dsai_frameId}`}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                      loading="lazy" />
                    <span className={cn(
                      "absolute top-1.5 right-1.5 text-[10px] font-bold px-1.5 py-0.5 rounded-full",
                      dsai_r.dsai_score >= 0.8 ? "bg-green-600 text-white"
                        : dsai_r.dsai_score >= 0.5 ? "bg-yellow-500 text-black"
                        : "bg-gray-600 text-white"
                    )}>
                      {Math.round(dsai_r.dsai_score * 100)}%
                    </span>
                  </div>
                  <div className="p-2 space-y-0.5">
                    <div className="text-[10px] font-mono text-muted-foreground truncate">{dsai_r.dsai_cameraId}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {new Date(dsai_r.dsai_timestamp).toLocaleDateString()}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Loading skeleton */}
      {dsai_isSearching && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
          {Array.from({ length: Math.min(dsai_topK, 10) }).map((_, dsai_i) => (
            <div key={dsai_i} className="rounded-lg border bg-card overflow-hidden">
              <div className="aspect-video bg-muted animate-pulse" />
              <div className="p-2 space-y-1">
                <div className="h-2.5 w-2/3 bg-muted animate-pulse rounded" />
                <div className="h-2.5 w-1/2 bg-muted animate-pulse rounded" />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
