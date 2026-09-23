import { getToken } from "next-auth/jwt";
import { NextRequest, NextResponse } from "next/server";
import { dsai_logger } from "@/lib/logger";

/**
 * dsai_PROTECTED_PATHS — route prefixes that require an authenticated session.
 * Requests to these paths are intercepted and redirected to /login if unauthenticated.
 */
const DSAI_PROTECTED_PATHS = [
  "/search",
  "/watchlist",
  "/alerts",
  "/upload",
  "/ingest",
  "/rtsp",
  "/analytics",
  "/admin",
  "/dashboard",
];

/**
 * dsai_ADMIN_PATHS — subset of protected paths that also require the "admin" role.
 * Authenticated non-admin users receive a 403 response when accessing these routes.
 */
const DSAI_ADMIN_PATHS = ["/admin"];

/**
 * dsai_isProtectedPath — returns true if the given pathname starts with any
 * of the protected route prefixes.
 */
function dsai_isProtectedPath(dsai_pathname: string): boolean {
  return DSAI_PROTECTED_PATHS.some((dsai_prefix) =>
    dsai_pathname.startsWith(dsai_prefix)
  );
}

/**
 * dsai_isAdminPath — returns true if the given pathname falls under an admin-only route.
 */
function dsai_isAdminPath(dsai_pathname: string): boolean {
  return DSAI_ADMIN_PATHS.some((dsai_prefix) =>
    dsai_pathname.startsWith(dsai_prefix)
  );
}

/**
 * Next.js Edge Middleware for route protection and request logging.
 *
 * Behaviour:
 * 1. Public paths (/login, /api/auth/*, /api/health, /api/ready, /_next/*, static assets)
 *    pass through without authentication checks.
 * 2. Protected paths: if the NextAuth JWT token is absent → redirect to
 *    /login?callbackUrl=<requested_path>.
 * 3. Admin paths: if the JWT token does not contain "admin" in roles →
 *    respond with 403 Forbidden page.
 */
export async function middleware(dsai_request: NextRequest) {
  const dsai_pathname = dsai_request.nextUrl.pathname;

  const dsai_requestId = dsai_request.headers.get("x-request-id") || crypto.randomUUID();
  const dsai_requestHeaders = new Headers(dsai_request.headers);
  dsai_requestHeaders.set("x-request-id", dsai_requestId);

  // Structured logging for every intercepted request
  dsai_logger.info("Incoming HTTP request", {
    route: dsai_pathname,
    method: dsai_request.method,
    request_id: dsai_requestId,
  });

  // Only intercept protected routes — all others pass through immediately.
  if (!dsai_isProtectedPath(dsai_pathname)) {
    const dsai_res = NextResponse.next({
      request: {
        headers: dsai_requestHeaders,
      },
    });
    dsai_res.headers.set("x-request-id", dsai_requestId);
    return dsai_res;
  }

  // Retrieve the NextAuth JWT from the request cookies.
  const dsai_token = await getToken({
    req: dsai_request,
    secret: process.env.NEXTAUTH_SECRET,
  });

  // Not authenticated — redirect to login with callbackUrl.
  if (!dsai_token) {
    dsai_logger.warn("Unauthenticated request redirected to login", {
      route: dsai_pathname,
      request_id: dsai_requestId,
    });
    const dsai_loginUrl = new URL("/login", dsai_request.url);
    dsai_loginUrl.searchParams.set("callbackUrl", dsai_pathname);
    return NextResponse.redirect(dsai_loginUrl);
  }

  // Authenticated but accessing an admin-only route without admin role.
  if (dsai_isAdminPath(dsai_pathname)) {
    const dsai_roles = dsai_token.dsai_roles as string[] | undefined;
    const dsai_isAdmin = Array.isArray(dsai_roles) && dsai_roles.includes("admin");

    if (!dsai_isAdmin) {
      dsai_logger.warn("Forbidden admin access attempt", {
        route: dsai_pathname,
        request_id: dsai_requestId,
        roles: dsai_roles,
      });
      // Return 403 response
      const dsai_forbiddenRes = new NextResponse(
        JSON.stringify({
          dsai_error: "Forbidden",
          dsai_message:
            "You do not have the required role to access this resource.",
        }),
        {
          status: 403,
          headers: {
            "Content-Type": "application/json",
            "x-request-id": dsai_requestId,
          },
        }
      );
      return dsai_forbiddenRes;
    }
  }

  // Authenticated and authorised — allow the request.
  const dsai_authRes = NextResponse.next({
    request: {
      headers: dsai_requestHeaders,
    },
  });
  dsai_authRes.headers.set("x-request-id", dsai_requestId);
  return dsai_authRes;
}

/**
 * Matcher config — only run this middleware on routes that could be protected.
 * Explicitly excludes:
 *   - /login and /api/auth/* (NextAuth itself)
 *   - /api/health and /api/ready (health probes — must never redirect)
 *   - /_next/* (Next.js internals)
 *   - /favicon.ico and static assets
 *
 * Using a negative-lookahead pattern so static assets are never intercepted.
 */
export const config = {
  matcher: [
    /*
     * Match all request paths EXCEPT the ones starting with:
     * - /login
     * - /api/auth (NextAuth API routes)
     * - /api/health
     * - /api/ready
     * - /_next (Next.js internals: JS chunks, CSS, etc.)
     * - /favicon.ico, /robots.txt, public folder static files
     */
    "/((?!login|api/auth|api/health|api/ready|_next|favicon\\.ico|robots\\.txt|.*\\.(?:png|jpg|jpeg|gif|svg|ico|webp|css|js|woff2?|ttf|eot)).*)",
  ],
};
