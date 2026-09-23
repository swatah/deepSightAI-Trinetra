import {
  dsai_register,
  dsai_normalizeRoute,
  dsai_recordHttpRequest,
  dsai_recordSearchLatency,
  dsai_recordUploadBytes,
  dsai_incrementActiveSse,
  dsai_decrementActiveSse,
} from "../../lib/metrics";

describe("Prometheus Metrics Service (REL-64 / #43)", () => {
  it("normalizes dynamic routes to avoid cardinality explosion", () => {
    expect(dsai_normalizeRoute("/api/media/frames/tenant-1/camera-2/image.jpg")).toBe("/api/media/[...path]");
    expect(dsai_normalizeRoute("/api/alerts/12345/acknowledge")).toBe("/api/alerts/[id]/acknowledge");
    expect(dsai_normalizeRoute("/api/search/text?q=suspicious")).toBe("/api/search/text");
    expect(dsai_normalizeRoute("/tenants/550e8400-e29b-41d4-a716-446655440000")).toBe("/tenants/[id]");
  });

  it("registers core metrics with trinetra_ui_ prefix", async () => {
    dsai_recordHttpRequest("GET", "/api/cameras", 200, 0.12);
    dsai_recordSearchLatency("vehicle", 0.35);
    dsai_recordUploadBytes("tenant-alpha", 1048576);
    dsai_incrementActiveSse();

    const dsai_metrics_output = await dsai_register.metrics();

    expect(dsai_metrics_output).toContain("trinetra_ui_http_requests_total");
    expect(dsai_metrics_output).toContain("trinetra_ui_http_request_duration_seconds");
    expect(dsai_metrics_output).toContain("trinetra_ui_search_latency_seconds");
    expect(dsai_metrics_output).toContain("trinetra_ui_upload_bytes_total");
    expect(dsai_metrics_output).toContain("trinetra_ui_active_sse_connections");

    dsai_decrementActiveSse();
  });
});
