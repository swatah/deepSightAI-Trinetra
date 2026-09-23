"use client";

/**
 * Vehicle Attribute & Reference-Crop Search page.
 *
 * Supports two modalities:
 *   1. Attribute filters (color, body type, time, cameras)
 *   2. Optional reference crop upload (base64 encoded, sent to backend)
 *
 * Calls POST /search/vehicle on SearchService:8081.
 * Backend already handles `image_base64.split(",")[-1]` so standard
 * data URLs (data:image/jpeg;base64,...) are forwarded as-is.
 *
 * Issue: #30 — Vehicle Attribute & Reference-Crop Search UI
 */

import React, { useCallback, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { Loader2, Search, Upload, X } from "lucide-react";
import { CameraSelector } from "@/components/camera/CameraSelector";
import { dsai_apiPost } from "@/lib/api/dsai_client";
import { cn } from "@/lib/dsai_utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DSAI_VEHICLE_COLORS = [
  "Black", "White", "Silver", "Gray", "Red", "Blue",
  "Yellow", "Green", "Brown", "Orange", "Purple", "Other",
];

const DSAI_BODY_TYPES = [
  "Sedan", "SUV", "Truck", "Van", "Bus", "Motorcycle", "Bicycle", "Other",
];

const DSAI_TOP_K_OPTIONS = [10, 25, 50, 100] as const;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DsaiVehicleCandidate {
  dsai_frameId: string;
  dsai_cameraId: string;
  dsai_timestamp: string;
  dsai_score: number;
  dsai_thumbnailUrl: string;
  dsai_attributes?: Record<string, string>;
}

interface DsaiVehicleSearchPayload {
  color?: string;
  body_type?: string;
  top_k: number;
  threshold: number;
  camera_ids?: string[];
  start_time?: string;
  end_time?: string;
  image_base64?: string;
}

