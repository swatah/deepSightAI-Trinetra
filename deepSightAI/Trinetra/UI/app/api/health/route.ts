import { NextResponse } from "next/server";

/**
 * GET /api/health
 * Lightweight liveness probe used by docker-compose healthcheck.
 * Returns HTTP 200 with a JSON body so the container enters "healthy" state.
 */
export async function GET() {
  return NextResponse.json(
    {
      dsai_status: "ok",
      dsai_service: "trinetra-ui",
    },
    { status: 200 }
  );
}
