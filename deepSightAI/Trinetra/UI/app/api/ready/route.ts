import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Checks connectivity to a backend service with a strict 2.0s timeout.
 */
async function dsai_checkService(dsai_baseUrl: string): Promise<{ status: "ok" | "unreachable"; url: string }> {
  const dsai_controller = new AbortController();
  const dsai_timer = setTimeout(() => dsai_controller.abort(), 2000);

  try {
    // Attempt /health probe endpoint; status < 500 confirms process is responding
    const dsai_res = await fetch(`${dsai_baseUrl}/health`, {
      signal: dsai_controller.signal,
      cache: "no-store",
    });
    return {
      status: dsai_res.status < 500 ? "ok" : "unreachable",
      url: dsai_baseUrl,
    };
  } catch {
    return {
      status: "unreachable",
      url: dsai_baseUrl,
    };
  } finally {
    clearTimeout(dsai_timer);
  }
}

/**
 * GET /api/ready
 * Readiness probe for Kubernetes: validates dependencies before admitting traffic.
 */
export async function GET() {
  const dsai_authUrl = process.env.AUTH_SERVICE_URL || "http://auth-service:8002";
  const dsai_searchUrl = process.env.SEARCH_SERVICE_URL || "http://search-service:8081";
  const dsai_watchlistUrl = process.env.WATCHLIST_SERVICE_URL || "http://watchlist-matcher:8083";

  // Check critical backends concurrently
  const [dsai_auth, dsai_search, dsai_watchlist] = await Promise.all([
    dsai_checkService(dsai_authUrl),
    dsai_checkService(dsai_searchUrl),
    dsai_checkService(dsai_watchlistUrl),
  ]);

  const dsai_allHealthy =
    dsai_auth.status === "ok" &&
    dsai_search.status === "ok" &&
    dsai_watchlist.status === "ok";

  const dsai_responseBody = {
    status: dsai_allHealthy ? "ready" : "degraded",
    service: "trinetra-ui",
    timestamp: new Date().toISOString(),
    backends: {
      auth_service: dsai_auth.status,
      search_service: dsai_search.status,
      watchlist_service: dsai_watchlist.status,
    },
  };

  return NextResponse.json(dsai_responseBody, {
    status: dsai_allHealthy ? 200 : 503,
  });
}
