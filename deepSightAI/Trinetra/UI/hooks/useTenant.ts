"use client";

/**
 * useTenant Hook — standard export matching Issue #26 requirement.
 * Re-exports useTenant hook and relevant tenant types from TenantContext.
 */

export { useTenant } from "@/context/TenantContext";
export type { DsaiTenant, DsaiTenantContextValue } from "@/context/TenantContext";