interface DsaiVehicleApiResponse {
  results: Array<{
    frame_id: string;
    camera_id: string;
    timestamp: string;
    score: number;
    thumbnail_url: string;
    attributes?: Record<string, string>;
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

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function VehicleSearchPage() {
  const { data: dsai_session } = useSession();
  const dsai_accessToken = (dsai_session as any)?.dsai_accessToken as string | undefined;
  const dsai_tenantId = (dsai_session as any)?.dsai_tenantId as string | undefined;

  const [dsai_color, dsai_setColor] = useState("");
  const [dsai_bodyType, dsai_setBodyType] = useState("");
  const [dsai_topK, dsai_setTopK] = useState<number>(10);
  const [dsai_threshold, dsai_setThreshold] = useState(0.3);
  const [dsai_cameraIds, dsai_setCameraIds] = useState<string[]>([]);
  const [dsai_startTime, dsai_setStartTime] = useState("");
  const [dsai_endTime, dsai_setEndTime] = useState("");

  const [dsai_cropFile, dsai_setCropFile] = useState<File | null>(null);
  const [dsai_cropPreview, dsai_setCropPreview] = useState<string | null>(null);
  const dsai_fileInputRef = useRef<HTMLInputElement>(null);

  const [dsai_results, dsai_setResults] = useState<DsaiVehicleCandidate[]>([]);
  const [dsai_isSearching, dsai_setIsSearching] = useState(false);
  const [dsai_error, dsai_setError] = useState<string | null>(null);
  const [dsai_searched, dsai_setSearched] = useState(false);

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

  const dsai_handleSearch = useCallback(async () => {
    if (!dsai_color && !dsai_bodyType && !dsai_cropFile) {
      dsai_setError("Provide at least one filter: color, body type, or a reference crop.");
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
      const dsai_payload: DsaiVehicleSearchPayload = {
        top_k: dsai_topK,
        threshold: dsai_threshold,
      };
      if (dsai_color) dsai_payload.color = dsai_color.toLowerCase();
      if (dsai_bodyType) dsai_payload.body_type = dsai_bodyType.toLowerCase();
      if (dsai_cameraIds.length > 0) dsai_payload.camera_ids = dsai_cameraIds;
      if (dsai_startTime) dsai_payload.start_time = dsai_startTime;
      if (dsai_endTime) dsai_payload.end_time = dsai_endTime;
      if (dsai_cropPreview) dsai_payload.image_base64 = dsai_cropPreview;

      const dsai_data = await dsai_apiPost<DsaiVehicleApiResponse>(
        "search/search/vehicle",
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
          dsai_attributes: dsai_r.attributes,
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
    dsai_color, dsai_bodyType, dsai_cropFile, dsai_cropPreview,
    dsai_topK, dsai_threshold, dsai_cameraIds, dsai_startTime, dsai_endTime,
    dsai_accessToken, dsai_tenantId,
  ]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Vehicle Search</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Filter by colour and body type, or upload a reference crop for similarity matching.
        </p>
      </div>

      <div className="rounded-lg border bg-card p-5 space-y-4">
        {/* Attribute filters */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Vehicle Color</label>
            <select
              value={dsai_color}
              onChange={(dsai_e) => dsai_setColor(dsai_e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">Any color</option>
              {DSAI_VEHICLE_COLORS.map((dsai_c) => (
                <option key={dsai_c} value={dsai_c}>{dsai_c}</option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Body Type</label>
            <select
              value={dsai_bodyType}
              onChange={(dsai_e) => dsai_setBodyType(dsai_e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">Any type</option>
              {DSAI_BODY_TYPES.map((dsai_t) => (
                <option key={dsai_t} value={dsai_t}>{dsai_t}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Reference crop uploader */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Reference Crop (optional)</label>
          {dsai_cropPreview ? (
            <div className="relative inline-block">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={dsai_cropPreview}
                alt="Reference crop preview"
                className="h-32 w-auto rounded border object-contain"
              />
              <button
                onClick={dsai_clearCrop}
                className="absolute -top-2 -right-2 rounded-full bg-destructive text-destructive-foreground p-0.5 shadow"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <div
              className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-input p-6 text-sm text-muted-foreground hover:border-primary/50 transition-colors"
              onClick={() => dsai_fileInputRef.current?.click()}
              onDrop={(dsai_e) => {
                dsai_e.preventDefault();
                const dsai_f = dsai_e.dataTransfer.files[0];
                if (dsai_f) dsai_handleCropSelect(dsai_f);
              }}
              onDragOver={(dsai_e) => dsai_e.preventDefault()}
            >
              <Upload className="h-6 w-6" />
              <span>Drop an image or click to upload</span>
            </div>
          )}
          <input
            ref={dsai_fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(dsai_e) => {
              const dsai_f = dsai_e.target.files?.[0];
              if (dsai_f) dsai_handleCropSelect(dsai_f);
            }}
          />
        </div>

        {/* Controls */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Results</label>
            <select
              value={dsai_topK}
              onChange={(dsai_e) => dsai_setTopK(Number(dsai_e.target.value))}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              {DSAI_TOP_K_OPTIONS.map((dsai_n) => (
                <option key={dsai_n} value={dsai_n}>Top {dsai_n}</option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Min Similarity: {dsai_threshold.toFixed(2)}</label>
            <input
              type="range" min={0} max={1} step={0.05}
              value={dsai_threshold}
              onChange={(dsai_e) => dsai_setThreshold(Number(dsai_e.target.value))}
              className="w-full"
            />
          </div>
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

        <button
          onClick={dsai_handleSearch}
          disabled={dsai_isSearching}
          className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {dsai_isSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          Search Vehicles
        </button>
      </div>

      {/* Error */}
      {dsai_error && (
        <div className="rounded-md border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {dsai_error}
        </div>
      )}

      {/* Results grid */}
      {dsai_searched && !dsai_isSearching && (
        <div>
          <p className="text-sm text-muted-foreground mb-4">
            {dsai_results.length === 0
              ? "No matches found. Try adjusting filters or lowering the threshold."
              : `${dsai_results.length} candidate${dsai_results.length !== 1 ? "s" : ""} found`}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {dsai_results.map((dsai_r) => {
              const dsai_proxy = dsai_toProxyUrl(dsai_r.dsai_thumbnailUrl);
              return (
                <div key={dsai_r.dsai_frameId} className="rounded-lg border bg-card overflow-hidden shadow-sm">
                  <div className="aspect-video bg-muted relative">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={dsai_proxy} alt={`Vehicle ${dsai_r.dsai_frameId}`}
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
                    {dsai_r.dsai_attributes && Object.keys(dsai_r.dsai_attributes).length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(dsai_r.dsai_attributes).map(([dsai_k, dsai_v]) => (
                          <span key={dsai_k} className="text-xs bg-muted rounded px-1.5 py-0.5">
                            {dsai_k}: {dsai_v}
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="text-xs font-mono text-muted-foreground truncate">{dsai_r.dsai_cameraId}</div>
                    <div className="text-xs text-muted-foreground">{new Date(dsai_r.dsai_timestamp).toLocaleString()}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
