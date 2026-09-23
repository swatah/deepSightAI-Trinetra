import { StructuredLogger, dsai_logger } from "../../lib/logger";

describe("Structured JSON Logger Suite (#45 / #46)", () => {
  let logSpy: jest.SpyInstance;
  let warnSpy: jest.SpyInstance;
  let errorSpy: jest.SpyInstance;

  beforeEach(() => {
    logSpy = jest.spyOn(console, "log").mockImplementation(() => {});
    warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    logSpy.mockRestore();
    warnSpy.mockRestore();
    errorSpy.mockRestore();
  });

  it("formats single-line JSON log with platform schema", () => {
    const logger = new StructuredLogger("trinetra-ui");
    const jsonStr = logger.format("info", "Video ingestion started", {
      tenant_id: "police-dept-1",
      request_id: "req-xyz-123",
      route: "/upload",
      method: "POST",
      status: 200,
      latency_ms: 85.2,
    });

    const parsed = JSON.parse(jsonStr);
    expect(parsed.service).toBe("trinetra-ui");
    expect(parsed.level).toBe("INFO");
    expect(parsed.message).toBe("Video ingestion started");
    expect(parsed.tenant_id).toBe("police-dept-1");
    expect(parsed.request_id).toBe("req-xyz-123");
    expect(parsed.route).toBe("/upload");
    expect(parsed.method).toBe("POST");
    expect(parsed.status).toBe(200);
    expect(parsed.latency_ms).toBe(85.2);
    expect(parsed.timestamp).toBeDefined();
  });

  it("emits logs at appropriate levels and respects hierarchy", () => {
    const logger = new StructuredLogger("trinetra-ui");
    logger.debug("Debug msg");
    logger.info("Info msg");
    logger.warn("Warn msg");
    logger.error("Error msg", { error: new Error("DB connection timeout") });

    expect(warnSpy).toHaveBeenCalled();
    expect(errorSpy).toHaveBeenCalled();
  });

  it("creates scoped child logger inheriting default context", () => {
    const rootLogger = new StructuredLogger("trinetra-ui");
    const childLogger = rootLogger.child({ tenant_id: "tenant-beta", request_id: "req-456" });

    const jsonStr = childLogger.format("warn", "High memory detected");
    const parsed = JSON.parse(jsonStr);

    expect(parsed.tenant_id).toBe("tenant-beta");
    expect(parsed.request_id).toBe("req-456");
    expect(parsed.level).toBe("WARN");
  });

  it("provides singleton dsai_logger", () => {
    expect(dsai_logger).toBeDefined();
  });
});
