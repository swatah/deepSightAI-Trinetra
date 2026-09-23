"use client";

/**
 * Watchlist Management page — Phase 5, Issue #35.
 *
 * Full CRUD interface for surveillance targets (plates, persons, vehicles)
 * against WatchlistMatcherService:8083 with strict role-based action gating.
 *
 * RBAC rule: AuthService issues `roles` only — no permissions array.
 * Write operations (Create/Edit/Delete/Toggle) are gated behind roles.includes("admin").
 */

import React, { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { Plus, Trash2, Edit2, ToggleLeft, ToggleRight, Loader2, ShieldAlert, X } from "lucide-react";
import { dsai_apiGet, dsai_apiPost, dsai_apiPut, dsai_apiDelete } from "@/lib/api/dsai_client";
import { dsai_isAdmin } from "@/lib/auth/dsai_rbac";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type DsaiPriority = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
type DsaiTargetType = "plate" | "person" | "vehicle";

interface DsaiWatchlistEntry {
  dsai_id: number;
  dsai_targetType: DsaiTargetType;
  dsai_identifier: string;
  dsai_priority: DsaiPriority;
  dsai_active: boolean;
  dsai_notes: string | null;
  dsai_referenceImageUrl: string | null;
  dsai_createdAt: string;
}

interface DsaiWatchlistApiEntry {
  id: number;
  target_type: DsaiTargetType;
  identifier: string;
  priority: string;
  active: boolean;
  notes?: string | null;
  reference_image_url?: string | null;
  created_at: string;
}

interface DsaiCreatePayload {
  target_type: DsaiTargetType;
  identifier: string;
  priority: DsaiPriority;
  active: boolean;
  notes?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DSAI_PRIORITY_COLORS: Record<DsaiPriority, string> = {
  CRITICAL: "bg-red-600 text-white",
  HIGH: "bg-orange-500 text-white",
  MEDIUM: "bg-yellow-400 text-black",
  LOW: "bg-blue-500 text-white",
};

const DSAI_PRIORITY_OPTIONS: DsaiPriority[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
const DSAI_TARGET_TYPE_OPTIONS: DsaiTargetType[] = ["plate", "person", "vehicle"];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function dsai_toProxyUrl(dsai_rawUrl: string | null): string | null {
  if (!dsai_rawUrl) return null;
  try {
    const dsai_parsed = new URL(dsai_rawUrl);
    return `/api/media${dsai_parsed.pathname}`;
  } catch {
    return `/api/media/${dsai_rawUrl.replace(/^\//, "")}`;
  }
}

function dsai_mapEntry(dsai_raw: DsaiWatchlistApiEntry): DsaiWatchlistEntry {
  return {
    dsai_id: dsai_raw.id,
    dsai_targetType: dsai_raw.target_type,
    dsai_identifier: dsai_raw.identifier,
    dsai_priority: (dsai_raw.priority?.toUpperCase() as DsaiPriority) ?? "MEDIUM",
    dsai_active: dsai_raw.active,
    dsai_notes: dsai_raw.notes ?? null,
    dsai_referenceImageUrl: dsai_raw.reference_image_url ?? null,
    dsai_createdAt: dsai_raw.created_at,
  };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function DsaiPriorityBadge({ dsai_priority }: { dsai_priority: DsaiPriority }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold ${DSAI_PRIORITY_COLORS[dsai_priority]}`}
    >
      {dsai_priority}
    </span>
  );
}

function DsaiEntryModal({
  dsai_entry,
  dsai_onClose,
  dsai_onSave,
}: {
  dsai_entry: Partial<DsaiWatchlistEntry> | null;
  dsai_onClose: () => void;
  dsai_onSave: (dsai_payload: DsaiCreatePayload) => Promise<void>;
}) {
  const [dsai_targetType, dsai_setTargetType] = useState<DsaiTargetType>(
    dsai_entry?.dsai_targetType ?? "plate"
  );
  const [dsai_identifier, dsai_setIdentifier] = useState(dsai_entry?.dsai_identifier ?? "");
  const [dsai_priority, dsai_setPriority] = useState<DsaiPriority>(
    dsai_entry?.dsai_priority ?? "MEDIUM"
  );
  const [dsai_active, dsai_setActive] = useState(dsai_entry?.dsai_active ?? true);
  const [dsai_notes, dsai_setNotes] = useState(dsai_entry?.dsai_notes ?? "");
  const [dsai_saving, dsai_setSaving] = useState(false);
  const [dsai_error, dsai_setError] = useState<string | null>(null);

  const dsai_handleSubmit = useCallback(async () => {
    if (!dsai_identifier.trim()) {
      dsai_setError("Identifier is required.");
      return;
    }
    dsai_setSaving(true);
    dsai_setError(null);
    try {
      const dsai_payload: DsaiCreatePayload = {
        target_type: dsai_targetType,
        identifier: dsai_identifier.trim(),
        priority: dsai_priority,
        active: dsai_active,
      };
      if (dsai_notes.trim()) dsai_payload.notes = dsai_notes.trim();
      await dsai_onSave(dsai_payload);
      dsai_onClose();
    } catch (dsai_err) {
      dsai_setError(dsai_err instanceof Error ? dsai_err.message : "Save failed.");
    } finally {
      dsai_setSaving(false);
    }
  }, [dsai_targetType, dsai_identifier, dsai_priority, dsai_active, dsai_notes, dsai_onSave, dsai_onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
      onClick={dsai_onClose}
    >
      <div
        className="relative w-full max-w-md rounded-xl bg-card border shadow-2xl p-6 space-y-4"
        onClick={(dsai_e) => dsai_e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            {dsai_entry?.dsai_id ? "Edit Target" : "Add Watchlist Target"}
          </h2>
          <button onClick={dsai_onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Target Type */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Target Type</label>
          <select
            value={dsai_targetType}
            onChange={(dsai_e) => dsai_setTargetType(dsai_e.target.value as DsaiTargetType)}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {DSAI_TARGET_TYPE_OPTIONS.map((dsai_t) => (
              <option key={dsai_t} value={dsai_t}>
                {dsai_t === "plate" ? "License Plate" : dsai_t === "person" ? "Person Re-ID" : "Vehicle Re-ID"}
              </option>
            ))}
          </select>
        </div>

        {/* Identifier */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">
            {dsai_targetType === "plate" ? "Plate Number" : dsai_targetType === "person" ? "Suspect Notes / Name" : "Vehicle Description"}
          </label>
          <input
            type="text"
            value={dsai_identifier}
            onChange={(dsai_e) => dsai_setIdentifier(dsai_e.target.value)}
            placeholder={
              dsai_targetType === "plate"
                ? "e.g. DL01AB9999"
                : dsai_targetType === "person"
                ? "e.g. Red hoodie, male approx 180cm"
                : "e.g. White Toyota Camry"
            }
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        {/* Priority */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Priority</label>
          <select
            value={dsai_priority}
            onChange={(dsai_e) => dsai_setPriority(dsai_e.target.value as DsaiPriority)}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {DSAI_PRIORITY_OPTIONS.map((dsai_p) => (
              <option key={dsai_p} value={dsai_p}>{dsai_p}</option>
            ))}
          </select>
        </div>

        {/* Notes */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Notes (optional)</label>
          <textarea
            value={dsai_notes}
            onChange={(dsai_e) => dsai_setNotes(dsai_e.target.value)}
            rows={2}
            placeholder="Additional context, clothing description, vehicle color..."
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring resize-none"
          />
        </div>

        {/* Active toggle */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => dsai_setActive((dsai_prev) => !dsai_prev)}
            className="text-primary"
          >
            {dsai_active ? <ToggleRight className="h-6 w-6" /> : <ToggleLeft className="h-6 w-6 text-muted-foreground" />}
          </button>
          <span className="text-sm">{dsai_active ? "Active" : "Inactive"}</span>
        </div>

        {dsai_error && (
          <p className="text-sm text-destructive">{dsai_error}</p>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-2">
          <button
            onClick={dsai_onClose}
            className="rounded-md border px-4 py-2 text-sm hover:bg-muted"
          >
            Cancel
          </button>
          <button
            onClick={dsai_handleSubmit}
            disabled={dsai_saving}
            className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {dsai_saving && <Loader2 className="h-4 w-4 animate-spin" />}
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

function DsaiEntryRow({
  dsai_entry,
  dsai_isAdmin,
  dsai_onEdit,
  dsai_onDelete,
  dsai_onToggle,
}: {
  dsai_entry: DsaiWatchlistEntry;
  dsai_isAdmin: boolean;
  dsai_onEdit: (dsai_e: DsaiWatchlistEntry) => void;
  dsai_onDelete: (dsai_id: number) => void;
  dsai_onToggle: (dsai_id: number, dsai_active: boolean) => void;
}) {
  const dsai_thumbUrl = dsai_toProxyUrl(dsai_entry.dsai_referenceImageUrl);

  return (
    <tr className="border-b last:border-0 hover:bg-muted/30">
      <td className="px-4 py-3">
        {dsai_thumbUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={dsai_thumbUrl}
            alt="crop"
            className="h-12 w-16 object-cover rounded border"
            onError={(dsai_e) => {
              (dsai_e.target as HTMLImageElement).style.display = "none";
            }}
          />
        ) : (
          <div className="h-12 w-16 rounded border bg-muted flex items-center justify-center text-xs text-muted-foreground">
            No img
          </div>
        )}
      </td>
      <td className="px-4 py-3">
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-secondary text-secondary-foreground capitalize">
          {dsai_entry.dsai_targetType}
        </span>
      </td>
      <td className="px-4 py-3 font-mono text-sm">{dsai_entry.dsai_identifier}</td>
      <td className="px-4 py-3">
        <DsaiPriorityBadge dsai_priority={dsai_entry.dsai_priority} />
      </td>
      <td className="px-4 py-3">
        {dsai_isAdmin ? (
          <button
            onClick={() => dsai_onToggle(dsai_entry.dsai_id, !dsai_entry.dsai_active)}
            className="text-primary"
            title={dsai_entry.dsai_active ? "Deactivate" : "Activate"}
          >
            {dsai_entry.dsai_active ? (
              <ToggleRight className="h-5 w-5 text-green-500" />
            ) : (
              <ToggleLeft className="h-5 w-5 text-muted-foreground" />
            )}
          </button>
        ) : (
          <span className={`text-xs font-medium ${dsai_entry.dsai_active ? "text-green-600" : "text-muted-foreground"}`}>
            {dsai_entry.dsai_active ? "Active" : "Inactive"}
          </span>
        )}
      </td>
      <td className="px-4 py-3 text-xs text-muted-foreground">
        {new Date(dsai_entry.dsai_createdAt).toLocaleDateString()}
      </td>
      {dsai_isAdmin && (
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <button
              onClick={() => dsai_onEdit(dsai_entry)}
              className="text-muted-foreground hover:text-primary"
              title="Edit"
            >
              <Edit2 className="h-4 w-4" />
            </button>
            <button
              onClick={() => dsai_onDelete(dsai_entry.dsai_id)}
              className="text-muted-foreground hover:text-destructive"
              title="Delete"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </td>
      )}
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function WatchlistPage() {
  const { data: dsai_session } = useSession();
  const dsai_accessToken = (dsai_session as any)?.dsai_accessToken as string | undefined;
  const dsai_tenantId = (dsai_session as any)?.dsai_tenantId as string | undefined;
  const dsai_userIsAdmin = dsai_isAdmin(dsai_session);

  const [dsai_entries, dsai_setEntries] = useState<DsaiWatchlistEntry[]>([]);
  const [dsai_loading, dsai_setLoading] = useState(true);
  const [dsai_error, dsai_setError] = useState<string | null>(null);
  const [dsai_modalEntry, dsai_setModalEntry] = useState<Partial<DsaiWatchlistEntry> | null>(null);
  const [dsai_modalOpen, dsai_setModalOpen] = useState(false);

  // ------------------------------------------------------------------
  // Fetch watchlist
  // ------------------------------------------------------------------
  const dsai_fetchWatchlist = useCallback(async () => {
    if (!dsai_accessToken || !dsai_tenantId) return;
    dsai_setLoading(true);
    dsai_setError(null);
    try {
      const dsai_data = await dsai_apiGet<{ items?: DsaiWatchlistApiEntry[] } | DsaiWatchlistApiEntry[]>(
        "watchlist/watchlist",
        dsai_accessToken,
        dsai_tenantId
      );
      const dsai_rawItems: DsaiWatchlistApiEntry[] = Array.isArray(dsai_data)
        ? dsai_data
        : (dsai_data as any)?.items ?? [];
      dsai_setEntries(dsai_rawItems.map(dsai_mapEntry));
    } catch (dsai_err) {
      dsai_setError(dsai_err instanceof Error ? dsai_err.message : "Failed to load watchlist.");
    } finally {
      dsai_setLoading(false);
    }
  }, [dsai_accessToken, dsai_tenantId]);

  useEffect(() => {
    dsai_fetchWatchlist();
  }, [dsai_fetchWatchlist]);

  // ------------------------------------------------------------------
  // Create / Update
  // ------------------------------------------------------------------
  const dsai_handleSave = useCallback(
    async (dsai_payload: DsaiCreatePayload) => {
      if (!dsai_accessToken || !dsai_tenantId) return;
      if (dsai_modalEntry?.dsai_id) {
        await dsai_apiPut(
          `watchlist/watchlist/${dsai_modalEntry.dsai_id}`,
          dsai_accessToken,
          dsai_tenantId,
          dsai_payload
        );
      } else {
        await dsai_apiPost("watchlist/watchlist", dsai_accessToken, dsai_tenantId, dsai_payload);
      }
      await dsai_fetchWatchlist();
    },
    [dsai_accessToken, dsai_tenantId, dsai_modalEntry, dsai_fetchWatchlist]
  );

  // ------------------------------------------------------------------
  // Delete
  // ------------------------------------------------------------------
  const dsai_handleDelete = useCallback(
    async (dsai_id: number) => {
      if (!dsai_accessToken || !dsai_tenantId) return;
      if (!window.confirm("Delete this watchlist target? This action cannot be undone.")) return;
      try {
        await dsai_apiDelete(`watchlist/watchlist/${dsai_id}`, dsai_accessToken, dsai_tenantId);
        dsai_setEntries((dsai_prev) => dsai_prev.filter((dsai_e) => dsai_e.dsai_id !== dsai_id));
      } catch (dsai_err) {
        dsai_setError(dsai_err instanceof Error ? dsai_err.message : "Delete failed.");
      }
    },
    [dsai_accessToken, dsai_tenantId]
  );

  // ------------------------------------------------------------------
  // Toggle active
  // ------------------------------------------------------------------
  const dsai_handleToggle = useCallback(
    async (dsai_id: number, dsai_active: boolean) => {
      if (!dsai_accessToken || !dsai_tenantId) return;
      try {
        await dsai_apiPut(`watchlist/watchlist/${dsai_id}`, dsai_accessToken, dsai_tenantId, {
          active: dsai_active,
        });
        dsai_setEntries((dsai_prev) =>
          dsai_prev.map((dsai_e) =>
            dsai_e.dsai_id === dsai_id ? { ...dsai_e, dsai_active: dsai_active } : dsai_e
          )
        );
      } catch (dsai_err) {
        dsai_setError(dsai_err instanceof Error ? dsai_err.message : "Toggle failed.");
      }
    },
    [dsai_accessToken, dsai_tenantId]
  );

  const dsai_openCreate = () => {
    dsai_setModalEntry({});
    dsai_setModalOpen(true);
  };

  const dsai_openEdit = (dsai_entry: DsaiWatchlistEntry) => {
    dsai_setModalEntry(dsai_entry);
    dsai_setModalOpen(true);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Watchlist</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Manage surveillance targets — plates, persons, and vehicles.
          </p>
        </div>
        {dsai_userIsAdmin && (
          <button
            onClick={dsai_openCreate}
            className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" />
            Add Target
          </button>
        )}
        {!dsai_userIsAdmin && (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground border rounded-md px-3 py-1.5">
            <ShieldAlert className="h-3.5 w-3.5" />
            Read-only — admin role required for write operations
          </div>
        )}
      </div>

      {/* Error */}
      {dsai_error && (
        <div className="rounded-md border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {dsai_error}
        </div>
      )}

      {/* Table */}
      <div className="rounded-lg border overflow-hidden">
        {dsai_loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : dsai_entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <p className="text-sm">No watchlist targets configured.</p>
            {dsai_userIsAdmin && (
              <button
                onClick={dsai_openCreate}
                className="mt-3 text-sm text-primary hover:underline"
              >
                Add the first target
              </button>
            )}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-muted text-muted-foreground text-xs uppercase">
              <tr>
                <th className="px-4 py-3 text-left">Image</th>
                <th className="px-4 py-3 text-left">Type</th>
                <th className="px-4 py-3 text-left">Identifier</th>
                <th className="px-4 py-3 text-left">Priority</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Added</th>
                {dsai_userIsAdmin && <th className="px-4 py-3 text-left">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {dsai_entries.map((dsai_entry) => (
                <DsaiEntryRow
                  key={dsai_entry.dsai_id}
                  dsai_entry={dsai_entry}
                  dsai_isAdmin={dsai_userIsAdmin}
                  dsai_onEdit={dsai_openEdit}
                  dsai_onDelete={dsai_handleDelete}
                  dsai_onToggle={dsai_handleToggle}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modal */}
      {dsai_modalOpen && (
        <DsaiEntryModal
          dsai_entry={dsai_modalEntry}
          dsai_onClose={() => {
            dsai_setModalOpen(false);
            dsai_setModalEntry(null);
          }}
          dsai_onSave={dsai_handleSave}
        />
      )}
    </div>
  );
}
