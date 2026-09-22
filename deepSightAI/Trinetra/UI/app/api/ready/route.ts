import { NextResponse } from "next/server";

/**
 * GET /api/ready
 * Readiness probe — returns HTTP 200 when the Next.js server is ready to accept traffic.
 * Referenced by the Kubernetes readiness probe in k8s/base/ui/deployment.yaml.
 */
export async function GET() {
  return NextResponse.json(
    {
      dsai_status: "ready",
      dsai_service: "trinetra-ui",
    },
    { status: 200 }
  );
}
