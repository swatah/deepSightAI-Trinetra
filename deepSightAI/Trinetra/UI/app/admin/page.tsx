"use client";

import React, { useEffect, useState } from "react";
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
  Loader2,
} from "lucide-react";
import { dsai_isAdmin } from "@/lib/auth/dsai_rbac";
import { SectorBadge } from "@/components/tenant/SectorBadge";
import { QuotaUsageDisplay } from "@/components/tenant/QuotaUsageDisplay";
import { dsai_apiGet, dsai_apiPost, dsai_apiPatch, DsaiApiError } from "@/lib/api/dsai_client";

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

/** Raw shape returned by GET/POST /tenants on AuthService */
interface DsaiTenantApiRecord {
  id: string;
  name: string;
  slug: string;
  active: boolean;
  created_at: string | null;
  plugin_config?: Record<string, unknown> | null;
}

function dsai_mapTenantRecord(dsai_raw: DsaiTenantApiRecord): TenantRecord {
  const dsai_pluginConfig = dsai_raw.plugin_config ?? {};
  const dsai_sector =
    typeof dsai_pluginConfig["sector"] === "string" ? (dsai_pluginConfig["sector"] as string) : "general";
  return {
    id: dsai_raw.id,
    name: dsai_raw.name,
    slug: dsai_raw.slug,
    sector: dsai_sector,
    active: dsai_raw.active,
    created_at: dsai_raw.created_at ?? "",
  };
}

