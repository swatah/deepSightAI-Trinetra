"use client";

import React, { useState } from "react";
import { useSession } from "next-auth/react";
import {
  BarChart3,
  Calendar,
  Download,
  Search,
  Bell,
  Video,
  Camera,
  ShieldAlert,
  ArrowUpRight,
  TrendingUp,
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
import { dsai_isAdmin } from "@/lib/auth/dsai_rbac";
import {
  ActivityLogEntry,
  dsai_exportActivityLogToCsv,
  dsai_downloadCsvFile,
} from "@/lib/csvExport";

const DSAI_SEARCH_TRENDS: Record<string, { date: string; queries: number; alerts: number }[]> = {
  today: [
    { date: "06:00", queries: 45, alerts: 2 },
    { date: "09:00", queries: 140, alerts: 5 },
    { date: "12:00", queries: 280, alerts: 8 },
    { date: "15:00", queries: 210, alerts: 4 },
    { date: "18:00", queries: 320, alerts: 11 },
    { date: "21:00", queries: 95, alerts: 3 },
  ],
  "7d": [
    { date: "Mon", queries: 1250, alerts: 34 },
    { date: "Tue", queries: 1480, alerts: 42 },
    { date: "Wed", queries: 1890, alerts: 58 },
    { date: "Thu", queries: 1670, alerts: 45 },
    { date: "Fri", queries: 2100, alerts: 64 },
    { date: "Sat", queries: 1120, alerts: 28 },
    { date: "Sun", queries: 940, alerts: 20 },
  ],
  "30d": [
    { date: "Week 1", queries: 8400, alerts: 210 },
    { date: "Week 2", queries: 9600, alerts: 245 },
    { date: "Week 3", queries: 11200, alerts: 310 },
    { date: "Week 4", queries: 10400, alerts: 280 },
  ],
};

const DSAI_CAMERA_ALERTS = [
  { camera: "North Gate", count: 84 },
  { camera: "Lobby East", count: 62 },
  { camera: "Loading Dock 1", count: 48 },
  { camera: "Perimeter West", count: 35 },
  { camera: "Parking Level B", count: 29 },
];

const DSAI_LEADERBOARD_CAMERAS = [
  { rank: 1, name: "North Gate Terminal", id: "CAM-01", detections: "184,200", status: "Active" },
  { rank: 2, name: "Main Lobby Escalators", id: "CAM-05", detections: "142,800", status: "Active" },
  { rank: 3, name: "Loading Bay Dock 3", id: "CAM-12", detections: "98,400", status: "Active" },
  { rank: 4, name: "South Gate Exit", id: "CAM-02", detections: "87,900", status: "Active" },
  { rank: 5, name: "Perimeter Fence West", id: "CAM-09", detections: "44,100", status: "Active" },
];

const DSAI_LEADERBOARD_TARGETS = [
  { rank: 1, target: "XYZ-9876 (Plate)", type: "Stolen Vehicle", searches: 142 },
  { rank: 2, target: "SUSPECT-REID-44", type: "Person Re-ID", searches: 98 },
  { rank: 3, target: "MTA-FLEET-102", type: "Authorized Fleet", searches: 84 },
  { rank: 4, target: "ABC-1234 (Plate)", type: "BOLO Target", searches: 65 },
  { rank: 5, target: "FORKLIFT-B2", type: "Asset Track", searches: 51 },
];

const DSAI_SAMPLE_ACTIVITY_LOGS: ActivityLogEntry[] = [
  {
    timestamp: "2026-09-22 17:45:12 UTC",
    event_type: "SEARCH_QUERY",
    user_id: "officer_449",
    camera_id: "CAM-01",
    details: "Vehicle attribute query: black sedan, 2026-09-22",
  },
  {
    timestamp: "2026-09-22 17:32:05 UTC",
    event_type: "ALERT_ACKNOWLEDGE",
    user_id: "supervisor_dave",
    camera_id: "CAM-12",
    details: "Acknowledged CRITICAL plate match XYZ-9876: True Positive",
  },
  {
    timestamp: "2026-09-22 16:50:33 UTC",
    event_type: "VIDEO_INGEST",
    user_id: "operator_jane",
    camera_id: "CAM-05",
    details: "Uploaded video footage s3://videos/lobby_1600.mp4 (1.4 GB)",
  },
  {
    timestamp: "2026-09-22 16:15:20 UTC",
    event_type: "WATCHLIST_CREATE",
    user_id: "admin_user",
    camera_id: "N/A",
    details: "Created high priority plate target BOLO-2026-09",
  },
];

export default function TenantAnalyticsDashboard() {
  const { data: dsai_session, status: dsai_authStatus } = useSession();
  const [dsai_timeRange, setDsaiTimeRange] = useState<"today" | "7d" | "30d">("7d");
  const [dsai_activityLogs] = useState<ActivityLogEntry[]>(DSAI_SAMPLE_ACTIVITY_LOGS);

  // Check admin privileges
  const dsai_adminAccess = dsai_isAdmin(dsai_session);

  // Loading state
  if (dsai_authStatus === "loading") {
    return (
      <div className="p-12 text-center text-slate-400 font-mono text-sm">
        Authenticating tenant session...
      </div>
    );
  }

  // 403 Forbidden for non-administrators
  if (!dsai_adminAccess) {
    return (
      <div className="min-h-[500px] flex items-center justify-center p-6">
        <div className="max-w-md w-full text-center space-y-4 bg-slate-900 border border-red-500/20 p-8 rounded-2xl">
          <div className="inline-flex p-3 rounded-full bg-red-500/10 text-red-400">
            <ShieldAlert className="w-8 h-8" />
          </div>
          <h2 className="text-xl font-bold text-white">403 Administrator Access Required</h2>
          <p className="text-sm text-slate-400">
            Tenant Analytics and audit logs contain privileged operational telemetry. You must possess the
            <strong className="text-slate-200"> admin</strong> role to access this dashboard.
          </p>
        </div>
      </div>
    );
  }

  const dsai_handleExportCsv = () => {
    const dsai_csv = dsai_exportActivityLogToCsv(dsai_activityLogs);
    const dsai_filename = `trinetra_activity_log_${dsai_timeRange}_${Date.now()}.csv`;
    dsai_downloadCsvFile(dsai_csv, dsai_filename);
  };

  const dsai_chartData = DSAI_SEARCH_TRENDS[dsai_timeRange] || DSAI_SEARCH_TRENDS["7d"];

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-blue-600/10 border border-blue-500/20 rounded-xl text-blue-400">
              <BarChart3 className="w-7 h-7" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white tracking-tight">
                Tenant Analytics & Usage Telemetry
              </h1>
              <p className="text-sm text-slate-400">
                Search volumes • Alert incident distributions • Audit activity CSV export
              </p>
            </div>
          </div>
        </div>

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Time range selector */}
          <div className="flex items-center bg-slate-900 border border-slate-800 rounded-xl p-1 text-xs">
            <button
              onClick={() => setDsaiTimeRange("today")}
              className={`px-3 py-1.5 rounded-lg transition-colors font-medium ${
                dsai_timeRange === "today"
                  ? "bg-blue-600 text-white font-semibold shadow"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Today
            </button>
            <button
              onClick={() => setDsaiTimeRange("7d")}
              className={`px-3 py-1.5 rounded-lg transition-colors font-medium ${
                dsai_timeRange === "7d"
                  ? "bg-blue-600 text-white font-semibold shadow"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Last 7 Days
            </button>
            <button
              onClick={() => setDsaiTimeRange("30d")}
              className={`px-3 py-1.5 rounded-lg transition-colors font-medium ${
                dsai_timeRange === "30d"
                  ? "bg-blue-600 text-white font-semibold shadow"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Last 30 Days
            </button>
          </div>

          {/* CSV Export Button */}
          <button
            onClick={dsai_handleExportCsv}
            className="inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold rounded-xl text-xs shadow-lg shadow-emerald-600/20 transition-colors"
          >
            <Download className="w-4 h-4" />
            Export Activity Log
          </button>
        </div>
      </div>

      {/* Summary KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Visual Search Queries</span>
            <Search className="w-4 h-4 text-blue-400" />
          </div>
          <div className="text-2xl font-bold text-white">10,450</div>
          <div className="text-xs text-emerald-400 font-medium flex items-center gap-1">
            <TrendingUp className="w-3.5 h-3.5" /> +18.4% this period
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Watchlist Alerts Produced</span>
            <Bell className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-bold text-white">288</div>
          <div className="text-xs text-slate-400 font-medium">96.5% Acknowledged</div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Ingested Footage Hours</span>
            <Video className="w-4 h-4 text-purple-400" />
          </div>
          <div className="text-2xl font-bold text-white">412.5 hrs</div>
          <div className="text-xs text-slate-400 font-medium">99.8% Indexing Success</div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Active Monitored Streams</span>
            <Camera className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-white">24 Cameras</div>
          <div className="text-xs text-emerald-400 font-medium">All Feeds Online</div>
        </div>
      </div>

      {/* Visual Trend Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-white text-base">Search Activity Over Time</h3>
            <span className="text-xs text-slate-400">Total Queries</span>
          </div>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={dsai_chartData}>
                <defs>
                  <linearGradient id="searchGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="date" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155" }}
                  itemStyle={{ color: "#f8fafc" }}
                />
                <Area
                  type="monotone"
                  dataKey="queries"
                  stroke="#3b82f6"
                  fillOpacity={1}
                  fill="url(#searchGradient)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-white text-base">Watchlist Alerts by Camera</h3>
            <span className="text-xs text-slate-400">Top 5 Alert Sources</span>
          </div>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={DSAI_CAMERA_ALERTS}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="camera" stroke="#94a3b8" fontSize={11} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155" }}
                  itemStyle={{ color: "#f8fafc" }}
                />
                <Bar dataKey="count" fill="#f59e0b" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Leaderboard Tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top Cameras */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-white text-base">Top 5 Most Active Cameras</h3>
            <span className="text-xs text-slate-400">Total Detections</span>
          </div>
          <div className="divide-y divide-slate-800">
            {DSAI_LEADERBOARD_CAMERAS.map((dsai_cam) => (
              <div key={dsai_cam.id} className="py-3 flex items-center justify-between text-xs">
                <div className="flex items-center gap-3">
                  <span className="w-5 h-5 rounded-full bg-slate-800 flex items-center justify-center font-bold text-slate-300">
                    {dsai_cam.rank}
                  </span>
                  <div>
                    <div className="font-semibold text-white">{dsai_cam.name}</div>
                    <div className="text-[11px] text-slate-500 font-mono">{dsai_cam.id}</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-bold text-slate-200">{dsai_cam.detections}</div>
                  <div className="text-[10px] text-emerald-400">{dsai_cam.status}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Most Searched Targets */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-white text-base">Most Searched Watchlist Targets</h3>
            <span className="text-xs text-slate-400">Query Frequency</span>
          </div>
          <div className="divide-y divide-slate-800">
            {DSAI_LEADERBOARD_TARGETS.map((dsai_tgt) => (
              <div key={dsai_tgt.rank} className="py-3 flex items-center justify-between text-xs">
                <div className="flex items-center gap-3">
                  <span className="w-5 h-5 rounded-full bg-slate-800 flex items-center justify-center font-bold text-slate-300">
                    {dsai_tgt.rank}
                  </span>
                  <div>
                    <div className="font-semibold text-white">{dsai_tgt.target}</div>
                    <div className="text-[11px] text-slate-500">{dsai_tgt.type}</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-bold text-blue-400">{dsai_tgt.searches} queries</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
