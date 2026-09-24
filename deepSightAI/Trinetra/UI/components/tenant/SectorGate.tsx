"use client";

/**
 * SectorGate — restricts a sector-specific dashboard to tenants whose sector
 * matches, or to platform administrators.
 *
 * Reused by the Law Enforcement, Commercial, and Logistics dashboards, which
 * previously rendered unconditionally for any authenticated user.
 */

import React from "react";
import { useSession } from "next-auth/react";
import { ShieldAlert } from "lucide-react";
import { useTenant } from "@/hooks/useTenant";
import { dsai_isAdmin } from "@/lib/auth/dsai_rbac";

export interface SectorGateProps {
  /** Sector key required to view the wrapped content, e.g. "law_enforcement" */
  dsai_requiredSector: string;
  /** Human-readable label for the access-denied message, e.g. "Law Enforcement" */
  dsai_label: string;
  children: React.ReactNode;
}

export function SectorGate({ dsai_requiredSector, dsai_label, children }: SectorGateProps) {
  const { data: dsai_session, status: dsai_authStatus } = useSession();
  const { dsai_sector, dsai_isLoading } = useTenant();

  if (dsai_authStatus === "loading" || dsai_isLoading) {
    return (
      <div className="p-12 text-center text-slate-400 font-mono text-sm">
        Loading tenant context...
      </div>
    );
  }

  const dsai_allowed = dsai_isAdmin(dsai_session) || dsai_sector === dsai_requiredSector;

  if (!dsai_allowed) {
    return (
      <div className="min-h-[500px] flex items-center justify-center p-6">
        <div className="max-w-md w-full text-center space-y-4 bg-slate-900 border border-red-500/20 p-8 rounded-2xl shadow-xl">
          <div className="inline-flex p-3 rounded-full bg-red-500/10 text-red-400">
            <ShieldAlert className="w-8 h-8" />
          </div>
          <h2 className="text-xl font-bold text-white">403 Sector Access Restricted</h2>
          <p className="text-sm text-slate-400">
            The {dsai_label} dashboard is limited to tenants provisioned for the{" "}
            <span className="font-mono text-slate-300">{dsai_requiredSector}</span> sector.
          </p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
