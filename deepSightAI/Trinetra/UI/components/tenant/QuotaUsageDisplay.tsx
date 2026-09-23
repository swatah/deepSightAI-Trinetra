"use client";

/**
 * QuotaUsageDisplay — tenant quota and resource usage visualisation widget.
 *
 * Phase 0 Decision 4: No backend quota API exists yet. Display informational
 * tier metrics with an explicit disclaimer banner. When a real quota API is
 * available, remove the dsai_informational flag and wire dsai_metrics directly
 * to the API response.
 *
 * Issue: #28 — Tenant Quota & Resource Usage Display
 */

import React from "react";
import { AlertTriangle, CheckCircle, Info, TrendingUp } from "lucide-react";
import { cn } from "@/lib/dsai_utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DsaiQuotaMetric {
  /** Display label */
  dsai_label: string;
  /** Current consumed value */
  dsai_used: number;
  /** Maximum allowed value (quota ceiling) */
  dsai_max: number;
  /** Unit suffix for display, e.g. "GB", "hr", "q/min" */
  dsai_unit: string;
  /** Override automatic status calculation */
  dsai_statusOverride?: "normal" | "warning" | "exceeded";
}

export interface QuotaUsageDisplayProps {
  /** Metrics to display. Pass empty array or undefined to show skeleton. */
  dsai_metrics?: DsaiQuotaMetric[];
  /** When true, renders the v1 informational disclaimer banner. */
  dsai_informational?: boolean;
  /** Optional heading for the widget */
  dsai_title?: string;
  /** Loading state — renders skeleton bars */
  dsai_isLoading?: boolean;
  /** Callback for "Request Quota Increase" CTA */
  dsai_onRequestIncrease?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type DsaiStatusLevel = "normal" | "warning" | "exceeded";

function dsai_getStatus(
  dsai_used: number,
  dsai_max: number,
  dsai_override?: DsaiStatusLevel
): DsaiStatusLevel {
  if (dsai_override) return dsai_override;
  const dsai_pct = dsai_max > 0 ? (dsai_used / dsai_max) * 100 : 0;
  if (dsai_pct >= 100) return "exceeded";
  if (dsai_pct >= 80) return "warning";
  return "normal";
}

const DSAI_STATUS_STYLES: Record<DsaiStatusLevel, string> = {
  normal: "bg-green-500",
  warning: "bg-yellow-500",
  exceeded: "bg-red-500",
};

const DSAI_STATUS_ICONS: Record<DsaiStatusLevel, React.ReactNode> = {
  normal: <CheckCircle className="h-4 w-4 text-green-500" />,
  warning: <AlertTriangle className="h-4 w-4 text-yellow-500" />,
  exceeded: <AlertTriangle className="h-4 w-4 text-red-500" />,
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function DsaiProgressBar({
  dsai_pct,
  dsai_status,
}: {
  dsai_pct: number;
  dsai_status: DsaiStatusLevel;
}) {
  return (
    <div className="relative h-2 w-full rounded-full bg-muted overflow-hidden">
      <div
        className={cn(
          "absolute inset-y-0 left-0 rounded-full transition-all duration-500",
          DSAI_STATUS_STYLES[dsai_status]
        )}
        style={{ width: `${Math.min(dsai_pct, 100)}%` }}
        role="progressbar"
        aria-valuenow={Math.round(dsai_pct)}
        aria-valuemin={0}
        aria-valuemax={100}
      />
    </div>
  );
}

function DsaiSkeletonRow() {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between">
        <div className="h-4 w-32 rounded bg-muted animate-pulse" />
        <div className="h-4 w-20 rounded bg-muted animate-pulse" />
      </div>
      <div className="h-2 w-full rounded-full bg-muted animate-pulse" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * QuotaUsageDisplay — renders resource utilisation progress bars per metric.
 *
 * The optional informational banner (dsai_informational=true) signals to
 * operators that quota figures are estimated tier values pending backend
 * enforcement, per Phase 0 architectural decision 4.
 */
export function QuotaUsageDisplay({
  dsai_metrics,
  dsai_informational = true,
  dsai_title = "Resource Usage",
  dsai_isLoading = false,
  dsai_onRequestIncrease,
}: QuotaUsageDisplayProps) {
  return (
    <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-muted-foreground" />
          <h3 className="font-semibold text-base">{dsai_title}</h3>
        </div>
        {dsai_onRequestIncrease && (
          <button
            onClick={dsai_onRequestIncrease}
            className="text-xs text-primary hover:underline font-medium"
          >
            Request Quota Increase
          </button>
        )}
      </div>

      {/* Informational disclaimer banner */}
      {dsai_informational && (
        <div className="flex items-start gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800 dark:bg-blue-900/20 dark:border-blue-700 dark:text-blue-300">
          <Info className="h-4 w-4 mt-0.5 flex-shrink-0" />
          <span>
            <strong>Informational Tier Estimates</strong> — Backend enforcement pending.
            Figures shown are approximate tier quotas and do not enforce hard limits yet.
          </span>
        </div>
      )}

      {/* Metrics */}
      <div className="space-y-4">
        {dsai_isLoading || !dsai_metrics ? (
          <>
            <DsaiSkeletonRow />
            <DsaiSkeletonRow />
            <DsaiSkeletonRow />
          </>
        ) : dsai_metrics.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-4">
            No usage metrics available.
          </p>
        ) : (
          dsai_metrics.map((dsai_metric) => {
            const dsai_pct =
              dsai_metric.dsai_max > 0
                ? (dsai_metric.dsai_used / dsai_metric.dsai_max) * 100
                : 0;
            const dsai_status = dsai_getStatus(
              dsai_metric.dsai_used,
              dsai_metric.dsai_max,
              dsai_metric.dsai_statusOverride
            );

            return (
              <div key={dsai_metric.dsai_label} className="space-y-1.5">
                <div className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-1.5">
                    {DSAI_STATUS_ICONS[dsai_status]}
                    <span className="font-medium">{dsai_metric.dsai_label}</span>
                  </div>
                  <span
                    className={cn(
                      "text-xs font-mono tabular-nums",
                      dsai_status === "exceeded"
                        ? "text-red-600 dark:text-red-400"
                        : dsai_status === "warning"
                        ? "text-yellow-600 dark:text-yellow-400"
                        : "text-muted-foreground"
                    )}
                  >
                    {dsai_metric.dsai_used.toLocaleString()}&nbsp;/&nbsp;
                    {dsai_metric.dsai_max.toLocaleString()}&nbsp;{dsai_metric.dsai_unit}
                    &nbsp;({Math.round(dsai_pct)}%)
                  </span>
                </div>
                <DsaiProgressBar dsai_pct={dsai_pct} dsai_status={dsai_status} />
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
