"use client";

import React from "react";
import { SessionProvider } from "next-auth/react";
import { DsaiTenantProvider } from "@/context/TenantContext";
import { ErrorBoundary } from "@/components/ErrorBoundary";

export interface DsaiProvidersProps {
  children: React.ReactNode;
}

export function DsaiProviders({ children }: DsaiProvidersProps) {
  return (
    <SessionProvider>
      <ErrorBoundary>
        <DsaiTenantProvider>
          {children}
        </DsaiTenantProvider>
      </ErrorBoundary>
    </SessionProvider>
  );
}
