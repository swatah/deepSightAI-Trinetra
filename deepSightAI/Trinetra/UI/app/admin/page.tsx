"use client";

import React, { useState } from "react";
import { useSession } from "next-auth/react";
import {
  Shield,
  Building2,
  Users,
  Key,
  Plus,
  Copy,
  Check,
  AlertTriangle,
  ShieldAlert,
  ToggleLeft,
  ToggleRight,
} from "lucide-react";
import { dsai_isAdmin } from "@/lib/auth/dsai_rbac";

interface TenantRecord {
  id: string;
  name: string;
  slug: string;
  sector: string;
  active: boolean;
  created_at: string;
}

interface UserRecord {
  id: string;
  email: string;
  tenant_id: string;
  roles: string[];
  created_at: string;
}

interface ApiKeyRecord {
  id: number;
  name: string;
  prefix: string;
  created_at: string;
  expires_at: string;
}

const DSAI_INITIAL_TENANTS: TenantRecord[] = [
  {
    id: "1",
    name: "Metropolitan Transit Authority",
    slug: "mta-transit",
    sector: "law_enforcement",
    active: true,
    created_at: "2026-04-10",
  },
  {
    id: "2",
    name: "Apex Logistics & Freight",
    slug: "apex-logistics",
    sector: "logistics",
    active: true,
    created_at: "2026-05-18",
  },
  {
    id: "3",
    name: "OmniCorp Retail Centers",
    slug: "omnicorp-retail",
    sector: "commercial",
    active: true,
    created_at: "2026-06-22",
  },
];

const DSAI_INITIAL_USERS: UserRecord[] = [
  {
    id: "usr-1",
    email: "security.director@mta.gov",
    tenant_id: "mta-transit",
    roles: ["admin", "operator"],
    created_at: "2026-04-11",
  },
  {
    id: "usr-2",
    email: "patrol.officer@mta.gov",
    tenant_id: "mta-transit",
    roles: ["operator"],
    created_at: "2026-04-15",
  },
  {
    id: "usr-3",
    email: "auditor@swatah.ai",
    tenant_id: "omnicorp-retail",
    roles: ["viewer"],
    created_at: "2026-07-01",
  },
];

const DSAI_INITIAL_API_KEYS: ApiKeyRecord[] = [
  {
    id: 101,
    name: "Edge Camera Stream Ingest Key",
    prefix: "cp_9xK2mP1a",
    created_at: "2026-08-01",
    expires_at: "2027-08-01",
  },
];

