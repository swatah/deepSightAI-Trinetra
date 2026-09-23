import {
  dsai_hasRole,
  dsai_isAdmin,
  dsai_isOperator,
  dsai_isViewer,
  dsai_getRoles,
  dsai_getTenantId,
} from "../../lib/auth/dsai_rbac";

describe("RBAC Helper Suite (dsai_rbac / #46)", () => {
  const adminSession = {
    user: { name: "Admin Officer" },
    expires: "2026-10-01",
    dsai_roles: ["admin", "operator"],
    dsai_tenantId: "police-dept-1",
  } as any;

  const operatorSession = {
    user: { name: "Operator Dave" },
    expires: "2026-10-01",
    dsai_roles: ["operator"],
    dsai_tenantId: "transit-authority",
  } as any;

  const viewerSession = {
    user: { name: "Auditor Jane" },
    expires: "2026-10-01",
    dsai_roles: ["viewer"],
    dsai_tenantId: "retail-corp",
  } as any;

  it("correctly identifies admin privileges via roles.includes('admin')", () => {
    expect(dsai_isAdmin(adminSession)).toBe(true);
    expect(dsai_isAdmin(operatorSession)).toBe(false);
    expect(dsai_isAdmin(viewerSession)).toBe(false);
    expect(dsai_isAdmin(null)).toBe(false);
  });

  it("correctly identifies operator role", () => {
    expect(dsai_isOperator(adminSession)).toBe(true);
    expect(dsai_isOperator(operatorSession)).toBe(true);
    expect(dsai_isOperator(viewerSession)).toBe(false);
  });

  it("correctly identifies viewer role", () => {
    expect(dsai_isViewer(adminSession)).toBe(false);
    expect(dsai_isViewer(operatorSession)).toBe(false);
    expect(dsai_isViewer(viewerSession)).toBe(true);
  });

  it("verifies absence of permissions array and evaluates role membership only", () => {
    // AuthService strictly produces roles, never permissions
    expect((adminSession as any).permissions).toBeUndefined();
    expect(dsai_hasRole(adminSession, "admin")).toBe(true);
    expect(dsai_hasRole(adminSession, "superadmin")).toBe(false);
  });

  it("retrieves tenant_id and roles safely from session", () => {
    expect(dsai_getTenantId(adminSession)).toBe("police-dept-1");
    expect(dsai_getTenantId(null)).toBeNull();
    expect(dsai_getRoles(adminSession)).toEqual(["admin", "operator"]);
    expect(dsai_getRoles(null)).toEqual([]);
  });
});
