import { dsai_parseSseChunk, dsai_connectSse, DsaiSseEvent } from "../../lib/streaming/sseClient";

describe("Native Web Streams SSE Parser Suite (#46)", () => {
  it("parses single SSE event with id, event, and data fields", () => {
    const rawChunk = "id: 101\nevent: alert\ndata: {\"rule\":\"weapon_detected\",\"confidence\":0.94}\n\n";
    const events: DsaiSseEvent[] = dsai_parseSseChunk(rawChunk);

    expect(events).toHaveLength(1);
    expect(events[0].dsai_id).toBe("101");
    expect(events[0].dsai_event).toBe("alert");
    expect(events[0].dsai_data).toBe("{\"rule\":\"weapon_detected\",\"confidence\":0.94}");
  });

  it("parses multiple consecutive SSE events separated by double newlines", () => {
    const rawChunk =
      "id: 1\nevent: ping\ndata: pong\n\n" +
      "id: 2\nevent: detection\ndata: {\"plate\":\"ABC1234\"}\n\n";
    const events = dsai_parseSseChunk(rawChunk);

    expect(events).toHaveLength(2);
    expect(events[0].dsai_id).toBe("1");
    expect(events[0].dsai_event).toBe("ping");
    expect(events[1].dsai_id).toBe("2");
    expect(events[1].dsai_event).toBe("detection");
  });

  it("handles multi-line data payloads cleanly", () => {
    const rawChunk = "data: line 1\ndata: line 2\ndata: line 3\n\n";
    const events = dsai_parseSseChunk(rawChunk);

    expect(events).toHaveLength(1);
    expect(events[0].dsai_data).toBe("line 1\nline 2\nline 3");
  });

  it("gracefully handles empty, whitespace, and malformed chunks without crashing", () => {
    expect(dsai_parseSseChunk("")).toEqual([]);
    expect(dsai_parseSseChunk("\n\n\n")).toEqual([]);
    expect(dsai_parseSseChunk(": comment line only\n\n")).toEqual([]);
  });

  it("connects to stream, receives events, and disconnects cleanly", async () => {
    const mockEvents: DsaiSseEvent[] = [];
    const encoder = new TextEncoder();
    let streamController: ReadableStreamDefaultController | null = null;

    const stream = new ReadableStream({
      start(controller) {
        streamController = controller;
        controller.enqueue(encoder.encode("id: 99\nevent: alert\ndata: test-alert\n\n"));
      },
    });

    const originalFetch = global.fetch;
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      body: stream,
    });

    const ctl = dsai_connectSse(
      "/api/backend/watchlist/alerts/stream",
      { Authorization: "Bearer token" },
      (ev) => mockEvents.push(ev)
    );

    // Wait for connection to establish and event to arrive
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(ctl.dsai_isConnected()).toBe(true);
    expect(mockEvents).toHaveLength(1);
    expect(mockEvents[0].dsai_id).toBe("99");

    ctl.dsai_disconnect();
    expect(ctl.dsai_isConnected()).toBe(false);

    try {
      streamController?.close();
    } catch {}

    global.fetch = originalFetch;
  });

  it("handles network error and triggers onError callback", async () => {
    const originalFetch = global.fetch;
    global.fetch = jest.fn().mockRejectedValue(new Error("Network drop"));
    const onError = jest.fn();

    const ctl = dsai_connectSse(
      "/api/backend/watchlist/alerts/stream",
      {},
      () => {},
      onError
    );

    await new Promise((resolve) => setTimeout(resolve, 50));
    ctl.dsai_disconnect();

    expect(onError).toHaveBeenCalled();
    global.fetch = originalFetch;
  });
});
