"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Eye, Menu, X } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/dsai_utils";

/** Navigation items — shared between desktop and mobile menus */
const dsai_navItems = [
  { dsai_label: "Dashboard", dsai_href: "/" },
  { dsai_label: "Search", dsai_href: "/search" },
  { dsai_label: "Watchlist", dsai_href: "/watchlist" },
  { dsai_label: "Ingest", dsai_href: "/ingest" },
  { dsai_label: "Admin", dsai_href: "/admin" },
];

/**
 * DsaiHeader — top navigation bar with responsive mobile menu.
 * Rendered server-side in layout.tsx but declared "use client" for
 * usePathname / mobile toggle interactivity.
 */
export function DsaiHeader() {
  const dsai_pathname = usePathname();
  const [dsai_mobileOpen, dsai_setMobileOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto max-w-7xl px-4">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2 font-bold text-lg">
            <Eye className="h-6 w-6 text-primary" />
            <span className="hidden sm:inline">Trinetra</span>
            <span className="text-xs text-muted-foreground hidden sm:inline font-normal">
              by deepSightAI
            </span>
          </Link>

          {/* Desktop nav */}
          <nav className="hidden md:flex items-center gap-1">
            {dsai_navItems.map((dsai_item) => (
              <Link
                key={dsai_item.dsai_href}
                href={dsai_item.dsai_href}
                className={cn(
                  "px-3 py-2 rounded-md text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground",
                  dsai_pathname === dsai_item.dsai_href
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground"
                )}
              >
                {dsai_item.dsai_label}
              </Link>
            ))}
          </nav>

          {/* Mobile toggle */}
          <button
            className="md:hidden p-2 rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            onClick={() => dsai_setMobileOpen((dsai_prev) => !dsai_prev)}
            aria-label="Toggle navigation"
          >
            {dsai_mobileOpen ? (
              <X className="h-5 w-5" />
            ) : (
              <Menu className="h-5 w-5" />
            )}
          </button>
        </div>

        {/* Mobile nav drawer */}
        {dsai_mobileOpen && (
          <nav className="md:hidden py-3 border-t flex flex-col gap-1">
            {dsai_navItems.map((dsai_item) => (
              <Link
                key={dsai_item.dsai_href}
                href={dsai_item.dsai_href}
                className={cn(
                  "px-3 py-2 rounded-md text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground",
                  dsai_pathname === dsai_item.dsai_href
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground"
                )}
                onClick={() => dsai_setMobileOpen(false)}
              >
                {dsai_item.dsai_label}
              </Link>
            ))}
          </nav>
        )}
      </div>
    </header>
  );
}
