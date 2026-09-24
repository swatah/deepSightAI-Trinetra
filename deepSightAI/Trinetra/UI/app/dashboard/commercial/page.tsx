"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  ShoppingBag,
  Users,
  Clock,
  TrendingUp,
  Layers,
  Sparkles,
  Info,
  Camera,
} from "lucide-react";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { useTenant } from "@/hooks/useTenant";
import { SectorBadge } from "@/components/tenant/SectorBadge";
import { SectorGate } from "@/components/tenant/SectorGate";

// Sample foot traffic time series
const DSAI_HOURLY_TRAFFIC = [
  { hour: "08:00", visitors: 120, dwell: 8 },
  { hour: "10:00", visitors: 450, dwell: 14 },
  { hour: "12:00", visitors: 890, dwell: 22 },
  { hour: "14:00", visitors: 780, dwell: 19 },
  { hour: "16:00", visitors: 1100, dwell: 25 },
  { hour: "18:00", visitors: 1420, dwell: 28 },
  { hour: "20:00", visitors: 650, dwell: 16 },
  { hour: "22:00", visitors: 210, dwell: 10 },
];

// Sample shopper demographics
const DSAI_DEMOGRAPHICS = [
  { ageGroup: "18-24", count: 320 },
  { ageGroup: "25-34", count: 840 },
  { ageGroup: "35-44", count: 650 },
  { ageGroup: "45-54", count: 420 },
  { ageGroup: "55+", count: 210 },
];

export default function CommercialDashboard() {
  return (
    <SectorGate dsai_requiredSector="commercial" dsai_label="Commercial">
      <CommercialDashboardContent />
    </SectorGate>
  );
}

