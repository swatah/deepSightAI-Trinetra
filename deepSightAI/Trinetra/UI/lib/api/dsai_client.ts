"use client";

import { signOut } from "next-auth/react";

/**
 * DSAI_SESSION_EXPIRED_EVENT — custom DOM event name fired when a 401 response
 * is received. Components can listen for this event to show an expiry modal.
 */
export const DSAI_SESSION_EXPIRED_EVENT = "dsai:session-expired";

/**
 * DsaiApiError — typed error class for non-2xx HTTP responses from backend
 * microservices. Carries the HTTP status code so callers can branch on it.
 */
export class DsaiApiError extends Error {
  constructor(
    public readonly dsai_status: number,
    public readonly dsai_statusText: string,
    message?: string
  ) {
    super(message ?? `HTTP ${dsai_status}: ${dsai_statusText}`);
    this.name = "DsaiApiError";
  }
}

/**
 * DsaiRequestOptions — superset of standard RequestInit with Trinetra-specific
 * fields for overriding the injected auth headers.
 */
export interface DsaiRequestOptions extends RequestInit {
  /** Override the Bearer token (defaults to session access token). */
  dsai_accessToken?: string;
  /** Override the tenant ID header (defaults to session tenant). */
  dsai_tenantId?: string;
}

/**
 * dsai_buildHeaders — constructs the complete HTTP header map for a backend request.
 *
 * Injects:
 *   Authorization: Bearer <accessToken>
 *   X-Tenant-ID: <tenantId>
 *   Content-Type: application/json  (unless overridden in dsai_extraHeaders)
 */
export function dsai_buildHeaders(
  dsai_accessToken: string,
  dsai_tenantId: string,
  dsai_extraHeaders?: HeadersInit
): Headers {
  const dsai_headers = new Headers({
    "Content-Type": "application/json",
    Authorization: `Bearer ${dsai_accessToken}`,
    "X-Tenant-ID": dsai_tenantId,
  });

  if (dsai_extraHeaders) {
    const dsai_extra = new Headers(dsai_extraHeaders);
    dsai_extra.forEach((dsai_value, dsai_key) => {
      dsai_headers.set(dsai_key, dsai_value);
    });
  }

  return dsai_headers;
}

/**
 * dsai_handleUnauthorized — fires the session-expired DOM event and triggers
 * NextAuth signOut, redirecting the user to /login.
 *
 * Called automatically whenever the API client receives a 401 response.
 * Does NOT throw — callers should treat the returned undefined as a signal to stop.
 */
function dsai_handleUnauthorized(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(DSAI_SESSION_EXPIRED_EVENT));
  }
  // Graceful sign-out: clears the NextAuth session cookie and redirects to login
  signOut({ callbackUrl: "/login" });
}

/**
 * dsai_apiFetch — the centralized fetch wrapper for all Trinetra backend calls.
 *
 * Routes requests through the same-origin Next.js reverse proxy (/api/backend/*)
 * to avoid CORS preflight errors on FastAPI microservices.
 *
 * Behaviour:
 *   - Attaches Authorization: Bearer + X-Tenant-ID headers automatically.
 *   - On HTTP 401: fires session-expired event, calls signOut, returns undefined.
 *   - On other non-2xx: throws DsaiApiError with status + body.
 *   - On success: returns parsed JSON of type T.
 *
 * @param dsai_path         - Relative path under /api/backend/ (e.g. "auth/users/me")
 * @param dsai_accessToken  - JWT access token from useSession() / getServerSession()
 * @param dsai_tenantId     - Tenant identifier from session
 * @param dsai_options      - Optional additional fetch options (method, body, etc.)
 * @returns Parsed response JSON, or undefined if session has expired.
 */
