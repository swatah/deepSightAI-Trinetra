import { NextResponse } from "next/server";
import { dsai_register } from "@/lib/metrics";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const dsai_metrics = await dsai_register.metrics();
    return new NextResponse(dsai_metrics, {
      status: 200,
      headers: {
        "Content-Type": dsai_register.contentType,
        "Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate",
      },
    });
  } catch (dsai_error: unknown) {
    const dsai_err_msg = dsai_error instanceof Error ? dsai_error.message : "Failed to generate metrics";
    return new NextResponse(dsai_err_msg, {
      status: 500,
      headers: { "Content-Type": "text/plain" },
    });
  }
}
