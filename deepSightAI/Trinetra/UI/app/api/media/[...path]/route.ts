/**
 * MinIO Media Proxy Route — authenticated Next.js server-side image proxy.
 *
 * SearchService returns thumbnail URLs pointing to internal MinIO addresses
 * (e.g. http://minio:9000/...) that client browsers cannot resolve outside
 * the Docker/Kubernetes network (ERR_NAME_NOT_RESOLVED).
 *
 * This route fetches the image server-side from internal MinIO and streams
 * the bytes to the browser with caching headers.
 *
 * Access pattern:  GET /api/media/<bucket>/<object-key>
 * Example:         GET /api/media/frames/tenant-1/cam-1/2026-09-22/frame-001.jpg
 *
 * Phase 0 Decision 8: Next.js Media Proxy (ADR 0001 §8)
 * Issue: #29 — Text Semantic Search UI with MinIO Media Proxy Thumbnail Rendering
 */

import { type NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { dsai_authOptions } from "@/lib/auth/dsai_authOptions";
import { dsai_recordHttpRequest } from "@/lib/metrics";
import { dsai_logger } from "@/lib/logger";

/** Base URL of the internal MinIO service (Docker/K8s internal DNS) */
const DSAI_MINIO_INTERNAL_URL =
  process.env.MINIO_INTERNAL_URL ?? "http://minio:9000";

/**
 * GET /api/media/[...path]
 *
 * Fetches a MinIO object server-side and proxies it to the browser.
 * Requires a valid NextAuth session for access control.
 */
export async function GET(
  dsai_request: NextRequest,
  { params }: { params: { path: string[] } }
): Promise<NextResponse> {
  const dsai_startTime = Date.now();

  // Auth gate — reject unauthenticated requests
  const dsai_session = await getServerSession(dsai_authOptions);
  if (!dsai_session) {
    dsai_recordHttpRequest("GET", "/api/media/[...path]", 401, (Date.now() - dsai_startTime) / 1000);
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  // Reconstruct the MinIO object key from path segments
  const dsai_objectPath = params.path.join("/");
  if (!dsai_objectPath) {
    dsai_recordHttpRequest("GET", "/api/media/[...path]", 400, (Date.now() - dsai_startTime) / 1000);
    return NextResponse.json({ error: "Missing object path" }, { status: 400 });
  }

  const dsai_minioUrl = `${DSAI_MINIO_INTERNAL_URL}/${dsai_objectPath}`;

  try {
    const dsai_upstreamResponse = await fetch(dsai_minioUrl, {
      // Pass through Range header if present (supports partial content / video)
      headers: dsai_request.headers.get("Range")
        ? { Range: dsai_request.headers.get("Range")! }
        : {},
    });

    const dsai_durationSec = (Date.now() - dsai_startTime) / 1000;
    dsai_recordHttpRequest("GET", "/api/media/[...path]", dsai_upstreamResponse.status, dsai_durationSec);

    if (!dsai_upstreamResponse.ok) {
      dsai_logger.warn("MinIO upstream error", {
        route: "/api/media/[...path]",
        status: dsai_upstreamResponse.status,
        latency_ms: Date.now() - dsai_startTime,
      });
      return NextResponse.json(
        { error: `MinIO returned ${dsai_upstreamResponse.status}` },
        { status: dsai_upstreamResponse.status }
      );
    }

    // Determine content type from upstream or fall back to JPEG
    const dsai_contentType =
      dsai_upstreamResponse.headers.get("content-type") ?? "image/jpeg";

    const dsai_responseHeaders = new Headers({
      "Content-Type": dsai_contentType,
      // Private caching: browser may cache for 24 hours, CDN must not cache
      "Cache-Control": "private, max-age=86400",
    });

    // Propagate Content-Length if available
    const dsai_contentLength = dsai_upstreamResponse.headers.get("content-length");
    if (dsai_contentLength) {
      dsai_responseHeaders.set("Content-Length", dsai_contentLength);
    }

    return new NextResponse(dsai_upstreamResponse.body, {
      status: dsai_upstreamResponse.status,
      headers: dsai_responseHeaders,
    });
  } catch (dsai_err) {
    const dsai_durationSec = (Date.now() - dsai_startTime) / 1000;
    dsai_recordHttpRequest("GET", "/api/media/[...path]", 502, dsai_durationSec);
    dsai_logger.error("Failed to fetch media from internal storage", {
      route: "/api/media/[...path]",
      status: 502,
      error: dsai_err instanceof Error ? dsai_err : String(dsai_err),
    });
    return NextResponse.json(
      { error: "Failed to fetch media from internal storage" },
      { status: 502 }
    );
  }
}
