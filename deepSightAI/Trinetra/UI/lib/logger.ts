export type LogLevel = "debug" | "info" | "warn" | "error";

const DSAI_LEVEL_PRIORITY: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

export interface LogContext {
  tenant_id?: string;
  request_id?: string;
  route?: string;
  method?: string;
  status?: number;
  latency_ms?: number;
  error?: string | Error;
  [key: string]: unknown;
}

export interface StructuredLogPayload {
  timestamp: string;
  level: string;
  service: string;
  tenant_id?: string;
  request_id?: string;
  route?: string;
  method?: string;
  status?: number;
  latency_ms?: number;
  message: string;
  [key: string]: unknown;
}

export class StructuredLogger {
  private dsai_serviceName: string;
  private dsai_defaultContext: LogContext;

  constructor(dsai_serviceName = "trinetra-ui", dsai_defaultContext: LogContext = {}) {
    this.dsai_serviceName = dsai_serviceName;
    this.dsai_defaultContext = dsai_defaultContext;
  }

  private dsai_getActiveLogLevel(): LogLevel {
    const dsai_envLevel = (process.env.LOG_LEVEL || "info").toLowerCase() as LogLevel;
    return DSAI_LEVEL_PRIORITY[dsai_envLevel] !== undefined ? dsai_envLevel : "info";
  }

  private dsai_shouldLog(dsai_level: LogLevel): boolean {
    const dsai_active = this.dsai_getActiveLogLevel();
    return DSAI_LEVEL_PRIORITY[dsai_level] >= DSAI_LEVEL_PRIORITY[dsai_active];
  }

  public format(dsai_level: LogLevel, dsai_message: string, dsai_context?: LogContext): string {
    const dsai_merged: LogContext = { ...this.dsai_defaultContext, ...dsai_context };
    
    // Convert Error object if present
    let dsai_errorStr: string | undefined;
    if (dsai_merged.error) {
      dsai_errorStr = dsai_merged.error instanceof Error ? dsai_merged.error.stack || dsai_merged.error.message : String(dsai_merged.error);
      delete dsai_merged.error;
    }

    const dsai_payload: StructuredLogPayload = {
      timestamp: new Date().toISOString(),
      level: dsai_level.toUpperCase(),
      service: this.dsai_serviceName,
      ...(dsai_merged.tenant_id ? { tenant_id: dsai_merged.tenant_id } : {}),
      ...(dsai_merged.request_id ? { request_id: dsai_merged.request_id } : {}),
      ...(dsai_merged.route ? { route: dsai_merged.route } : {}),
      ...(dsai_merged.method ? { method: dsai_merged.method } : {}),
      ...(typeof dsai_merged.status === "number" ? { status: dsai_merged.status } : {}),
      ...(typeof dsai_merged.latency_ms === "number" ? { latency_ms: dsai_merged.latency_ms } : {}),
      ...(dsai_errorStr ? { error: dsai_errorStr } : {}),
      message: dsai_message,
      ...dsai_merged,
    };

    return JSON.stringify(dsai_payload);
  }

  private dsai_emit(dsai_level: LogLevel, dsai_message: string, dsai_context?: LogContext): void {
    if (!this.dsai_shouldLog(dsai_level)) return;
    const dsai_line = this.format(dsai_level, dsai_message, dsai_context);
    if (dsai_level === "error") {
      console.error(dsai_line);
    } else if (dsai_level === "warn") {
      console.warn(dsai_line);
    } else {
      console.log(dsai_line);
    }
  }

  public debug(dsai_message: string, dsai_context?: LogContext): void {
    this.dsai_emit("debug", dsai_message, dsai_context);
  }

  public info(dsai_message: string, dsai_context?: LogContext): void {
    this.dsai_emit("info", dsai_message, dsai_context);
  }

  public warn(dsai_message: string, dsai_context?: LogContext): void {
    this.dsai_emit("warn", dsai_message, dsai_context);
  }

  public error(dsai_message: string, dsai_context?: LogContext): void {
    this.dsai_emit("error", dsai_message, dsai_context);
  }

  public child(dsai_context: LogContext): StructuredLogger {
    return new StructuredLogger(this.dsai_serviceName, {
      ...this.dsai_defaultContext,
      ...dsai_context,
    });
  }
}

export const dsai_logger = new StructuredLogger("trinetra-ui");
export default dsai_logger;