function CommercialDashboardContent() {
  const { dsai_sector } = useTenant();
  const [dsai_showHeatmap, setDsaiShowHeatmap] = useState(true);
  const [dsai_selectedCamera, setDsaiSelectedCamera] = useState("CAM-ENTRANCE-01");
  const [dsai_intensity, setDsaiIntensity] = useState(70);
  const dsai_canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Draw simulated radial heat points on canvas
  useEffect(() => {
    const dsai_canvas = dsai_canvasRef.current;
    if (!dsai_canvas) return;
    const dsai_ctx = dsai_canvas.getContext("2d");
    if (!dsai_ctx) return;

    dsai_ctx.clearRect(0, 0, dsai_canvas.width, dsai_canvas.height);

    if (!dsai_showHeatmap) return;

    // Draw background store layout grid
    dsai_ctx.fillStyle = "#0f172a";
    dsai_ctx.fillRect(0, 0, dsai_canvas.width, dsai_canvas.height);

    // Heat points coordinates
    const dsai_heatPoints = [
      { x: 120, y: 140, radius: 80, weight: dsai_intensity / 100 },
      { x: 260, y: 180, radius: 95, weight: (dsai_intensity * 0.9) / 100 },
      { x: 380, y: 110, radius: 70, weight: (dsai_intensity * 0.75) / 100 },
      { x: 480, y: 200, radius: 60, weight: (dsai_intensity * 0.6) / 100 },
    ];

    for (const dsai_pt of dsai_heatPoints) {
      const dsai_gradient = dsai_ctx.createRadialGradient(
        dsai_pt.x,
        dsai_pt.y,
        0,
        dsai_pt.x,
        dsai_pt.y,
        dsai_pt.radius
      );
      dsai_gradient.addColorStop(0, `rgba(239, 68, 68, ${0.85 * dsai_pt.weight})`);
      dsai_gradient.addColorStop(0.4, `rgba(245, 158, 11, ${0.65 * dsai_pt.weight})`);
      dsai_gradient.addColorStop(0.7, `rgba(59, 130, 246, ${0.35 * dsai_pt.weight})`);
      dsai_gradient.addColorStop(1, "rgba(0, 0, 0, 0)");

      dsai_ctx.fillStyle = dsai_gradient;
      dsai_ctx.beginPath();
      dsai_ctx.arc(dsai_pt.x, dsai_pt.y, dsai_pt.radius, 0, Math.PI * 2);
      dsai_ctx.fill();
    }
  }, [dsai_showHeatmap, dsai_intensity, dsai_selectedCamera]);

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-emerald-600/10 border border-emerald-500/20 rounded-xl text-emerald-400">
              <ShoppingBag className="w-7 h-7" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white tracking-tight">
                Commercial & Retail Analytics Dashboard
              </h1>
              <p className="text-sm text-slate-400">
                Foot Traffic Density • Dwell Times • Shopper Demographics
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
          <strong className="text-white">Commercial Model Status:</strong> Dwell heatmaps and shopper
          demographics are computed from local plugin stubs (<code className="text-blue-300">heatmap.py</code>,{" "}
          <code className="text-blue-300">demographics.py</code>). Visualizations gracefully operate in training
          preview mode until production edge inference models are promoted.
        </p>
      </div>

      {/* Key Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Today's Total Foot Traffic</span>
            <Users className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-white">5,620</div>
          <div className="text-xs text-emerald-400 font-medium flex items-center gap-1">
            <TrendingUp className="w-3.5 h-3.5" /> +14.2% vs yesterday
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Average Dwell Time</span>
            <Clock className="w-4 h-4 text-blue-400" />
          </div>
          <div className="text-2xl font-bold text-white">18.4 mins</div>
          <div className="text-xs text-slate-400">Peak dwell in Electronics</div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Peak Visitor Hour</span>
            <TrendingUp className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-bold text-white">18:00 - 19:00</div>
          <div className="text-xs text-amber-400 font-medium">1,420 visitors/hr</div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Store Conversion Rate</span>
            <ShoppingBag className="w-4 h-4 text-purple-400" />
          </div>
          <div className="text-2xl font-bold text-white">24.8%</div>
          <div className="text-xs text-purple-400 font-medium">+2.1% this week</div>
        </div>
      </div>

      {/* Heatmap Section */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Layers className="w-5 h-5 text-emerald-400" />
              <h2 className="text-lg font-bold text-white">Store Dwell Time Heatmap Overlay</h2>
            </div>
            <p className="text-sm text-slate-400">
              Visualizes customer congregation and foot traffic bottleneck density across camera fields of view.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2 bg-slate-950 px-3 py-1.5 rounded-lg border border-slate-800 text-xs">
              <Camera className="w-4 h-4 text-slate-400" />
              <select
                value={dsai_selectedCamera}
                onChange={(e) => setDsaiSelectedCamera(e.target.value)}
                className="bg-transparent text-white focus:outline-none"
              >
                <option value="CAM-ENTRANCE-01">Main Store Entrance</option>
                <option value="CAM-ELECTRONICS-02">Electronics Department</option>
                <option value="CAM-CHECKOUT-03">Checkout Counters</option>
              </select>
            </div>

            <button
              onClick={() => setDsaiShowHeatmap(!dsai_showHeatmap)}
              className={`px-4 py-1.5 text-xs font-semibold rounded-lg transition-colors border ${
                dsai_showHeatmap
                  ? "bg-emerald-600/20 text-emerald-400 border-emerald-500/40 hover:bg-emerald-600/30"
                  : "bg-slate-800 text-slate-400 border-slate-700 hover:bg-slate-700"
              }`}
            >
              {dsai_showHeatmap ? "Heatmap: Visible" : "Heatmap: Hidden"}
            </button>
          </div>
        </div>

        {/* Heatmap Canvas Container */}
        <div className="relative w-full aspect-video max-h-[420px] rounded-xl overflow-hidden border border-slate-800 bg-slate-950 flex items-center justify-center">
          <canvas
            ref={dsai_canvasRef}
            width={600}
            height={360}
            className="w-full h-full object-cover"
          />
          <div className="absolute top-4 left-4 bg-slate-900/80 backdrop-blur-md px-3 py-1.5 rounded-md border border-slate-700 text-xs text-slate-300 font-mono">
            Feed: {dsai_selectedCamera} • Live Density Map
          </div>
          <div className="absolute bottom-4 right-4 bg-slate-900/80 backdrop-blur-md px-3 py-1.5 rounded-md border border-slate-700 text-xs text-slate-300 flex items-center gap-2">
            <span>Density: Low</span>
            <div className="w-20 h-2 rounded bg-gradient-to-r from-blue-500 via-amber-500 to-red-500" />
            <span>High</span>
          </div>
        </div>
      </div>

      {/* Traffic Trend and Demographics Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-white text-base">Hourly Traffic Trends</h3>
            <span className="text-xs text-slate-400">Past 24 Hours</span>
          </div>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={DSAI_HOURLY_TRAFFIC}>
                <defs>
                  <linearGradient id="trafficGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="hour" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155" }}
                  itemStyle={{ color: "#f8fafc" }}
                />
                <Area
                  type="monotone"
                  dataKey="visitors"
                  stroke="#10b981"
                  fillOpacity={1}
                  fill="url(#trafficGradient)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-white text-base">Shopper Demographics (Age Brackets)</h3>
            <span className="text-xs text-slate-400">Estimated Distribution</span>
          </div>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={DSAI_DEMOGRAPHICS}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="ageGroup" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155" }}
                  itemStyle={{ color: "#f8fafc" }}
                />
                <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
