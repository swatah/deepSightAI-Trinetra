"use client";

/**
 * SectorBadge — renders a colour-coded badge with an icon for the tenant's industry sector.
 *
 * Each sector maps to a distinct Tailwind colour scheme and icon so operators can
 * instantly identify the deployment context at a glance.
 *
 * Issue: #27 — Tenant SectorBadge Component & Dynamic Sector Styling
 */

import React from "react";
import {
  Shield,
  Store,
  Truck,
  Building2,
  Tag,
  HeartPulse,
  GraduationCap,
  UtensilsCrossed,
  Coins,
  Factory,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/dsai_utils";

// ---------------------------------------------------------------------------
// Sector colour & icon mapping
// ---------------------------------------------------------------------------

const DSAI_SECTOR_STYLES: Record<
  string,
  { dsai_label: string; dsai_className: string; dsai_icon: LucideIcon }
> = {
  law_enforcement: {
    dsai_label: "Law Enforcement",
    dsai_icon: Shield,
    dsai_className:
      "bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-900/40 dark:text-blue-200 dark:border-blue-700",
  },
  retail: {
    dsai_label: "Retail",
    dsai_icon: Store,
    dsai_className:
      "bg-green-100 text-green-800 border-green-300 dark:bg-green-900/40 dark:text-green-200 dark:border-green-700",
  },
  commercial: {
    dsai_label: "Commercial",
    dsai_icon: Building2,
    dsai_className:
      "bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-900/40 dark:text-emerald-200 dark:border-emerald-700",
  },
  logistics: {
    dsai_label: "Logistics",
    dsai_icon: Truck,
    dsai_className:
      "bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-900/40 dark:text-amber-200 dark:border-amber-700",
  },
  transport: {
    dsai_label: "Transport",
    dsai_icon: Truck,
    dsai_className:
      "bg-yellow-100 text-yellow-800 border-yellow-300 dark:bg-yellow-900/40 dark:text-yellow-200 dark:border-yellow-700",
  },
  government: {
    dsai_label: "Government",
    dsai_icon: Building2,
    dsai_className:
      "bg-purple-100 text-purple-800 border-purple-300 dark:bg-purple-900/40 dark:text-purple-200 dark:border-purple-700",
  },
  healthcare: {
    dsai_label: "Healthcare",
    dsai_icon: HeartPulse,
    dsai_className:
      "bg-red-100 text-red-800 border-red-300 dark:bg-red-900/40 dark:text-red-200 dark:border-red-700",
  },
  education: {
    dsai_label: "Education",
    dsai_icon: GraduationCap,
    dsai_className:
      "bg-orange-100 text-orange-800 border-orange-300 dark:bg-orange-900/40 dark:text-orange-200 dark:border-orange-700",
  },
  hospitality: {
    dsai_label: "Hospitality",
    dsai_icon: UtensilsCrossed,
    dsai_className:
      "bg-pink-100 text-pink-800 border-pink-300 dark:bg-pink-900/40 dark:text-pink-200 dark:border-pink-700",
  },
  finance: {
    dsai_label: "Finance",
    dsai_icon: Coins,
    dsai_className:
      "bg-teal-100 text-teal-800 border-teal-300 dark:bg-teal-900/40 dark:text-teal-200 dark:border-teal-700",
  },
  critical_infrastructure: {
    dsai_label: "Critical Infrastructure",
    dsai_icon: Factory,
    dsai_className:
      "bg-slate-100 text-slate-800 border-slate-300 dark:bg-slate-900/40 dark:text-slate-200 dark:border-slate-700",
  },
};

const DSAI_DEFAULT_SECTOR_STYLE = {
  dsai_label: "General",
  dsai_icon: Tag,
  dsai_className:
    "bg-gray-100 text-gray-700 border-gray-300 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600",
};

// ---------------------------------------------------------------------------
// Props & Component
// ---------------------------------------------------------------------------

export interface SectorBadgeProps {
  /** Sector key as stored in plugin_config (e.g. "law_enforcement") */
  dsai_sector: string | null | undefined;
  /** Extra class names for the wrapper element */
  className?: string;
  /** Badge size variant */
  dsai_size?: "sm" | "md" | "lg";
  /** Whether to show sector icon */
  dsai_showIcon?: boolean;
}

/**
 * SectorBadge — pill-style badge indicating the tenant's industry sector.
 *
 * Renders nothing when dsai_sector is null or undefined.
 */
export function SectorBadge({
  dsai_sector,
  className,
  dsai_size = "sm",
  dsai_showIcon = true,
}: SectorBadgeProps) {
  if (!dsai_sector) return null;

  const dsai_style =
    DSAI_SECTOR_STYLES[dsai_sector] ?? {
      ...DSAI_DEFAULT_SECTOR_STYLE,
      dsai_label: dsai_sector
        .replace(/_/g, " ")
        .replace(/\b\w/g, (dsai_c) => dsai_c.toUpperCase()),
    };

  const IconComponent = dsai_style.dsai_icon;

  const dsai_sizeClasses = {
    sm: "text-xs px-2 py-0.5 gap-1",
    md: "text-sm px-2.5 py-1 gap-1.5",
    lg: "text-base px-3 py-1.5 gap-2",
  }[dsai_size];

  const dsai_iconSizes = {
    sm: "w-3 h-3",
    md: "w-3.5 h-3.5",
    lg: "w-4 h-4",
  }[dsai_size];

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border font-medium",
        dsai_sizeClasses,
        dsai_style.dsai_className,
        className
      )}
    >
      {dsai_showIcon && <IconComponent className={dsai_iconSizes} aria-hidden="true" />}
      <span>{dsai_style.dsai_label}</span>
    </span>
  );
}

/**
 * dsai_getSectorLabel — returns the human-readable label for a sector key.
 * Useful for rendering sector names without the badge wrapper.
 */
export function dsai_getSectorLabel(dsai_sector: string | null | undefined): string {
  if (!dsai_sector) return "Unknown";
  return (
    DSAI_SECTOR_STYLES[dsai_sector]?.dsai_label ??
    dsai_sector
      .replace(/_/g, " ")
      .replace(/\b\w/g, (dsai_c) => dsai_c.toUpperCase())
  );
}
