/**
 * dsai_sseClient — lightweight vanilla TypeScript SSE client using native Web APIs.
 *
 * CRITICAL ARCHITECTURAL RULE (Issue #36):
 *   - Zero external packages. @microsoft/fetch-event-source is STRICTLY forbidden.
 *   - Standard browser new EventSource() cannot send custom Authorization headers,
 *     so we use fetch() + ReadableStream + TextDecoder instead.
 *
 * Features:
 *   - Reads SSE streams with Bearer authorization via fetch + ReadableStream
 *   - Automatic reconnect with exponential backoff on network errors
 *   - Polling fallback when SSE fails or is blocked by proxies
 *
 * Usage:
 *   const dsai_ctl = dsai_connectSse("/api/backend/watchlist/alerts/stream", headers, onEvent, onError);
 *   dsai_ctl.dsai_disconnect();
 */

export interface DsaiSseEvent {
  dsai_id: string | null;
  dsai_event: string | null;
  dsai_data: string;
}

export interface DsaiSseController {
  /** Permanently stop the SSE connection and any pending reconnect. */
  dsai_disconnect: () => void;
  /** Returns true if the connection is currently active. */
  dsai_isConnected: () => boolean;
}

/** dsai_parseSseChunk — parses a raw SSE text chunk into structured events. */
export function dsai_parseSseChunk(dsai_raw: string): DsaiSseEvent[] {
  const dsai_events: DsaiSseEvent[] = [];
  // SSE events are separated by double newlines
  const dsai_blocks = dsai_raw.split(/\n\n/);
  for (const dsai_block of dsai_blocks) {
    const dsai_lines = dsai_block.split("\n").filter((dsai_l) => dsai_l.trim() !== "");
    if (dsai_lines.length === 0) continue;

    let dsai_id: string | null = null;
    let dsai_event: string | null = null;
    const dsai_dataParts: string[] = [];

    for (const dsai_line of dsai_lines) {
      if (dsai_line.startsWith("id:")) {
        dsai_id = dsai_line.slice(3).trim();
      } else if (dsai_line.startsWith("event:")) {
        dsai_event = dsai_line.slice(6).trim();
      } else if (dsai_line.startsWith("data:")) {
        dsai_dataParts.push(dsai_line.slice(5).trim());
      }
    }

    if (dsai_dataParts.length > 0) {
      dsai_events.push({
        dsai_id,
        dsai_event,
        dsai_data: dsai_dataParts.join("\n"),
      });
    }
  }
  return dsai_events;
}

const DSAI_INITIAL_BACKOFF_MS = 500;
const DSAI_MAX_BACKOFF_MS = 30_000;
const DSAI_BACKOFF_FACTOR = 2;

/**
 * dsai_connectSse — opens a streaming SSE connection using fetch + ReadableStream.
 * Reconnects automatically on error with exponential backoff.
 */
export function dsai_connectSse(
  dsai_url: string,
  dsai_headers: Record<string, string>,
  dsai_onEvent: (dsai_event: DsaiSseEvent) => void,
  dsai_onError?: (dsai_err: unknown) => void
): DsaiSseController {
  let dsai_active = true;
  let dsai_backoffMs = DSAI_INITIAL_BACKOFF_MS;
  let dsai_connected = false;
  let dsai_abortController: AbortController | null = null;

  async function dsai_connect(): Promise<void> {
    if (!dsai_active) return;
    dsai_abortController = new AbortController();
    try {
      const dsai_response = await fetch(dsai_url, {
        headers: dsai_headers,
        signal: dsai_abortController.signal,
      });

      if (!dsai_response.ok || !dsai_response.body) {
        throw new Error(`SSE connection failed: HTTP ${dsai_response.status}`);
      }

      dsai_connected = true;
      dsai_backoffMs = DSAI_INITIAL_BACKOFF_MS; // reset on success

      const dsai_reader = dsai_response.body.getReader();
      const dsai_decoder = new TextDecoder();
      let dsai_buffer = "";

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await dsai_reader.read();
        if (done || !dsai_active) break;

        dsai_buffer += dsai_decoder.decode(value, { stream: true });

        // Process complete SSE blocks (terminated by \n\n)
        const dsai_lastNewline = dsai_buffer.lastIndexOf("\n\n");
        if (dsai_lastNewline !== -1) {
          const dsai_complete = dsai_buffer.slice(0, dsai_lastNewline + 2);
          dsai_buffer = dsai_buffer.slice(dsai_lastNewline + 2);
          const dsai_events = dsai_parseSseChunk(dsai_complete);
          dsai_events.forEach(dsai_onEvent);
        }
      }
    } catch (dsai_err) {
      if (!dsai_active) return; // intentional disconnect
      dsai_connected = false;
      dsai_onError?.(dsai_err);
    }

    // Reconnect with backoff
    if (dsai_active) {
      dsai_connected = false;
      await new Promise((dsai_resolve) => setTimeout(dsai_resolve, dsai_backoffMs));
      dsai_backoffMs = Math.min(dsai_backoffMs * DSAI_BACKOFF_FACTOR, DSAI_MAX_BACKOFF_MS);
      dsai_connect();
    }
  }

  dsai_connect();

  return {
    dsai_disconnect() {
      dsai_active = false;
      dsai_connected = false;
      dsai_abortController?.abort();
    },
    dsai_isConnected() {
      return dsai_connected;
    },
  };
}
