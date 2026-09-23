import { NextResponse } from "next/server";
import { dsai_recordHttpRequest } from "@/lib/metrics";
import { dsai_logger } from "@/lib/logger";

export const dynamic = "force-dynamic";

/**
 * GET /api/health
 * Liveness probe for Kubernetes & Docker: validates Node.js process is active.
 */
export async function GET() {
  const dsai_startTime = Date.now();
  const dsai_durationSec = (Date.now() - dsai_startTime) / 1000;
  dsai_recordHttpRequest("GET", "/api/health", 200, dsai_durationSec);
  dsai_logger.debug("Liveness probe OK", { route: "/api/health", status: 200 });

  return NextResponse.json(
    {
      status: "ok",
      service: "trinetra-ui",
      timestamp: new Date().toISOString(),
      uptime: process.uptime(),
    },
    { status: 200 }
  );
}
