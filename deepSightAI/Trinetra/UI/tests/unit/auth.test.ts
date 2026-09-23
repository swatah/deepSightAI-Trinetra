import {
  dsai_buildHeaders,
  dsai_apiFetch,
  DsaiApiError,
  DSAI_SESSION_EXPIRED_EVENT,
} from "../../lib/api/dsai_client";

// Mock next-auth/react signOut
jest.mock("next-auth/react", () => ({
  signOut: jest.fn(),
}));

describe("Auth & API Client Suite (#46)", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.clearAllMocks();
  });

  it("builds correct headers with Bearer token, X-Tenant-ID, and Content-Type", () => {
    const dsai_headers = dsai_buildHeaders("mock_jwt_token_123", "tenant_xyz");

    expect(dsai_headers.get("Authorization")).toBe("Bearer mock_jwt_token_123");
    expect(dsai_headers.get("X-Tenant-ID")).toBe("tenant_xyz");
    expect(dsai_headers.get("Content-Type")).toBe("application/json");
  });

  it("allows overriding and extending headers", () => {
    const dsai_headers = dsai_buildHeaders("token_abc", "tenant_1", {
      "X-Custom-Trace": "trace_999",
      "Content-Type": "application/octet-stream",
    });

    expect(dsai_headers.get("Authorization")).toBe("Bearer token_abc");
    expect(dsai_headers.get("X-Tenant-ID")).toBe("tenant_1");
    expect(dsai_headers.get("X-Custom-Trace")).toBe("trace_999");
    expect(dsai_headers.get("Content-Type")).toBe("application/octet-stream");
  });

  it("constructs DsaiApiError with status and text", () => {
    const dsai_err = new DsaiApiError(404, "Not Found", "Camera stream not located");
    expect(dsai_err.dsai_status).toBe(404);
    expect(dsai_err.dsai_statusText).toBe("Not Found");
    expect(dsai_err.message).toBe("Camera stream not located");
    expect(dsai_err.name).toBe("DsaiApiError");
  });

  it("executes successful dsai_apiFetch call and parses JSON", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ results: [{ id: "cam-1" }] }),
    });

    const data = await dsai_apiFetch("/cameras", "test-token", "tenant-1");
    expect(data).toEqual({ results: [{ id: "cam-1" }] });
  });

  it("intercepts HTTP 401, dispatches session-expired event, and triggers signOut", async () => {
    const eventSpy = jest.fn();
    window.addEventListener(DSAI_SESSION_EXPIRED_EVENT, eventSpy);

    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
    });

    const res = await dsai_apiFetch("/cameras", "expired-token", "tenant-1");
    expect(res).toBeUndefined();
    expect(eventSpy).toHaveBeenCalled();

    window.removeEventListener(DSAI_SESSION_EXPIRED_EVENT, eventSpy);
  });

  it("throws DsaiApiError on non-401 failure status", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      text: async () => "Internal database failure",
    });

    await expect(dsai_apiFetch("/cameras", "tok", "tenant-1")).rejects.toThrow(DsaiApiError);
  });
});
