"use client";

import React, { Component, ReactNode } from "react";
import * as Sentry from "@sentry/nextjs";
import { AlertTriangle, RefreshCw, Flag } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  tenantId?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
  eventId: string | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      eventId: null,
    };
  }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      error,
      eventId: null,
    };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    const dsai_eventId = Sentry.captureException(error, {
      extra: { componentStack: errorInfo.componentStack },
      tags: {
        tenant_id: this.props.tenantId || "unknown",
      },
    });

    this.setState({ eventId: dsai_eventId });
  }

  handleReset = (): void => {
    this.setState({
      hasError: false,
      error: null,
      eventId: null,
    });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="min-h-[300px] flex items-center justify-center p-6 bg-slate-900/50 rounded-xl border border-red-500/20">
          <div className="max-w-md w-full text-center space-y-4">
            <div className="inline-flex p-3 rounded-full bg-red-500/10 text-red-400">
              <AlertTriangle className="w-8 h-8" />
            </div>
            <h3 className="text-lg font-semibold text-white">Something went wrong</h3>
            <p className="text-sm text-slate-400">
              An unexpected error occurred while rendering this component. Our telemetry has captured this event.
            </p>
            {this.state.eventId && (
              <p className="text-xs font-mono text-slate-500 bg-slate-800/80 py-1.5 px-3 rounded border border-slate-700">
                Event ID: {this.state.eventId}
              </p>
            )}
            <div className="flex items-center justify-center gap-3 pt-2">
              <button
                onClick={this.handleReset}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
                Try Again
              </button>
              <button
                onClick={() => {
                  if (typeof window !== "undefined") {
                    window.open(
                      `mailto:support@swatah.ai?subject=Trinetra%20Error%20Report%20${this.state.eventId || ""}&body=Error:%20${encodeURIComponent(this.state.error?.message || "")}`,
                      "_blank"
                    );
                  }
                }}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors border border-slate-700"
              >
                <Flag className="w-4 h-4" />
                Report Issue
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