export default function AdminPage() {
  const { data: dsai_session, status: dsai_authStatus } = useSession();
  const dsai_accessToken = (dsai_session as any)?.dsai_accessToken as string | undefined;
  const dsai_tenantId = (dsai_session as any)?.dsai_tenantId as string | undefined;
  const [dsai_activeTab, setDsaiActiveTab] = useState<"tenants" | "users" | "apikeys">("tenants");

  // Tenants state
  const [dsai_tenants, setDsaiTenants] = useState<TenantRecord[]>([]);
  const [dsai_tenantsLoading, setDsaiTenantsLoading] = useState(false);
  const [dsai_tenantsError, setDsaiTenantsError] = useState<string | null>(null);
  const [dsai_showCreateTenant, setDsaiShowCreateTenant] = useState(false);
  const [dsai_newTenantName, setDsaiNewTenantName] = useState("");
  const [dsai_newTenantSlug, setDsaiNewTenantSlug] = useState("");
  const [dsai_newTenantSector, setDsaiNewTenantSector] = useState("law_enforcement");
  const [dsai_createTenantError, setDsaiCreateTenantError] = useState<string | null>(null);
  const [dsai_createTenantBusy, setDsaiCreateTenantBusy] = useState(false);
  const [dsai_togglingTenantId, setDsaiTogglingTenantId] = useState<string | null>(null);
  const [dsai_toggleTenantError, setDsaiToggleTenantError] = useState<string | null>(null);

  // Users state — fetched in a single call to GET /users (admin-scoped,
  // cross-tenant), optionally filterable by ?tenant_id= server-side.
  const [dsai_users, setDsaiUsers] = useState<UserRecord[]>([]);
  const [dsai_usersLoading, setDsaiUsersLoading] = useState(false);
  const [dsai_usersError, setDsaiUsersError] = useState<string | null>(null);
  const [dsai_showCreateUser, setDsaiShowCreateUser] = useState(false);
  const [dsai_newUserEmail, setDsaiNewUserEmail] = useState("");
  const [dsai_newUserPassword, setDsaiNewUserPassword] = useState("");
  const [dsai_newUserTenant, setDsaiNewUserTenant] = useState("");
  const [dsai_newUserRole, setDsaiNewUserRole] = useState("operator");
  const [dsai_createUserError, setDsaiCreateUserError] = useState<string | null>(null);
  const [dsai_createUserBusy, setDsaiCreateUserBusy] = useState(false);

  // API Keys state — GET /auth/api-keys lists keys for the admin's own tenant
  // (prefix/name/timestamps only, never the hash); POST creates a new one.
  const [dsai_apiKeys, setDsaiApiKeys] = useState<ApiKeyRecord[]>([]);
  const [dsai_apiKeysLoading, setDsaiApiKeysLoading] = useState(false);
  const [dsai_apiKeysError, setDsaiApiKeysError] = useState<string | null>(null);
  const [dsai_showCreateApiKey, setDsaiShowCreateApiKey] = useState(false);
  const [dsai_newKeyName, setDsaiNewKeyName] = useState("");
  const [dsai_newKeyDays, setDsaiNewKeyDays] = useState(90);
  const [dsai_generatedSecret, setDsaiGeneratedSecret] = useState<string | null>(null);
  const [dsai_copiedSecret, setDsaiCopiedSecret] = useState(false);
  const [dsai_createKeyError, setDsaiCreateKeyError] = useState<string | null>(null);
  const [dsai_createKeyBusy, setDsaiCreateKeyBusy] = useState(false);

  // Verify Admin privilege
  const dsai_adminAccess = dsai_isAdmin(dsai_session);

  useEffect(() => {
    if (!dsai_adminAccess || !dsai_accessToken) return;
    let dsai_cancelled = false;
    setDsaiTenantsLoading(true);
    setDsaiTenantsError(null);

    dsai_apiGet<DsaiTenantApiRecord[]>("auth/tenants", dsai_accessToken, dsai_tenantId ?? "")
      .then((dsai_raw) => {
        if (dsai_cancelled || !dsai_raw) return;
        setDsaiTenants(dsai_raw.map(dsai_mapTenantRecord));
      })
      .catch((dsai_err: unknown) => {
        if (dsai_cancelled) return;
        setDsaiTenantsError(
          dsai_err instanceof DsaiApiError ? dsai_err.message : "Failed to load tenants"
        );
      })
      .finally(() => {
        if (!dsai_cancelled) setDsaiTenantsLoading(false);
      });

    return () => {
      dsai_cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dsai_adminAccess, dsai_accessToken]);

  useEffect(() => {
    if (!dsai_adminAccess || !dsai_accessToken) return;
    let dsai_cancelled = false;
    setDsaiUsersLoading(true);
    setDsaiUsersError(null);

    dsai_apiGet<
      { id: string; email: string; tenant_id: string; roles: string[]; created_at: string | null }[]
    >("auth/users", dsai_accessToken, dsai_tenantId ?? "")
      .then((dsai_raw) => {
        if (dsai_cancelled || !dsai_raw) return;
        setDsaiUsers(
          dsai_raw.map((dsai_u) => ({
            id: dsai_u.id,
            email: dsai_u.email,
            tenant_id: dsai_u.tenant_id,
            roles: dsai_u.roles,
            created_at: dsai_u.created_at ?? "",
          }))
        );
      })
      .catch((dsai_err: unknown) => {
        if (dsai_cancelled) return;
        setDsaiUsersError(
          dsai_err instanceof DsaiApiError ? dsai_err.message : "Failed to load tenant users"
        );
      })
      .finally(() => {
        if (!dsai_cancelled) setDsaiUsersLoading(false);
      });

    return () => {
      dsai_cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dsai_adminAccess, dsai_accessToken]);

  useEffect(() => {
    if (!dsai_adminAccess || !dsai_accessToken) return;
    let dsai_cancelled = false;
    setDsaiApiKeysLoading(true);
    setDsaiApiKeysError(null);

    dsai_apiGet<
      { id: number; name: string; prefix: string; created_at: string | null; expires_at: string | null }[]
    >("auth/auth/api-keys", dsai_accessToken, dsai_tenantId ?? "")
      .then((dsai_raw) => {
        if (dsai_cancelled || !dsai_raw) return;
        setDsaiApiKeys(
          dsai_raw.map((dsai_k) => ({
            id: dsai_k.id,
            name: dsai_k.name,
            prefix: dsai_k.prefix,
            created_at: dsai_k.created_at ?? "",
            expires_at: dsai_k.expires_at ?? "",
          }))
        );
      })
      .catch((dsai_err: unknown) => {
        if (dsai_cancelled) return;
        setDsaiApiKeysError(
          dsai_err instanceof DsaiApiError ? dsai_err.message : "Failed to load API keys"
        );
      })
      .finally(() => {
        if (!dsai_cancelled) setDsaiApiKeysLoading(false);
      });

    return () => {
      dsai_cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dsai_adminAccess, dsai_accessToken]);

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
  const dsai_handleCreateTenant = async () => {
    if (!dsai_newTenantName || !dsai_newTenantSlug || !dsai_accessToken) return;
    setDsaiCreateTenantBusy(true);
    setDsaiCreateTenantError(null);
    try {
      const dsai_created = await dsai_apiPost<DsaiTenantApiRecord>(
        "auth/tenants",
        dsai_accessToken,
        dsai_tenantId ?? "",
        {
          name: dsai_newTenantName,
          slug: dsai_newTenantSlug.toLowerCase().replace(/\s+/g, "-"),
          sector: dsai_newTenantSector,
        }
      );
      if (dsai_created) {
        setDsaiTenants((dsai_prev) => [...dsai_prev, dsai_mapTenantRecord(dsai_created)]);
        setDsaiNewTenantName("");
        setDsaiNewTenantSlug("");
        setDsaiShowCreateTenant(false);
      }
    } catch (dsai_err) {
      setDsaiCreateTenantError(
        dsai_err instanceof DsaiApiError ? dsai_err.message : "Failed to provision tenant"
      );
    } finally {
      setDsaiCreateTenantBusy(false);
    }
  };

  const dsai_toggleTenantActive = async (dsai_tenant: TenantRecord) => {
    if (!dsai_accessToken) return;
    setDsaiTogglingTenantId(dsai_tenant.id);
    setDsaiToggleTenantError(null);
    try {
      const dsai_updated = await dsai_apiPatch<DsaiTenantApiRecord>(
        `auth/tenants/${dsai_tenant.id}`,
        dsai_accessToken,
        dsai_tenantId ?? "",
        { active: !dsai_tenant.active }
      );
      if (dsai_updated) {
        const dsai_mapped = dsai_mapTenantRecord(dsai_updated);
        setDsaiTenants((dsai_prev) =>
          dsai_prev.map((t) => (t.id === dsai_tenant.id ? dsai_mapped : t))
        );
      }
    } catch (dsai_err) {
      setDsaiToggleTenantError(
        dsai_err instanceof DsaiApiError ? dsai_err.message : "Failed to update tenant status"
      );
    } finally {
      setDsaiTogglingTenantId(null);
    }
  };

  // User Handlers
  const dsai_handleCreateUser = async () => {
    if (!dsai_newUserEmail || !dsai_newUserPassword || !dsai_newUserTenant || !dsai_accessToken) return;
    setDsaiCreateUserBusy(true);
    setDsaiCreateUserError(null);
    try {
      const dsai_created = await dsai_apiPost<{
        id: string;
        email: string;
        tenant_id: string;
        roles: string[];
        created_at: string | null;
      }>(`auth/tenants/${dsai_newUserTenant}/users`, dsai_accessToken, dsai_tenantId ?? "", {
        email: dsai_newUserEmail,
        password: dsai_newUserPassword,
        role: dsai_newUserRole,
      });
      if (dsai_created) {
        setDsaiUsers((dsai_prev) => [
          ...dsai_prev,
          {
            id: dsai_created.id,
            email: dsai_created.email,
            tenant_id: dsai_created.tenant_id,
            roles: dsai_created.roles,
            created_at: dsai_created.created_at ?? new Date().toISOString().split("T")[0],
          },
        ]);
        setDsaiNewUserEmail("");
        setDsaiNewUserPassword("");
        setDsaiShowCreateUser(false);
      }
    } catch (dsai_err) {
      setDsaiCreateUserError(
        dsai_err instanceof DsaiApiError ? dsai_err.message : "Failed to provision user"
      );
    } finally {
      setDsaiCreateUserBusy(false);
    }
  };

  // API Key Handlers — calls the real POST /auth/api-keys endpoint, scoped to
  // the admin's own tenant, with an Argon2id hash stored server-side.
  const dsai_handleCreateApiKey = async () => {
    if (!dsai_newKeyName || !dsai_accessToken) return;
    setDsaiCreateKeyBusy(true);
    setDsaiCreateKeyError(null);
    try {
      const dsai_created = await dsai_apiPost<{
        id: number;
        prefix: string;
        key: string;
        name: string;
        permissions: string[];
        expires_at: string;
      }>("auth/auth/api-keys", dsai_accessToken, dsai_tenantId ?? "", {
        name: dsai_newKeyName,
        permissions: [],
        expires_in_days: dsai_newKeyDays,
      });

      if (dsai_created) {
        const dsai_newRecord: ApiKeyRecord = {
          id: dsai_created.id,
          name: dsai_created.name,
          prefix: dsai_created.prefix,
          created_at: new Date().toISOString().split("T")[0],
          expires_at: dsai_created.expires_at.split("T")[0],
        };
        setDsaiApiKeys((dsai_prev) => [...dsai_prev, dsai_newRecord]);
        setDsaiGeneratedSecret(dsai_created.key);
        setDsaiNewKeyName("");
        setDsaiShowCreateApiKey(false);
      }
    } catch (dsai_err) {
      setDsaiCreateKeyError(
        dsai_err instanceof DsaiApiError ? dsai_err.message : "Failed to generate API key"
      );
    } finally {
      setDsaiCreateKeyBusy(false);
    }
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

          {dsai_tenantsError && dsai_tenants.length > 0 && (
            <p className="text-xs text-amber-400">
              Could not refresh the full tenant list from AuthService ({dsai_tenantsError}) — showing
              tenants provisioned in this session only.
            </p>
          )}
          {dsai_toggleTenantError && (
            <p className="text-xs text-red-400">{dsai_toggleTenantError}</p>
          )}

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
                {dsai_tenantsLoading ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-8 text-center text-slate-400">
                      <Loader2 className="w-4 h-4 inline animate-spin mr-2" />
                      Loading tenants from AuthService...
                    </td>
                  </tr>
                ) : dsai_tenantsError && dsai_tenants.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-8 text-center text-red-400">
                      {dsai_tenantsError}
                    </td>
                  </tr>
                ) : dsai_tenants.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-8 text-center text-slate-500">
                      No tenants provisioned yet.
                    </td>
                  </tr>
                ) : (
                  dsai_tenants.map((dsai_tenant) => (
                    <tr key={dsai_tenant.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-6 py-4 font-semibold text-white">{dsai_tenant.name}</td>
                      <td className="px-6 py-4 font-mono text-slate-400">{dsai_tenant.slug}</td>
                      <td className="px-6 py-4">
                        <SectorBadge dsai_sector={dsai_tenant.sector} dsai_size="sm" />
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
                          onClick={() => dsai_toggleTenantActive(dsai_tenant)}
                          disabled={dsai_togglingTenantId === dsai_tenant.id}
                          className="text-xs text-slate-400 hover:text-white inline-flex items-center gap-1 font-medium disabled:opacity-50"
                        >
                          {dsai_togglingTenantId === dsai_tenant.id ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : dsai_tenant.active ? (
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
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Quota & Resource Usage Overview */}
          <QuotaUsageDisplay
            dsai_informational={true}
            dsai_title="Multi-Tenant Resource Quotas & Allocation"
          />
        </div>
      )}

      {/* Tab 2: User Provisioning */}
      {dsai_activeTab === "users" && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-bold text-white">Platform Users & Roles</h2>
              <p className="text-xs text-slate-400">
                Live from AuthService via a single cross-tenant listing call.
              </p>
            </div>
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
                {dsai_usersLoading ? (
                  <tr>
                    <td colSpan={4} className="px-6 py-8 text-center text-slate-400">
                      <Loader2 className="w-4 h-4 inline animate-spin mr-2" />
                      Loading users from AuthService...
                    </td>
                  </tr>
                ) : dsai_usersError && dsai_users.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-6 py-8 text-center text-red-400">
                      {dsai_usersError}
                    </td>
                  </tr>
                ) : dsai_users.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-6 py-8 text-center text-slate-500">
                      No users provisioned yet.
                    </td>
                  </tr>
                ) : (
                  dsai_users.map((dsai_user) => (
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
                  ))
                )}
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
                Notice: Secret keys are hashed via Argon2id upon generation and shown only once. Revocation
                is scheduled for a future release.
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
                {dsai_apiKeysLoading ? (
                  <tr>
                    <td colSpan={4} className="px-6 py-8 text-center text-slate-400">
                      <Loader2 className="w-4 h-4 inline animate-spin mr-2" />
                      Loading API keys from AuthService...
                    </td>
                  </tr>
                ) : dsai_apiKeysError && dsai_apiKeys.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-6 py-8 text-center text-red-400">
                      {dsai_apiKeysError}
                    </td>
                  </tr>
                ) : dsai_apiKeys.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-6 py-8 text-center text-slate-500">
                      No API keys generated yet.
                    </td>
                  </tr>
                ) : (
                  dsai_apiKeys.map((dsai_key) => (
                    <tr key={dsai_key.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-6 py-4 font-semibold text-white">{dsai_key.name}</td>
                      <td className="px-6 py-4 font-mono text-slate-400">{dsai_key.prefix}••••••••</td>
                      <td className="px-6 py-4 text-slate-500">{dsai_key.created_at}</td>
                      <td className="px-6 py-4 text-slate-400">{dsai_key.expires_at}</td>
                    </tr>
                  ))
                )}
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
            {dsai_createTenantError && (
              <p className="text-xs text-red-400">{dsai_createTenantError}</p>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setDsaiShowCreateTenant(false)}
                className="px-4 py-2 bg-slate-800 text-slate-300 rounded-lg text-xs"
              >
                Cancel
              </button>
              <button
                onClick={dsai_handleCreateTenant}
                disabled={!dsai_newTenantName || !dsai_newTenantSlug || dsai_createTenantBusy}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 disabled:opacity-50 text-white rounded-lg text-xs font-semibold"
              >
                {dsai_createTenantBusy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
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
                  <option value="" disabled>
                    Select a tenant…
                  </option>
                  {dsai_tenants.map((t) => (
                    <option key={t.id} value={t.id}>
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
            {dsai_createUserError && (
              <p className="text-xs text-red-400">{dsai_createUserError}</p>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setDsaiShowCreateUser(false)}
                className="px-4 py-2 bg-slate-800 text-slate-300 rounded-lg text-xs"
              >
                Cancel
              </button>
              <button
                onClick={dsai_handleCreateUser}
                disabled={!dsai_newUserEmail || !dsai_newUserPassword || !dsai_newUserTenant || dsai_createUserBusy}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 disabled:opacity-50 text-white rounded-lg text-xs font-semibold"
              >
                {dsai_createUserBusy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
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
            {dsai_createKeyError && (
              <p className="text-xs text-red-400">{dsai_createKeyError}</p>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setDsaiShowCreateApiKey(false)}
                className="px-4 py-2 bg-slate-800 text-slate-300 rounded-lg text-xs"
              >
                Cancel
              </button>
              <button
                onClick={dsai_handleCreateApiKey}
                disabled={!dsai_newKeyName || dsai_createKeyBusy}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 disabled:opacity-50 text-white rounded-lg text-xs font-semibold"
              >
                {dsai_createKeyBusy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
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
