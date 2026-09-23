import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { DsaiHeader } from "@/components/DsaiHeader";
import { DsaiProviders } from "@/components/DsaiProviders";

const dsai_inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Trinetra — deepSightAI Visual Intelligence Platform",
  description:
    "Multi-modal video search and live watchlist alerting engine for the Trinetra platform.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={dsai_inter.className}>
        <DsaiProviders>
          <div className="min-h-screen flex flex-col bg-background">
            <DsaiHeader />
            <main className="flex-1 container mx-auto px-4 py-6 max-w-7xl">
              {children}
            </main>
            <footer className="border-t py-4 text-center text-sm text-muted-foreground">
              deepSightAI Trinetra &copy; {new Date().getFullYear()}
            </footer>
          </div>
        </DsaiProviders>
      </body>
    </html>
  );
}
