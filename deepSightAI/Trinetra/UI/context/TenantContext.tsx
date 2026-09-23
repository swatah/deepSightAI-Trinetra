"use client";

/**
 * TenantContext — React Context providing active tenant metadata across Trinetra UI.
 *
 * Design (Phase 0 Decision 5):
 *   - tenant_id is extracted from the NextAuth session token.
 *   - Full tenant profile is fetched from GET /tenants/{id} on AuthService:8002.
 *   - `sector` is stored inside the `plugin_config` JSON blob (no dedicated column yet).
 *
 * Issue: #26 — Multi-Tenant Context Provider & useTenant Hook
 */

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { dsai_apiGet } from "@/lib/api/dsai_client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DsaiTenant {
  /** UUID primary key */
  dsai_id: string;
  /** Human-readable display name */
  dsai_name: string;
  /** URL-safe slug */
  dsai_slug: string;
  /** Whether the tenant account is currently active */
  dsai_active: boolean;
  /**
   * Industry sector, stored in plugin_config per Phase 0 decision 5.
   * Examples: "law_enforcement", "retail", "transport", "government"
   */
  dsai_sector: string | null;
  /** Raw plugin_config blob for advanced callers */
  dsai_pluginConfig: Record<string, unknown>;
}

export interface DsaiTenantContextValue {
  /** Full tenant object, or null while loading / unauthenticated */
  dsai_tenant: DsaiTenant | null;
  /** Shorthand for dsai_tenant?.dsai_id */
  dsai_tenantId: string | null;
  /** Shorthand for dsai_tenant?.dsai_sector */
  dsai_sector: string | null;
  /** True while the tenant profile is being fetched */
  dsai_isLoading: boolean;
  /** Error string if the fetch failed */
  dsai_error: string | null;
  /** Re-fetch the tenant profile on demand */
  dsai_refreshTenant: () => void;
  /** Returns true if the active tenant's sector matches the given value */
  dsai_isSector: (dsai_targetSector: string) => boolean;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const DsaiTenantContext = createContext<DsaiTenantContextValue>({
  dsai_tenant: null,
  dsai_tenantId: null,
  dsai_sector: null,
  dsai_isLoading: false,
  dsai_error: null,
  dsai_refreshTenant: () => {},
  dsai_isSector: () => false,
});

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

/** Raw shape returned by GET /tenants/{id} on AuthService */
interface DsaiTenantApiResponse {
  id: string;
  name: string;
  slug: string;
  active: boolean;
  plugin_config?: Record<string, unknown> | null;
}

export function DsaiTenantProvider({ children }: { children: React.ReactNode }) {
  const { data: dsai_session, status: dsai_sessionStatus } = useSession();

  const [dsai_tenant, dsai_setTenant] = useState<DsaiTenant | null>(null);
  const [dsai_isLoading, dsai_setIsLoading] = useState(false);
  const [dsai_error, dsai_setError] = useState<string | null>(null);
  const [dsai_refreshToken, dsai_setRefreshToken] = useState(0);

  // Derive tenant ID directly from session (available before the extra fetch completes)
  const dsai_tenantId = (dsai_session as any)?.dsai_tenantId as string | null ?? null;
  const dsai_accessToken = (dsai_session as any)?.dsai_accessToken as string | null ?? null;

  useEffect(() => {
    if (dsai_sessionStatus !== "authenticated" || !dsai_tenantId || !dsai_accessToken) {
      dsai_setTenant(null);
      dsai_setError(null);
      return;
    }

    let dsai_cancelled = false;
    dsai_setIsLoading(true);
    dsai_setError(null);

    dsai_apiGet<DsaiTenantApiResponse>(
      `auth/tenants/${dsai_tenantId}`,
      dsai_accessToken,
      dsai_tenantId
    )
      .then((dsai_data) => {
        if (dsai_cancelled || !dsai_data) return;
        const dsai_pluginConfig =
          (dsai_data.plugin_config as Record<string, unknown> | null) ?? {};
        const dsai_sector =
          typeof dsai_pluginConfig["sector"] === "string"
            ? dsai_pluginConfig["sector"]
            : null;

        dsai_setTenant({
          dsai_id: dsai_data.id,
          dsai_name: dsai_data.name,
          dsai_slug: dsai_data.slug,
          dsai_active: dsai_data.active,
          dsai_sector: dsai_sector,
          dsai_pluginConfig: dsai_pluginConfig,
        });
      })
      .catch((dsai_err: unknown) => {
        if (dsai_cancelled) return;
        dsai_setError(
          dsai_err instanceof Error ? dsai_err.message : "Failed to load tenant profile"
        );
      })
      .finally(() => {
        if (!dsai_cancelled) dsai_setIsLoading(false);
      });

    return () => {
      dsai_cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dsai_sessionStatus, dsai_tenantId, dsai_accessToken, dsai_refreshToken]);

  const dsai_refreshTenant = useCallback(() => {
    dsai_setRefreshToken((dsai_prev) => dsai_prev + 1);
  }, []);

  const dsai_isSector = useCallback(
    (dsai_targetSector: string) => dsai_tenant?.dsai_sector === dsai_targetSector,
    [dsai_tenant]
  );

  const dsai_contextValue: DsaiTenantContextValue = {
    dsai_tenant,
    dsai_tenantId,
    dsai_sector: dsai_tenant?.dsai_sector ?? null,
    dsai_isLoading,
    dsai_error,
    dsai_refreshTenant,
    dsai_isSector,
  };

  return (
    <DsaiTenantContext.Provider value={dsai_contextValue}>
      {children}
    </DsaiTenantContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * useTenant — consume the active tenant context.
 *
 * Must be used inside <DsaiTenantProvider>.
 */
export function useTenant(): DsaiTenantContextValue {
  return useContext(DsaiTenantContext);
}
