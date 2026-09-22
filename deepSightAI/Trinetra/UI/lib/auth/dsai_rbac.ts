import type { Session } from "next-auth";

/**
 * RBAC helper for deepSightAI Trinetra.
 *
 * IMPORTANT: AuthService issues ONLY `roles` (["admin"], ["operator"], ["viewer"])
 * in the JWT. There is NO `permissions` array. All permission gates are satisfied
 * by checking role membership — particularly `"admin"` in roles.
 */

/**
 * dsai_hasRole — checks whether the authenticated session includes a specific role.
 *
 * @param dsai_session - NextAuth Session object from useSession() or getServerSession()
 * @param dsai_role    - The role string to check for (e.g. "admin", "operator", "viewer")
 * @returns true if the session contains the given role, false otherwise
 */
export function dsai_hasRole(
  dsai_session: Session | null | undefined,
  dsai_role: string
): boolean {
  if (!dsai_session) return false;
  const dsai_roles = (dsai_session as any).dsai_roles as string[] | undefined;
  if (!Array.isArray(dsai_roles)) return false;
  return dsai_roles.includes(dsai_role);
}

/**
 * dsai_isAdmin — returns true if the authenticated user has the "admin" role.
 * Satisfies: watchlist:write, alerts:acknowledge, admin panel access gates.
 *
 * @param dsai_session - NextAuth Session object
 * @returns true if user is an admin, false otherwise
 */
export function dsai_isAdmin(
  dsai_session: Session | null | undefined
): boolean {
  return dsai_hasRole(dsai_session, "admin");
}

/**
 * dsai_isOperator — returns true if the user has the "operator" role.
 *
 * @param dsai_session - NextAuth Session object
 * @returns true if user is an operator
 */
export function dsai_isOperator(
  dsai_session: Session | null | undefined
): boolean {
  return dsai_hasRole(dsai_session, "operator");
}

/**
 * dsai_isViewer — returns true if the user has the "viewer" role.
 *
 * @param dsai_session - NextAuth Session object
 * @returns true if user is a viewer
 */
export function dsai_isViewer(
  dsai_session: Session | null | undefined
): boolean {
  return dsai_hasRole(dsai_session, "viewer");
}

/**
 * dsai_getRoles — returns the full roles array from the session, or an empty array.
 *
 * @param dsai_session - NextAuth Session object
 * @returns string[] of role names
 */
export function dsai_getRoles(
  dsai_session: Session | null | undefined
): string[] {
  if (!dsai_session) return [];
  const dsai_roles = (dsai_session as any).dsai_roles as string[] | undefined;
  return Array.isArray(dsai_roles) ? dsai_roles : [];
}

/**
 * dsai_getTenantId — returns the tenant_id from the session, or null.
 *
 * @param dsai_session - NextAuth Session object
 * @returns tenant_id string or null
 */
export function dsai_getTenantId(
  dsai_session: Session | null | undefined
): string | null {
  if (!dsai_session) return null;
  return (dsai_session as any).dsai_tenantId as string | null;
}
