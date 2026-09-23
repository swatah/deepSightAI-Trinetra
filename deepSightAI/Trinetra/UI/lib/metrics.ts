import client from "prom-client";

// Use global singleton registry to avoid re-registration in Next.js dev HMR
const dsai_global = globalThis as unknown as {
  dsai_prometheus_registry?: client.Registry;
  dsai_http_requests_total?: client.Counter<"method" | "route" | "status_code">;
  dsai_http_request_duration_seconds?: client.Histogram<"route" | "status_code">;
  dsai_search_latency_seconds?: client.Histogram<"search_mode">;
  dsai_upload_bytes_total?: client.Counter<"tenant_id">;
  dsai_active_sse_connections?: client.Gauge<string>;
};

export const dsai_register = dsai_global.dsai_prometheus_registry || new client.Registry();
dsai_global.dsai_prometheus_registry = dsai_register;

// Collect standard default metrics (memory, event loop, etc.)
if (!dsai_global.dsai_http_requests_total) {
  client.collectDefaultMetrics({ register: dsai_register, prefix: "trinetra_ui_" });
}

export const trinetra_ui_http_requests_total =
  dsai_global.dsai_http_requests_total ||
  new client.Counter({
    name: "trinetra_ui_http_requests_total",
    help: "Total HTTP requests handled by the UI service",
    labelNames: ["method", "route", "status_code"],
    registers: [dsai_register],
  });
dsai_global.dsai_http_requests_total = trinetra_ui_http_requests_total;

export const trinetra_ui_http_request_duration_seconds =
  dsai_global.dsai_http_request_duration_seconds ||
  new client.Histogram({
    name: "trinetra_ui_http_request_duration_seconds",
    help: "HTTP request latency in seconds",
    labelNames: ["route", "status_code"],
    buckets: [0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
    registers: [dsai_register],
  });
dsai_global.dsai_http_request_duration_seconds = trinetra_ui_http_request_duration_seconds;

export const trinetra_ui_search_latency_seconds =
  dsai_global.dsai_search_latency_seconds ||
  new client.Histogram({
    name: "trinetra_ui_search_latency_seconds",
    help: "Multi-modal visual search query latency in seconds",
    labelNames: ["search_mode"],
    buckets: [0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
    registers: [dsai_register],
  });
dsai_global.dsai_search_latency_seconds = trinetra_ui_search_latency_seconds;

export const trinetra_ui_upload_bytes_total =
  dsai_global.dsai_upload_bytes_total ||
  new client.Counter({
    name: "trinetra_ui_upload_bytes_total",
    help: "Total bytes of video assets uploaded per tenant",
    labelNames: ["tenant_id"],
    registers: [dsai_register],
  });
dsai_global.dsai_upload_bytes_total = trinetra_ui_upload_bytes_total;

export const trinetra_ui_active_sse_connections =
  dsai_global.dsai_active_sse_connections ||
  new client.Gauge({
    name: "trinetra_ui_active_sse_connections",
    help: "Number of active Server-Sent Events (SSE) connections for live alerts",
    registers: [dsai_register],
  });
dsai_global.dsai_active_sse_connections = trinetra_ui_active_sse_connections;

/**
 * Normalizes dynamic paths to prevent Prometheus high-cardinality explosions.
 */
export function dsai_normalizeRoute(dsai_path: string): string {
  if (!dsai_path) return "/";
  // Strip query string
  const dsai_clean_path = dsai_path.split("?")[0];

  // Specific dynamic routes in Trinetra UI
  if (dsai_clean_path.startsWith("/api/media/")) {
    return "/api/media/[...path]";
  }
  if (dsai_clean_path.startsWith("/api/alerts/") && dsai_clean_path.endsWith("/acknowledge")) {
    return "/api/alerts/[id]/acknowledge";
  }
  if (dsai_clean_path.startsWith("/tenants/") && dsai_clean_path.split("/").length === 3) {
    return "/tenants/[id]";
  }

  // Replace standard UUIDs or Mongo ObjectIDs or long hashes
  return dsai_clean_path
    .replace(/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g, "[id]")
    .replace(/\/\d+(?=\/|$)/g, "/[id]");
}

/**
 * Record an HTTP request event and duration.
 */
export function dsai_recordHttpRequest(
  dsai_method: string,
  dsai_raw_route: string,
  dsai_status_code: number,
  dsai_duration_seconds: number
): void {
  const dsai_route = dsai_normalizeRoute(dsai_raw_route);
  const dsai_status_str = String(dsai_status_code);
  trinetra_ui_http_requests_total.labels(dsai_method, dsai_route, dsai_status_str).inc();
  trinetra_ui_http_request_duration_seconds.labels(dsai_route, dsai_status_str).observe(dsai_duration_seconds);
}

/**
 * Record visual search query latency.
 */
export function dsai_recordSearchLatency(
  dsai_search_mode: "text" | "vehicle" | "person" | "plate" | "image",
  dsai_duration_seconds: number
): void {
  trinetra_ui_search_latency_seconds.labels(dsai_search_mode).observe(dsai_duration_seconds);
}

/**
 * Record uploaded video bytes by tenant.
 */
export function dsai_recordUploadBytes(dsai_tenant_id: string, dsai_bytes: number): void {
  trinetra_ui_upload_bytes_total.labels(dsai_tenant_id).inc(dsai_bytes);
}

/**
 * Active SSE gauge helpers.
 */
export function dsai_incrementActiveSse(): void {
  trinetra_ui_active_sse_connections.inc();
}

export function dsai_decrementActiveSse(): void {
  trinetra_ui_active_sse_connections.dec();
}
