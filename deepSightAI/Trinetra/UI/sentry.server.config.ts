import * as Sentry from "@sentry/nextjs";

const DSAI_SENTRY_DSN = process.env.SENTRY_DSN || process.env.NEXT_PUBLIC_SENTRY_DSN;

Sentry.init({
  dsn: DSAI_SENTRY_DSN,
  tracesSampleRate: process.env.NODE_ENV === "production" ? 0.2 : 1.0,
  environment: process.env.NODE_ENV || "development",
  release: process.env.APP_VERSION || "0.1.0",
  beforeSend(dsai_event) {
    if (dsai_event.request?.headers) {
      delete dsai_event.request.headers["authorization"];
      delete dsai_event.request.headers["cookie"];
      delete dsai_event.request.headers["x-tenant-token"];
    }
    if (dsai_event.extra) {
      for (const dsai_key of Object.keys(dsai_event.extra)) {
        if (/password|token|secret|auth|key/i.test(dsai_key)) {
          dsai_event.extra[dsai_key] = "[REDACTED]";
        }
      }
    }
    return dsai_event;
  },
});
