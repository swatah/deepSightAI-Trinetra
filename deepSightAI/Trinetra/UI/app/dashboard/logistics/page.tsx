"use client";

import React, { useState } from "react";
import {
  Truck,
  HardHat,
  AlertTriangle,
  Clock,
  CheckCircle2,
  XCircle,
  Sparkles,
  Info,
  ShieldCheck,
  Video,
} from "lucide-react";
import { useTenant } from "@/hooks/useTenant";
import { SectorBadge } from "@/components/tenant/SectorBadge";
import { SectorGate } from "@/components/tenant/SectorGate";

interface DockDoor {
  bay_id: string;
  name: string;
  status: "AVAILABLE" | "LOADING" | "OCCUPIED" | "OVERDUE";
  carrier: string;
  duration_mins: number;
}

const DSAI_DOCK_DOORS: DockDoor[] = [
  { bay_id: "BAY-01", name: "Inbound Bay 1", status: "LOADING", carrier: "DHL Express", duration_mins: 34 },
  { bay_id: "BAY-02", name: "Inbound Bay 2", status: "AVAILABLE", carrier: "None", duration_mins: 0 },
  { bay_id: "BAY-03", name: "Outbound Bay 3", status: "OVERDUE", carrier: "FedEx Freight", duration_mins: 92 },
  { bay_id: "BAY-04", name: "Outbound Bay 4", status: "OCCUPIED", carrier: "UPS Supply Chain", duration_mins: 45 },
  { bay_id: "BAY-05", name: "Inbound Bay 5", status: "AVAILABLE", carrier: "None", duration_mins: 0 },
  { bay_id: "BAY-06", name: "Cross-dock Bay 6", status: "LOADING", carrier: "Schneider Logistics", duration_mins: 22 },
];

interface ProximityViolation {
  id: string;
  timestamp: string;
  camera_id: string;
  event_type: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM";
  distance_meters: number;
}

const DSAI_INCIDENTS: ProximityViolation[] = [
  {
    id: "INC-2026-441",
    timestamp: "10 minutes ago",
    camera_id: "CAM-AISLE-04",
    event_type: "Forklift / Pedestrian Proximity Violation",
    severity: "HIGH",
    distance_meters: 1.4,
  },
  {
    id: "INC-2026-440",
    timestamp: "38 minutes ago",
    camera_id: "CAM-BAY-03-LOADING",
    event_type: "Bystander in Active Loading Bay without Vest",
    severity: "CRITICAL",
    distance_meters: 0.8,
  },
  {
    id: "INC-2026-439",
    timestamp: "2 hours ago",
    camera_id: "CAM-STAGING-02",
    event_type: "Unattended Pallet Jack in Forklift Travel Lane",
    severity: "MEDIUM",
    distance_meters: 2.1,
  },
];

export default function LogisticsDashboard() {
  return (
    <SectorGate dsai_requiredSector="logistics" dsai_label="Logistics">
      <LogisticsDashboardContent />
    </SectorGate>
  );
}