export default function AdminPage() {
  const { data: dsai_session, status: dsai_authStatus } = useSession();
  const [dsai_activeTab, setDsaiActiveTab] = useState<"tenants" | "users" | "apikeys">("tenants");

  // Tenants state
  const [dsai_tenants, setDsaiTenants] = useState<TenantRecord[]>(DSAI_INITIAL_TENANTS);
  const [dsai_showCreateTenant, setDsaiShowCreateTenant] = useState(false);
  const [dsai_newTenantName, setDsaiNewTenantName] = useState("");
  const [dsai_newTenantSlug, setDsaiNewTenantSlug] = useState("");
  const [dsai_newTenantSector, setDsaiNewTenantSector] = useState("law_enforcement");

  // Users state
  const [dsai_users, setDsaiUsers] = useState<UserRecord[]>(DSAI_INITIAL_USERS);
  const [dsai_showCreateUser, setDsaiShowCreateUser] = useState(false);
  const [dsai_newUserEmail, setDsaiNewUserEmail] = useState("");
  const [dsai_newUserPassword, setDsaiNewUserPassword] = useState("");
  const [dsai_newUserTenant, setDsaiNewUserTenant] = useState("mta-transit");
  const [dsai_newUserRole, setDsaiNewUserRole] = useState("operator");

  // API Keys state
  const [dsai_apiKeys, setDsaiApiKeys] = useState<ApiKeyRecord[]>(DSAI_INITIAL_API_KEYS);
  const [dsai_showCreateApiKey, setDsaiShowCreateApiKey] = useState(false);
  const [dsai_newKeyName, setDsaiNewKeyName] = useState("");
  const [dsai_newKeyDays, setDsaiNewKeyDays] = useState(90);
  const [dsai_generatedSecret, setDsaiGeneratedSecret] = useState<string | null>(null);
  const [dsai_copiedSecret, setDsaiCopiedSecret] = useState(false);

  // Verify Admin privilege
  const dsai_adminAccess = dsai_isAdmin(dsai_session);

  if (dsai_authStatus === "loading") {
    return (
      <div className="p-12 text-center text-slate-400 font-mono text-sm">
        Authenticating administrator session...
      </div>
    );
  }

  if (!dsai_adminAccess) {
    return (
      <div className="min-h-[500px] flex items-center justify-center p-6">
        <div className="max-w-md w-full text-center space-y-4 bg-slate-900 border border-red-500/20 p-8 rounded-2xl shadow-xl">
          <div className="inline-flex p-3 rounded-full bg-red-500/10 text-red-400">
            <ShieldAlert className="w-8 h-8" />
          </div>
          <h2 className="text-xl font-bold text-white">403 Super-Admin Access Required</h2>
          <p className="text-sm text-slate-400">
            Platform tenant provisioning, user role management, and credential generation require
            super-admin privileges.
          </p>
        </div>
      </div>
    );
  }

  // Tenant Handlers
  const dsai_handleCreateTenant = () => {
    if (!dsai_newTenantName || !dsai_newTenantSlug) return;
    const dsai_newTenant: TenantRecord = {
      id: String(dsai_tenants.length + 1),
      name: dsai_newTenantName,
      slug: dsai_newTenantSlug.toLowerCase().replace(/\s+/g, "-"),
      sector: dsai_newTenantSector,
      active: true,
      created_at: new Date().toISOString().split("T")[0],
    };
    setDsaiTenants([...dsai_tenants, dsai_newTenant]);
    setDsaiNewTenantName("");
    setDsaiNewTenantSlug("");
    setDsaiShowCreateTenant(false);
  };

  const dsai_toggleTenantActive = (id: string) => {
    setDsaiTenants(
      dsai_tenants.map((t) => (t.id === id ? { ...t, active: !t.active } : t))
    );
  };

  // User Handlers
  const dsai_handleCreateUser = () => {
    if (!dsai_newUserEmail || !dsai_newUserPassword) return;
    const dsai_newUser: UserRecord = {
      id: `usr-${Date.now()}`,
      email: dsai_newUserEmail,
      tenant_id: dsai_newUserTenant,
      roles: [dsai_newUserRole],
      created_at: new Date().toISOString().split("T")[0],
    };
    setDsaiUsers([...dsai_users, dsai_newUser]);
    setDsaiNewUserEmail("");
    setDsaiNewUserPassword("");
    setDsaiShowCreateUser(false);
  };

  // API Key Handlers
  const dsai_handleCreateApiKey = () => {
    if (!dsai_newKeyName) return;
    const dsai_prefix = "cp_" + Math.random().toString(36).substring(2, 10);
    const dsai_suffix = Array.from({ length: 32 }, () =>
      Math.floor(Math.random() * 16).toString(16)
    ).join("");
    const dsai_fullKey = dsai_prefix + dsai_suffix;

    const dsai_expires = new Date();
    dsai_expires.setDate(dsai_expires.getDate() + dsai_newKeyDays);

    const dsai_newRecord: ApiKeyRecord = {
      id: Date.now(),
      name: dsai_newKeyName,
      prefix: dsai_prefix,
      created_at: new Date().toISOString().split("T")[0],
      expires_at: dsai_expires.toISOString().split("T")[0],
    };

    setDsaiApiKeys([...dsai_apiKeys, dsai_newRecord]);
    setDsaiGeneratedSecret(dsai_fullKey);
    setDsaiNewKeyName("");
    setDsaiShowCreateApiKey(false);
  };

  const dsai_handleCopySecret = () => {
    if (!dsai_generatedSecret) return;
    navigator.clipboard.writeText(dsai_generatedSecret);
    setDsaiCopiedSecret(true);
    setTimeout(() => setDsaiCopiedSecret(false), 2000);
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-blue-600/10 border border-blue-500/20 rounded-xl text-blue-400">
              <Shield className="w-7 h-7" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white tracking-tight">Super-Admin Platform Panel</h1>
              <p className="text-sm text-slate-400">
                Multi-tenant provisioning, operator accounts, and API key management
              </p>
            </div>
          </div>
        </div>

        {/* Tab Switcher */}
        <div className="flex items-center bg-slate-900 border border-slate-800 rounded-xl p-1 text-xs">
          <button
            onClick={() => setDsaiActiveTab("tenants")}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg transition-colors font-semibold ${
              dsai_activeTab === "tenants" ? "bg-blue-600 text-white shadow" : "text-slate-400 hover:text-white"
            }`}
          >
            <Building2 className="w-3.5 h-3.5" />
            Tenants
          </button>
          <button
            onClick={() => setDsaiActiveTab("users")}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg transition-colors font-semibold ${
              dsai_activeTab === "users" ? "bg-blue-600 text-white shadow" : "text-slate-400 hover:text-white"
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            Users
          </button>
          <button
            onClick={() => setDsaiActiveTab("apikeys")}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg transition-colors font-semibold ${
              dsai_activeTab === "apikeys" ? "bg-blue-600 text-white shadow" : "text-slate-400 hover:text-white"
            }`}
          >
            <Key className="w-3.5 h-3.5" />
            API Keys
          </button>
        </div>
      </div>

      {/* Tab 1: Tenant Management */}
      {dsai_activeTab === "tenants" && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-white">Platform Tenant Directory</h2>
            <button
              onClick={() => setDsaiShowCreateTenant(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-blue-600/20 transition-colors"
            >
              <Plus className="w-4 h-4" />
              Provision Tenant
            </button>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-950/70 text-xs uppercase font-semibold text-slate-400 border-b border-slate-800">
                <tr>
                  <th className="px-6 py-4">Tenant Name</th>
                  <th className="px-6 py-4">Slug ID</th>
                  <th className="px-6 py-4">Sector</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4">Created</th>
                  <th className="px-6 py-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-sans text-xs">
                {dsai_tenants.map((dsai_tenant) => (
                  <tr key={dsai_tenant.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="px-6 py-4 font-semibold text-white">{dsai_tenant.name}</td>
                    <td className="px-6 py-4 font-mono text-slate-400">{dsai_tenant.slug}</td>
                    <td className="px-6 py-4 capitalize text-slate-300">
                      {dsai_tenant.sector.replace("_", " ")}
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`inline-flex px-2 py-0.5 rounded-full font-medium text-[11px] ${
                          dsai_tenant.active
                            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                            : "bg-red-500/10 text-red-400 border border-red-500/20"
                        }`}
                      >
                        {dsai_tenant.active ? "Active" : "Suspended"}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-slate-500">{dsai_tenant.created_at}</td>
                    <td className="px-6 py-4 text-right">
                      <button
                        onClick={() => dsai_toggleTenantActive(dsai_tenant.id)}
                        className="text-xs text-slate-400 hover:text-white inline-flex items-center gap-1 font-medium"
                      >
                        {dsai_tenant.active ? (
                          <>
                            <ToggleRight className="w-4 h-4 text-emerald-400" /> Suspend
                          </>
                        ) : (
                          <>
                            <ToggleLeft className="w-4 h-4 text-slate-500" /> Activate
                          </>
                        )}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 2: User Provisioning */}
      {dsai_activeTab === "users" && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-white">Platform Users & Roles</h2>
            <button
              onClick={() => setDsaiShowCreateUser(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-blue-600/20 transition-colors"
            >
              <Plus className="w-4 h-4" />
              Invite User
            </button>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-950/70 text-xs uppercase font-semibold text-slate-400 border-b border-slate-800">
                <tr>
                  <th className="px-6 py-4">User Email</th>
                  <th className="px-6 py-4">Tenant Scope</th>
                  <th className="px-6 py-4">Assigned Roles</th>
                  <th className="px-6 py-4">Provisioned</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-sans text-xs">
                {dsai_users.map((dsai_user) => (
                  <tr key={dsai_user.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="px-6 py-4 font-semibold text-white">{dsai_user.email}</td>
                    <td className="px-6 py-4 font-mono text-slate-400">{dsai_user.tenant_id}</td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-1.5">
                        {dsai_user.roles.map((r) => (
                          <span
                            key={r}
                            className="px-2 py-0.5 rounded font-mono text-[10px] bg-slate-800 text-blue-300 border border-slate-700 uppercase"
                          >
                            {r}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-slate-500">{dsai_user.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 3: API Key Generation */}
      {dsai_activeTab === "apikeys" && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-bold text-white">Programmatic API Keys</h2>
              <p className="text-xs text-slate-400">
                Notice: Secret keys are hashed via Argon2id upon generation. Revocation is scheduled for a future release.
              </p>
            </div>
            <button
              onClick={() => setDsaiShowCreateApiKey(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-blue-600/20 transition-colors"
            >
              <Plus className="w-4 h-4" />
              Generate API Key
            </button>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-950/70 text-xs uppercase font-semibold text-slate-400 border-b border-slate-800">
                <tr>
                  <th className="px-6 py-4">Key Label</th>
                  <th className="px-6 py-4">Key Prefix</th>
                  <th className="px-6 py-4">Created Date</th>
                  <th className="px-6 py-4">Expiration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-sans text-xs">
                {dsai_apiKeys.map((dsai_key) => (
                  <tr key={dsai_key.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="px-6 py-4 font-semibold text-white">{dsai_key.name}</td>
                    <td className="px-6 py-4 font-mono text-slate-400">{dsai_key.prefix}••••••••</td>
                    <td className="px-6 py-4 text-slate-500">{dsai_key.created_at}</td>
                    <td className="px-6 py-4 text-slate-400">{dsai_key.expires_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Modal: Create Tenant */}
      {dsai_showCreateTenant && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4">
            <h3 className="text-lg font-bold text-white">Provision New Platform Tenant</h3>
            <div className="space-y-3 text-sm">
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Tenant Name *</label>
                <input
                  type="text"
                  placeholder="e.g. Gotham City Police Department"
                  value={dsai_newTenantName}
                  onChange={(e) => setDsaiNewTenantName(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Slug Identifier *</label>
                <input
                  type="text"
                  placeholder="e.g. gcpd"
                  value={dsai_newTenantSlug}
                  onChange={(e) => setDsaiNewTenantSlug(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Sector *</label>
                <select
                  value={dsai_newTenantSector}
                  onChange={(e) => setDsaiNewTenantSector(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm"
                >
                  <option value="law_enforcement">Law Enforcement</option>
                  <option value="logistics">Logistics & Supply Chain</option>
                  <option value="commercial">Commercial & Retail</option>
                  <option value="government">Government & Infrastructure</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setDsaiShowCreateTenant(false)}
                className="px-4 py-2 bg-slate-800 text-slate-300 rounded-lg text-xs"
              >
                Cancel
              </button>
              <button
                onClick={dsai_handleCreateTenant}
                disabled={!dsai_newTenantName || !dsai_newTenantSlug}
                className="px-4 py-2 bg-blue-600 disabled:opacity-50 text-white rounded-lg text-xs font-semibold"
              >
                Provision Tenant
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Create User */}
      {dsai_showCreateUser && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4">
            <h3 className="text-lg font-bold text-white">Provision User Account</h3>
            <div className="space-y-3 text-sm">
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">User Email *</label>
                <input
                  type="email"
                  placeholder="e.g. officer@mta.gov"
                  value={dsai_newUserEmail}
                  onChange={(e) => setDsaiNewUserEmail(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Initial Password *</label>
                <input
                  type="password"
                  placeholder="Min 8 characters"
                  value={dsai_newUserPassword}
                  onChange={(e) => setDsaiNewUserPassword(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Tenant Organization *</label>
                <select
                  value={dsai_newUserTenant}
                  onChange={(e) => setDsaiNewUserTenant(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm"
                >
                  {dsai_tenants.map((t) => (
                    <option key={t.slug} value={t.slug}>
                      {t.name} ({t.slug})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Platform Role *</label>
                <select
                  value={dsai_newUserRole}
                  onChange={(e) => setDsaiNewUserRole(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm"
                >
                  <option value="operator">Operator (Search, View & Alerts)</option>
                  <option value="admin">Administrator (Watchlist Writes & Tenant Admin)</option>
                  <option value="viewer">Viewer (Read-Only Access)</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setDsaiShowCreateUser(false)}
                className="px-4 py-2 bg-slate-800 text-slate-300 rounded-lg text-xs"
              >
                Cancel
              </button>
              <button
                onClick={dsai_handleCreateUser}
                disabled={!dsai_newUserEmail || !dsai_newUserPassword}
                className="px-4 py-2 bg-blue-600 disabled:opacity-50 text-white rounded-lg text-xs font-semibold"
              >
                Create User
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Create API Key */}
      {dsai_showCreateApiKey && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4">
            <h3 className="text-lg font-bold text-white">Generate Programmatic API Key</h3>
            <div className="space-y-3 text-sm">
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Key Description / Name *</label>
                <input
                  type="text"
                  placeholder="e.g. RTSP Video Ingest Daemon"
                  value={dsai_newKeyName}
                  onChange={(e) => setDsaiNewKeyName(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Expiration Period</label>
                <select
                  value={dsai_newKeyDays}
                  onChange={(e) => setDsaiNewKeyDays(Number(e.target.value))}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm"
                >
                  <option value={30}>30 Days</option>
                  <option value={90}>90 Days</option>
                  <option value={365}>1 Year</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setDsaiShowCreateApiKey(false)}
                className="px-4 py-2 bg-slate-800 text-slate-300 rounded-lg text-xs"
              >
                Cancel
              </button>
              <button
                onClick={dsai_handleCreateApiKey}
                disabled={!dsai_newKeyName}
                className="px-4 py-2 bg-blue-600 disabled:opacity-50 text-white rounded-lg text-xs font-semibold"
              >
                Generate Key
              </button>
            </div>
          </div>
        </div>
      )}

      {/* One-Time Secret Display Modal */}
      {dsai_generatedSecret && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-amber-500/30 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center gap-2 text-amber-400 font-bold text-lg">
              <AlertTriangle className="w-5 h-5 shrink-0" />
              Store Your Secret API Key
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">
              Make sure to copy your API key now as you will not be able to see it again! For security,
              only its cryptographic hash is stored on the server.
            </p>
            <div className="p-3 bg-slate-950 rounded-xl border border-slate-800 flex items-center justify-between gap-2">
              <code className="text-xs font-mono text-emerald-400 break-all select-all">
                {dsai_generatedSecret}
              </code>
              <button
                onClick={dsai_handleCopySecret}
                className="p-2 bg-slate-800 hover:bg-slate-700 text-white rounded-lg shrink-0 transition-colors"
                title="Copy to clipboard"
              >
                {dsai_copiedSecret ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
            {dsai_copiedSecret && (
              <div className="text-xs text-emerald-400 font-medium text-center">
                ✓ Copied to clipboard!
              </div>
            )}
            <div className="flex justify-end pt-2">
              <button
                onClick={() => setDsaiGeneratedSecret(null)}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold"
              >
                I have safely stored my key
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