export async function dsai_apiFetch<T = unknown>(
  dsai_path: string,
  dsai_accessToken: string,
  dsai_tenantId: string,
  dsai_options: DsaiRequestOptions = {}
): Promise<T | undefined> {
  const { dsai_accessToken: dsai_tokenOverride, dsai_tenantId: dsai_tenantOverride, ...dsai_fetchOptions } = dsai_options;

  const dsai_effectiveToken = dsai_tokenOverride ?? dsai_accessToken;
  const dsai_effectiveTenantId = dsai_tenantOverride ?? dsai_tenantId;

  const dsai_headers = dsai_buildHeaders(
    dsai_effectiveToken,
    dsai_effectiveTenantId,
    dsai_fetchOptions.headers
  );

  // All browser calls go through the Next.js same-origin reverse proxy to avoid CORS.
  // The /api/backend/<service>/<path> rewrite rules in next.config.js forward them.
  const dsai_proxyBase = "/api/backend";
  const dsai_url = `${dsai_proxyBase}/${dsai_path}`;

  const dsai_response = await fetch(dsai_url, {
    ...dsai_fetchOptions,
    headers: dsai_headers,
  });

  // 401 → session has expired. Trigger expiry flow and return undefined.
  if (dsai_response.status === 401) {
    dsai_handleUnauthorized();
    return undefined;
  }

  // Other non-2xx responses → throw typed error for caller to handle.
  if (!dsai_response.ok) {
    const dsai_errorText = await dsai_response.text().catch(() => "");
    throw new DsaiApiError(
      dsai_response.status,
      dsai_response.statusText,
      dsai_errorText || undefined
    );
  }

  // No-content responses
  if (dsai_response.status === 204) {
    return undefined;
  }

  return dsai_response.json() as Promise<T>;
}

/**
 * dsai_apiGet — convenience wrapper for GET requests.
 */
export async function dsai_apiGet<T = unknown>(
  dsai_path: string,
  dsai_accessToken: string,
  dsai_tenantId: string,
  dsai_options?: DsaiRequestOptions
): Promise<T | undefined> {
  return dsai_apiFetch<T>(dsai_path, dsai_accessToken, dsai_tenantId, {
    ...dsai_options,
    method: "GET",
  });
}

/**
 * dsai_apiPost — convenience wrapper for POST requests with a JSON body.
 */
export async function dsai_apiPost<T = unknown>(
  dsai_path: string,
  dsai_accessToken: string,
  dsai_tenantId: string,
  dsai_body: unknown,
  dsai_options?: DsaiRequestOptions
): Promise<T | undefined> {
  return dsai_apiFetch<T>(dsai_path, dsai_accessToken, dsai_tenantId, {
    ...dsai_options,
    method: "POST",
    body: JSON.stringify(dsai_body),
  });
}

/**
 * dsai_apiPut — convenience wrapper for PUT requests with a JSON body.
 */
export async function dsai_apiPut<T = unknown>(
  dsai_path: string,
  dsai_accessToken: string,
  dsai_tenantId: string,
  dsai_body: unknown,
  dsai_options?: DsaiRequestOptions
): Promise<T | undefined> {
  return dsai_apiFetch<T>(dsai_path, dsai_accessToken, dsai_tenantId, {
    ...dsai_options,
    method: "PUT",
    body: JSON.stringify(dsai_body),
  });
}

/**
 * dsai_apiPatch — convenience wrapper for PATCH requests with a JSON body.
 */
export async function dsai_apiPatch<T = unknown>(
  dsai_path: string,
  dsai_accessToken: string,
  dsai_tenantId: string,
  dsai_body: unknown,
  dsai_options?: DsaiRequestOptions
): Promise<T | undefined> {
  return dsai_apiFetch<T>(dsai_path, dsai_accessToken, dsai_tenantId, {
    ...dsai_options,
    method: "PATCH",
    body: JSON.stringify(dsai_body),
  });
}

/**
 * dsai_apiDelete — convenience wrapper for DELETE requests.
 */
export async function dsai_apiDelete<T = unknown>(
  dsai_path: string,
  dsai_accessToken: string,
  dsai_tenantId: string,
  dsai_options?: DsaiRequestOptions
): Promise<T | undefined> {
  return dsai_apiFetch<T>(dsai_path, dsai_accessToken, dsai_tenantId, {
    ...dsai_options,
    method: "DELETE",
  });
}
