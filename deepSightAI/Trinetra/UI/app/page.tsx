import { Camera, Search, Bell, ShieldCheck } from "lucide-react";

/**
 * Root landing page for the Trinetra UI.
 * Next.js App Router reserved filename — exempt from dsai_ prefix per project policy.
 */
export default function Page() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-8 text-center">
      <div>
        <h1 className="text-4xl font-bold tracking-tight text-foreground mb-3">
          Trinetra Visual Intelligence Platform
        </h1>
        <p className="text-muted-foreground text-lg max-w-xl mx-auto">
          Multi-modal video search, live watchlist alerting, and real-time
          threat detection — powered by deepSightAI.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 w-full max-w-3xl">
        <DsaiFeatureCard
          icon={<Search className="h-6 w-6" />}
          title="Visual Search"
          description="Text, vehicle, person, plate & image search"
        />
        <DsaiFeatureCard
          icon={<Bell className="h-6 w-6" />}
          title="Live Alerts"
          description="Real-time watchlist matching via SSE stream"
        />
        <DsaiFeatureCard
          icon={<Camera className="h-6 w-6" />}
          title="RTSP Ingestion"
          description="Multi-camera stream management"
        />
        <DsaiFeatureCard
          icon={<ShieldCheck className="h-6 w-6" />}
          title="Multi-Tenant"
          description="Full data isolation per tenant"
        />
      </div>
    </div>
  );
}

interface DsaiFeatureCardProps {
  dsai_icon?: React.ReactNode;
  icon?: React.ReactNode;
  title: string;
  description: string;
}

function DsaiFeatureCard({ icon, title, description }: DsaiFeatureCardProps) {
  return (
    <div className="rounded-lg border bg-card p-4 flex flex-col items-center gap-2 text-card-foreground shadow-sm hover:shadow-md transition-shadow">
      <div className="text-primary">{icon}</div>
      <h3 className="font-semibold text-sm">{title}</h3>
      <p className="text-xs text-muted-foreground">{description}</p>
    </div>
  );
}