function LogisticsDashboardContent() {
  const { dsai_sector } = useTenant();
  const [dsai_ppeCompliance, setDsaiPpeCompliance] = useState(94);
  const [dsai_dockDoors] = useState<DockDoor[]>(DSAI_DOCK_DOORS);
  const [dsai_incidents] = useState<ProximityViolation[]>(DSAI_INCIDENTS);

  const dsai_isUnderThreshold = dsai_ppeCompliance < 90;

  const dsai_getStatusBadge = (status: DockDoor["status"]) => {
    switch (status) {
      case "AVAILABLE":
        return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Available</span>;
      case "LOADING":
        return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20">Loading</span>;
      case "OCCUPIED":
        return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">Occupied</span>;
      case "OVERDUE":
        return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-500/10 text-red-400 border border-red-500/20 animate-pulse">Overdue (&gt;60m)</span>;
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-blue-600/10 border border-blue-500/20 rounded-xl text-blue-400">
              <Truck className="w-7 h-7" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white tracking-tight">
                Logistics & Warehouse Operations Dashboard
              </h1>
              <p className="text-sm text-slate-400">
                PPE Safety Compliance • Dock Bay Turnaround • Proximity Incident Feed
              </p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {dsai_sector && <SectorBadge dsai_sector={dsai_sector} dsai_size="md" />}
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 text-xs font-semibold">
            <Sparkles className="w-3.5 h-3.5" />
            P2 Beta • ML In Training Mode
          </span>
        </div>
      </div>

      {/* Model Maturity Notice */}
      <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 flex items-start gap-3 text-slate-300 text-sm">
        <Info className="w-5 h-5 text-blue-400 shrink-0 mt-0.5" />
        <p className="leading-relaxed">
          <strong className="text-white">Logistics Model Status:</strong> PPE detection is powered by the{" "}
          <code className="text-blue-300">ppe.py</code> plugin stub (hard hat and high-vis vest classification).
          Dock door turnaround telemetry simulates sensor integrations pending production edge camera deployment.
        </p>
      </div>

      {/* Threshold Alert Banner if < 90% */}
      {dsai_isUnderThreshold && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-200 flex items-center justify-between gap-4 animate-bounce">
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-6 h-6 text-red-400 shrink-0" />
            <div>
              <div className="font-bold text-red-400 text-sm">CRITICAL SAFETY THRESHOLD ALERT</div>
              <div className="text-xs text-red-200/90">
                Facility-wide PPE compliance has fallen below 90% ({dsai_ppeCompliance}%). Warehouse Floor Supervisor
                walkthrough mandated immediately.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* PPE Compliance Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 lg:col-span-1">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-bold text-white">
              <HardHat className="w-5 h-5 text-amber-400" />
              <h3>PPE Compliance Gauge</h3>
            </div>
            <span
              className={`text-xs font-bold px-2 py-0.5 rounded ${
                dsai_ppeCompliance >= 90
                  ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                  : "bg-red-500/10 text-red-400 border border-red-500/20"
              }`}
            >
              Threshold: 90%
            </span>
          </div>

          <div className="flex flex-col items-center justify-center py-4 space-y-2">
            <div
              className={`text-5xl font-extrabold tracking-tight ${
                dsai_ppeCompliance >= 90 ? "text-emerald-400" : "text-red-400"
              }`}
            >
              {dsai_ppeCompliance}%
            </div>
            <div className="text-xs text-slate-400">Facility Overall Compliance</div>
          </div>

          {/* Test slider */}
          <div className="pt-2 border-t border-slate-800 space-y-1">
            <div className="flex justify-between text-xs text-slate-400">
              <span>Simulate Compliance Score:</span>
              <span className="font-mono text-white">{dsai_ppeCompliance}%</span>
            </div>
            <input
              type="range"
              min="70"
              max="100"
              value={dsai_ppeCompliance}
              onChange={(e) => setDsaiPpeCompliance(Number(e.target.value))}
              className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-blue-500"
            />
          </div>

          {/* Sub-breakdowns */}
          <div className="space-y-2 pt-2 text-xs">
            <div className="flex justify-between text-slate-300">
              <span>Hard Hat Protection</span>
              <span className="font-semibold text-emerald-400">96.2%</span>
            </div>
            <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
              <div className="bg-emerald-500 h-full rounded-full" style={{ width: "96.2%" }} />
            </div>

            <div className="flex justify-between text-slate-300 pt-1">
              <span>High-Visibility Vests</span>
              <span className="font-semibold text-blue-400">91.8%</span>
            </div>
            <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
              <div className="bg-blue-500 h-full rounded-full" style={{ width: "91.8%" }} />
            </div>
          </div>
        </div>

        {/* Dock Bay Turnaround Grid */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 lg:col-span-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-bold text-white">
              <Truck className="w-5 h-5 text-blue-400" />
              <h3>Dock Door Utilization & Turnaround</h3>
            </div>
            <div className="text-xs text-slate-400 flex items-center gap-1">
              <Clock className="w-3.5 h-3.5" /> Avg Turnaround: <strong className="text-white">41 mins</strong>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3 pt-2">
            {dsai_dockDoors.map((dsai_door) => (
              <div
                key={dsai_door.bay_id}
                className="bg-slate-950/80 border border-slate-800 rounded-xl p-3.5 space-y-2 hover:border-slate-700 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono font-bold text-white">{dsai_door.bay_id}</span>
                  {dsai_getStatusBadge(dsai_door.status)}
                </div>
                <div className="text-xs text-slate-300 font-medium">{dsai_door.name}</div>
                <div className="text-[11px] text-slate-400 truncate">
                  Carrier: <span className="text-slate-200">{dsai_door.carrier}</span>
                </div>
                {dsai_door.duration_mins > 0 && (
                  <div className="text-[11px] text-slate-500 font-mono">
                    Elapsed: {dsai_door.duration_mins}m
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Proximity Violation Feed */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 font-bold text-white">
            <AlertTriangle className="w-5 h-5 text-amber-400" />
            <h2>Proximity Violations & Near-Miss Incidents</h2>
          </div>
          <span className="text-xs text-slate-400 font-mono">Real-Time Facility Stream</span>
        </div>

        <div className="divide-y divide-slate-800/80">
          {dsai_incidents.map((dsai_inc) => (
            <div key={dsai_inc.id} className="py-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span
                    className={`px-2 py-0.5 rounded font-bold text-[10px] ${
                      dsai_inc.severity === "CRITICAL"
                        ? "bg-red-500/20 text-red-400 border border-red-500/30"
                        : "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                    }`}
                  >
                    {dsai_inc.severity}
                  </span>
                  <span className="font-semibold text-white">{dsai_inc.event_type}</span>
                  <span className="text-slate-400">• Distance: {dsai_inc.distance_meters}m</span>
                </div>
                <div className="text-slate-500 text-[11px]">
                  Camera: <span className="text-slate-400 font-mono">{dsai_inc.camera_id}</span> • {dsai_inc.timestamp}
                </div>
              </div>

              <button className="self-start sm:self-auto inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium border border-slate-700 transition-colors">
                <Video className="w-3.5 h-3.5 text-blue-400" />
                View Clip
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
