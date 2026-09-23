"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Eye, Menu, X, Shield, Bell, Upload, Search, BarChart3, Video, Building2 } from "lucide-react";
import { useState } from "react";
import { useSession } from "next-auth/react";
import { cn } from "@/lib/dsai_utils";
import { useTenant } from "@/hooks/useTenant";
import { SectorBadge } from "@/components/tenant/SectorBadge";

/** Navigation items — shared between desktop and mobile menus */
const dsai_navItems = [
  { dsai_label: "Dashboard", dsai_href: "/dashboard", dsai_icon: Eye },
  { dsai_label: "Search", dsai_href: "/search/text", dsai_icon: Search },
  { dsai_label: "Alerts", dsai_href: "/alerts", dsai_icon: Bell },
  { dsai_label: "Watchlist", dsai_href: "/watchlist", dsai_icon: Shield },
  { dsai_label: "Upload", dsai_href: "/ingest", dsai_icon: Upload },
  { dsai_label: "Streams", dsai_href: "/rtsp", dsai_icon: Video },
  { dsai_label: "Analytics", dsai_href: "/analytics", dsai_icon: BarChart3 },
  { dsai_label: "Admin", dsai_href: "/admin", dsai_icon: Building2 },
];

export function DsaiHeader() {
  const dsai_pathname = usePathname();
  const { data: dsai_session } = useSession();
  const { dsai_tenant, dsai_sector } = useTenant();
  const [dsai_mobileOpen, dsai_setMobileOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-800 bg-slate-950/90 backdrop-blur supports-[backdrop-filter]:bg-slate-950/75">
      <div className="container mx-auto max-w-7xl px-4 sm:px-6">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <Link
            href="/dashboard"
            className="flex items-center gap-2.5 font-bold text-lg min-h-[44px] min-w-[44px] py-1"
          >
            <div className="p-1.5 rounded-lg bg-blue-600/10 border border-blue-500/20 text-blue-400">
              <Eye className="h-5 w-5" />
            </div>
            <div className="flex flex-col sm:flex-row sm:items-baseline sm:gap-1.5">
              <span className="text-white font-extrabold tracking-tight">Trinetra</span>
              <span className="text-[10px] text-slate-400 hidden sm:inline font-mono">
                deepSightAI
              </span>
            </div>
          </Link>

          {/* Desktop Navigation */}
          <nav className="hidden lg:flex items-center gap-1">
            {dsai_navItems.map((dsai_item) => {
              const dsai_isActive = dsai_pathname.startsWith(dsai_item.dsai_href);
              const Icon = dsai_item.dsai_icon;
              return (
                <Link
                  key={dsai_item.dsai_href}
                  href={dsai_item.dsai_href}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition-colors",
                    dsai_isActive
                      ? "bg-blue-600/20 text-blue-400 border border-blue-500/30"
                      : "text-slate-400 hover:text-white hover:bg-slate-900"
                  )}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {dsai_item.dsai_label}
                </Link>
              );
            })}
          </nav>

          {/* User Tenant Info (Desktop) */}
          <div className="hidden sm:flex items-center gap-3">
            {dsai_sector && <SectorBadge dsai_sector={dsai_sector} dsai_size="sm" />}
            {dsai_session?.user && (
              <div className="text-right">
                <div className="text-xs font-semibold text-white">
                  {dsai_session.user.name || dsai_session.user.email}
                </div>
                <div className="text-[10px] text-slate-400 font-mono">
                  {dsai_tenant?.dsai_name || (dsai_session as any).dsai_tenantId || "Tenant"}
                </div>
              </div>
            )}
          </div>

          {/* Mobile hamburger button — strict 44x44px minimum touch target */}
          <button
            className="lg:hidden min-w-[44px] min-h-[44px] flex items-center justify-center rounded-xl bg-slate-900 border border-slate-800 text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
            onClick={() => dsai_setMobileOpen((prev) => !prev)}
            aria-label="Toggle navigation drawer"
            aria-expanded={dsai_mobileOpen}
          >
            {dsai_mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>

        {/* Mobile Nav Drawer */}
        {dsai_mobileOpen && (
          <div className="lg:hidden border-t border-slate-800 py-4 space-y-4">
            {/* Mobile Tenant Profile */}
            {dsai_session?.user && (
              <div className="px-3 py-2.5 bg-slate-900/80 rounded-xl border border-slate-800 flex items-center justify-between text-xs">
                <div>
                  <div className="font-semibold text-white">
                    {dsai_session.user.name || dsai_session.user.email}
                  </div>
                  <div className="text-slate-400 font-mono text-[11px]">
                    Scope: {dsai_tenant?.dsai_name || (dsai_session as any).dsai_tenantId || "Default"}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {dsai_sector && <SectorBadge dsai_sector={dsai_sector} dsai_size="sm" />}
                  <span className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 text-[10px] font-mono uppercase">
                    {((dsai_session as any).dsai_roles?.[0] as string) || "User"}
                  </span>
                </div>
              </div>
            )}

            {/* Mobile Nav List — every button >= 44px height */}
            <nav className="flex flex-col gap-1.5">
              {dsai_navItems.map((dsai_item) => {
                const dsai_isActive = dsai_pathname.startsWith(dsai_item.dsai_href);
                const Icon = dsai_item.dsai_icon;
                return (
                  <Link
                    key={dsai_item.dsai_href}
                    href={dsai_item.dsai_href}
                    className={cn(
                      "min-h-[44px] flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm font-semibold transition-colors",
                      dsai_isActive
                        ? "bg-blue-600 text-white shadow-lg shadow-blue-600/20"
                        : "text-slate-300 hover:text-white hover:bg-slate-900"
                    )}
                    onClick={() => dsai_setMobileOpen(false)}
                  >
                    <Icon className="w-4 h-4 shrink-0" />
                    <span>{dsai_item.dsai_label}</span>
                  </Link>
                );
              })}
            </nav>
          </div>
        )}
      </div>
    </header>
  );
}
