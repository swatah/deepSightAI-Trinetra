import { NextResponse } from "next/server";
import * as Sentry from "@sentry/nextjs";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const dsai_tenant_id = request.headers.get("x-tenant-id") || searchParams.get("tenant_id") || "test-tenant-1";

  try {
    throw new Error("Trinetra Sentry integration test error from /api/debug/sentry-test");
  } catch (dsai_error: unknown) {
    const dsai_eventId = Sentry.captureException(dsai_error, {
      tags: {
        tenant_id: dsai_tenant_id,
        test_route: "/api/debug/sentry-test",
      },
      extra: {
        timestamp: new Date().toISOString(),
      },
    });

    return NextResponse.json({
      status: "error_captured",
      message: "Test error successfully dispatched to Sentry",
      tenant_id: dsai_tenant_id,
      event_id: dsai_eventId,
    });
  }
}
