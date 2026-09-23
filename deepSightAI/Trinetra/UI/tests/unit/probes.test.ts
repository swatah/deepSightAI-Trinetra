/**
 * @jest-environment node
 */
import { GET as getHealth } from "../../app/api/health/route";
import { GET as getReady } from "../../app/api/ready/route";

describe("Kubernetes Probes Suite (#55)", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.clearAllMocks();
  });

  it("liveness probe (/api/health) returns 200 OK immediately with uptime and timestamp", async () => {
    const response = await getHealth();
    expect(response.status).toBe(200);

    const body = await response.json();
    expect(body.status).toBe("ok");
    expect(body.service).toBe("trinetra-ui");
    expect(body.uptime).toBeGreaterThanOrEqual(0);
    expect(body.timestamp).toBeDefined();
  });

  it("readiness probe (/api/ready) returns 200 when all backends are healthy", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      status: 200,
    });

    const response = await getReady();
    expect(response.status).toBe(200);

    const body = await response.json();
    expect(body.status).toBe("ready");
    expect(body.backends.auth_service).toBe("ok");
    expect(body.backends.search_service).toBe("ok");
    expect(body.backends.watchlist_service).toBe("ok");
  });

  it("readiness probe (/api/ready) returns 503 Service Unavailable when a critical backend fails", async () => {
    global.fetch = jest.fn().mockImplementation((url: string) => {
      if (url.includes("8002")) {
        return Promise.reject(new Error("Connection refused"));
      }
      return Promise.resolve({ status: 200 });
    });

    const response = await getReady();
    expect(response.status).toBe(503);

    const body = await response.json();
    expect(body.status).toBe("degraded");
    expect(body.backends.auth_service).toBe("unreachable");
    expect(body.backends.search_service).toBe("ok");
  });
});
