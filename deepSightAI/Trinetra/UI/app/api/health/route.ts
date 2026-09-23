import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * GET /api/health
 * Liveness probe for Kubernetes & Docker: validates Node.js process is active.
 */
export async function GET() {
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
