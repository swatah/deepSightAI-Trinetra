"use client";

/**
 * CameraSelector — dynamic camera topology multi-select component.
 *
 * Fetches the live camera list from SearchService:8081 GET /cameras and
 * renders a searchable multi-select combobox with Select All / Clear All
 * convenience toggles. Inactive cameras show a warning indicator.
 *
 * Issue: #34 — Dynamic Camera Topology Selector
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, CircleDot, Search, X } from "lucide-react";
import { useSession } from "next-auth/react";
import { cn } from "@/lib/dsai_utils";
import { dsai_apiGet } from "@/lib/api/dsai_client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DsaiCamera {
  dsai_id: string;
  dsai_name: string;
  dsai_location?: string;
  dsai_status: "active" | "inactive" | string;
  dsai_rtsp_url?: string;
}

/** Raw shape returned by GET /cameras */
interface DsaiCameraApiItem {
  id: string;
  name?: string;
  location?: string;
  status?: string;
  rtsp_url?: string;
}

export interface CameraSelectorProps {
  /** Current selection: array of camera IDs */
  dsai_value: string[];
  /** Called whenever the selection changes */
  dsai_onChange: (dsai_ids: string[]) => void;
  /** Optional placeholder text */
  dsai_placeholder?: string;
  /** Disable the selector entirely */
  dsai_disabled?: boolean;
  /** Extra class names for the root wrapper */
  className?: string;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * CameraSelector — searchable multi-select for camera IDs.
 *
 * Data is fetched once on mount and cached for the component lifetime.
 * Passes selected camera IDs to the parent via dsai_onChange.
 */
export function CameraSelector({
  dsai_value,
  dsai_onChange,
  dsai_placeholder = "Select cameras…",
  dsai_disabled = false,
  className,
}: CameraSelectorProps) {
  const { data: dsai_session } = useSession();
  const dsai_accessToken = (dsai_session as any)?.dsai_accessToken as string | undefined;
  const dsai_tenantId = (dsai_session as any)?.dsai_tenantId as string | undefined;

  const [dsai_cameras, dsai_setCameras] = useState<DsaiCamera[]>([]);
  const [dsai_isLoading, dsai_setIsLoading] = useState(false);
  const [dsai_fetchError, dsai_setFetchError] = useState<string | null>(null);
  const [dsai_open, dsai_setOpen] = useState(false);
  const [dsai_searchText, dsai_setSearchText] = useState("");
  const dsai_containerRef = useRef<HTMLDivElement>(null);

  // Fetch camera list on mount
  useEffect(() => {
    if (!dsai_accessToken || !dsai_tenantId) return;
    let dsai_cancelled = false;
    dsai_setIsLoading(true);
    dsai_setFetchError(null);

    dsai_apiGet<DsaiCameraApiItem[] | { cameras: DsaiCameraApiItem[] }>(
      "search/cameras",
      dsai_accessToken,
      dsai_tenantId
    )
      .then((dsai_raw) => {
        if (dsai_cancelled || !dsai_raw) return;
        // Handle both array and wrapped object response shapes
        const dsai_items: DsaiCameraApiItem[] = Array.isArray(dsai_raw)
          ? dsai_raw
          : (dsai_raw as { cameras: DsaiCameraApiItem[] }).cameras ?? [];

        dsai_setCameras(
          dsai_items.map((dsai_item) => ({
            dsai_id: dsai_item.id,
            dsai_name: dsai_item.name ?? dsai_item.id,
            dsai_location: dsai_item.location,
            dsai_status: dsai_item.status ?? "inactive",
            dsai_rtsp_url: dsai_item.rtsp_url,
          }))
        );
      })
      .catch((dsai_err: unknown) => {
        if (dsai_cancelled) return;
        dsai_setFetchError(
          dsai_err instanceof Error ? dsai_err.message : "Failed to load cameras"
        );
      })
      .finally(() => {
        if (!dsai_cancelled) dsai_setIsLoading(false);
      });

    return () => {
      dsai_cancelled = true;
    };
  }, [dsai_accessToken, dsai_tenantId]);

  // Close dropdown when clicking outside
  useEffect(() => {
    function dsai_handleOutsideClick(dsai_event: MouseEvent) {
      if (
        dsai_containerRef.current &&
        !dsai_containerRef.current.contains(dsai_event.target as Node)
      ) {
        dsai_setOpen(false);
        dsai_setSearchText("");
      }
    }
    document.addEventListener("mousedown", dsai_handleOutsideClick);
    return () => document.removeEventListener("mousedown", dsai_handleOutsideClick);
  }, []);

  // Filtered list based on search text
  const dsai_filteredCameras = useMemo(
    () =>
      dsai_cameras.filter(
        (dsai_cam) =>
          dsai_cam.dsai_name
            .toLowerCase()
            .includes(dsai_searchText.toLowerCase()) ||
          dsai_cam.dsai_id
            .toLowerCase()
            .includes(dsai_searchText.toLowerCase()) ||
          (dsai_cam.dsai_location ?? "")
            .toLowerCase()
            .includes(dsai_searchText.toLowerCase())
      ),
    [dsai_cameras, dsai_searchText]
  );

  const dsai_toggleCamera = useCallback(
    (dsai_id: string) => {
      dsai_onChange(
        dsai_value.includes(dsai_id)
          ? dsai_value.filter((dsai_v) => dsai_v !== dsai_id)
          : [...dsai_value, dsai_id]
      );
    },
    [dsai_value, dsai_onChange]
  );

  const dsai_selectAll = useCallback(() => {
    dsai_onChange(dsai_cameras.map((dsai_c) => dsai_c.dsai_id));
  }, [dsai_cameras, dsai_onChange]);

  const dsai_clearAll = useCallback(() => {
    dsai_onChange([]);
  }, [dsai_onChange]);

  // Summary label for the trigger button
  const dsai_triggerLabel = useMemo(() => {
    if (dsai_value.length === 0) return dsai_placeholder;
    if (dsai_value.length === 1) {
      const dsai_found = dsai_cameras.find((dsai_c) => dsai_c.dsai_id === dsai_value[0]);
      return dsai_found?.dsai_name ?? dsai_value[0];
    }
    return `${dsai_value.length} cameras selected`;
  }, [dsai_value, dsai_cameras, dsai_placeholder]);

  return (
    <div ref={dsai_containerRef} className={cn("relative", className)}>
      {/* Trigger */}
      <button
        type="button"
        disabled={dsai_disabled}
        onClick={() => dsai_setOpen((dsai_prev) => !dsai_prev)}
        className={cn(
          "flex w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
          dsai_value.length > 0 ? "text-foreground" : "text-muted-foreground"
        )}
      >
        <span className="truncate">{dsai_triggerLabel}</span>
        <div className="flex items-center gap-1 ml-2 flex-shrink-0">
          {dsai_value.length > 0 && (
            <span className="text-xs bg-primary text-primary-foreground rounded-full px-1.5 py-0.5 font-medium">
              {dsai_value.length}
            </span>
          )}
          <ChevronDown
            className={cn(
              "h-4 w-4 text-muted-foreground transition-transform",
              dsai_open && "rotate-180"
            )}
          />
        </div>
      </button>

      {/* Dropdown panel */}
      {dsai_open && (
        <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover text-popover-foreground shadow-lg">
          {/* Search input */}
          <div className="flex items-center gap-2 border-b px-3 py-2">
            <Search className="h-4 w-4 text-muted-foreground flex-shrink-0" />
            <input
              autoFocus
              type="text"
              value={dsai_searchText}
              onChange={(dsai_e) => dsai_setSearchText(dsai_e.target.value)}
              placeholder="Search cameras…"
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            {dsai_searchText && (
              <button
                type="button"
                onClick={() => dsai_setSearchText("")}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {/* Select All / Clear All */}
          <div className="flex items-center gap-3 border-b px-3 py-1.5">
            <button
              type="button"
              onClick={dsai_selectAll}
              className="text-xs text-primary hover:underline"
            >
              Select All
            </button>
            <button
              type="button"
              onClick={dsai_clearAll}
              className="text-xs text-muted-foreground hover:underline"
            >
              Clear All
            </button>
          </div>

          {/* Camera list */}
          <div className="max-h-60 overflow-y-auto py-1">
            {dsai_isLoading ? (
              <div className="px-3 py-4 text-center text-sm text-muted-foreground">
                Loading cameras…
              </div>
            ) : dsai_fetchError ? (
              <div className="px-3 py-4 text-center text-sm text-destructive">
                {dsai_fetchError}
              </div>
            ) : dsai_filteredCameras.length === 0 ? (
              <div className="px-3 py-4 text-center text-sm text-muted-foreground">
                No cameras found.
              </div>
            ) : (
              dsai_filteredCameras.map((dsai_cam) => {
                const dsai_isSelected = dsai_value.includes(dsai_cam.dsai_id);
                const dsai_isActive = dsai_cam.dsai_status === "active";

                return (
                  <button
                    key={dsai_cam.dsai_id}
                    type="button"
                    onClick={() => dsai_toggleCamera(dsai_cam.dsai_id)}
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-2 text-sm text-left hover:bg-accent hover:text-accent-foreground transition-colors",
                      dsai_isSelected && "bg-accent/50"
                    )}
                  >
                    {/* Checkbox indicator */}
                    <span
                      className={cn(
                        "h-4 w-4 flex-shrink-0 rounded border",
                        dsai_isSelected
                          ? "bg-primary border-primary"
                          : "border-input"
                      )}
                    >
                      {dsai_isSelected && (
                        <svg viewBox="0 0 12 12" className="text-primary-foreground fill-current">
                          <path d="M10 3L5 8.5 2 5.5" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </span>

                    {/* Camera status dot */}
                    <CircleDot
                      className={cn(
                        "h-3.5 w-3.5 flex-shrink-0",
                        dsai_isActive ? "text-green-500" : "text-muted-foreground/40"
                      )}
                    />

                    {/* Camera info */}
                    <div className="flex-1 min-w-0">
                      <div className="font-medium truncate">{dsai_cam.dsai_name}</div>
                      {dsai_cam.dsai_location && (
                        <div className="text-xs text-muted-foreground truncate">
                          {dsai_cam.dsai_location}
                        </div>
                      )}
                    </div>

                    {/* Inactive warning badge */}
                    {!dsai_isActive && (
                      <span className="text-xs text-yellow-600 dark:text-yellow-400 flex-shrink-0">
                        Inactive
                      </span>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
