import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import AdminPage from "../../app/admin/page";
import { useSession } from "next-auth/react";
import * as dsaiClient from "@/lib/api/dsai_client";

jest.mock("next-auth/react", () => ({
  useSession: jest.fn(),
}));

jest.mock("@/lib/api/dsai_client", () => ({
  ...jest.requireActual("@/lib/api/dsai_client"),
  dsai_apiGet: jest.fn(),
  dsai_apiPost: jest.fn(),
  dsai_apiPatch: jest.fn(),
}));

describe("Super-Admin Panel Suite (#53)", () => {
  const mockUseSession = useSession as jest.Mock;
  const dsai_apiGetMock = dsaiClient.dsai_apiGet as jest.Mock;

  beforeEach(() => {
    dsai_apiGetMock.mockReset();
    dsai_apiGetMock.mockResolvedValue([]);
  });

  it("blocks non-admin users with 403 Forbidden screen", () => {
    mockUseSession.mockReturnValue({
      data: {
        user: { name: "Operator Dave" },
        dsai_roles: ["operator"],
      },
      status: "authenticated",
    });

    render(<AdminPage />);
    expect(screen.getByText(/403 Super-Admin Access Required/i)).toBeInTheDocument();
  });

  it("renders Super-Admin panel and tabs for admin users", () => {
    mockUseSession.mockReturnValue({
      data: {
        user: { name: "Super Admin" },
        dsai_roles: ["admin"],
      },
      status: "authenticated",
    });

    render(<AdminPage />);
    expect(screen.getByText("Super-Admin Platform Panel")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Tenants/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Users/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /API Keys/i })).toBeInTheDocument();
  });

  it("displays empty tenant directory (no accessToken → no fetch) and opens provision modal", () => {
    mockUseSession.mockReturnValue({
      data: {
        user: { name: "Super Admin" },
        dsai_roles: ["admin"],
      },
      status: "authenticated",
    });

    render(<AdminPage />);
    expect(screen.getByText("No tenants provisioned yet.")).toBeInTheDocument();

    const provisionBtn = screen.getByRole("button", { name: /Provision Tenant/i });
    fireEvent.click(provisionBtn);
    expect(screen.getByText("Provision New Platform Tenant")).toBeInTheDocument();
  });

  it("switches to API Keys tab and shows generation modal", () => {
    mockUseSession.mockReturnValue({
      data: {
        user: { name: "Super Admin" },
        dsai_roles: ["admin"],
      },
      status: "authenticated",
    });

    render(<AdminPage />);
    const apiKeysTab = screen.getByRole("button", { name: /API Keys/i });
    fireEvent.click(apiKeysTab);

    expect(screen.getByText("Programmatic API Keys")).toBeInTheDocument();
    expect(screen.getByText("No API keys generated yet.")).toBeInTheDocument();

    const generateBtn = screen.getByRole("button", { name: /Generate API Key/i });
    fireEvent.click(generateBtn);
    expect(screen.getByText("Generate Programmatic API Key")).toBeInTheDocument();
  });

  it("provisions a tenant via a real POST to /auth/tenants, not local-only state", async () => {
    mockUseSession.mockReturnValue({
      data: {
        user: { name: "Super Admin" },
        dsai_roles: ["admin"],
        dsai_accessToken: "test-token",
        dsai_tenantId: "1",
      },
      status: "authenticated",
    });

    const dsai_apiPostMock = dsaiClient.dsai_apiPost as jest.Mock;
    dsai_apiPostMock.mockResolvedValue({
      id: "9",
      name: "Test Tenant",
      slug: "test-tenant",
      active: true,
      created_at: "2026-09-24T00:00:00Z",
      plugin_config: { sector: "commercial" },
    });

    render(<AdminPage />);

    fireEvent.click(screen.getByRole("button", { name: /Provision Tenant/i }));
    fireEvent.change(screen.getByPlaceholderText(/Gotham City Police Department/i), {
      target: { value: "Test Tenant" },
    });
    fireEvent.change(screen.getByPlaceholderText(/gcpd/i), { target: { value: "test-tenant" } });
    const dsai_provisionButtons = screen.getAllByRole("button", { name: /^Provision Tenant$/i });
    fireEvent.click(dsai_provisionButtons[dsai_provisionButtons.length - 1]);

    await screen.findByText("Test Tenant");
    expect(dsai_apiPostMock).toHaveBeenCalledWith(
      "auth/tenants",
      "test-token",
      "1",
      expect.objectContaining({ name: "Test Tenant", slug: "test-tenant" })
    );

    dsai_apiPostMock.mockReset();
  });

  it("suspends a tenant via a real PATCH to /auth/tenants/{id}, not local-only state", async () => {
    mockUseSession.mockReturnValue({
      data: {
        user: { name: "Super Admin" },
        dsai_roles: ["admin"],
        dsai_accessToken: "test-token",
        dsai_tenantId: "1",
      },
      status: "authenticated",
    });

    dsai_apiGetMock.mockImplementation((dsai_path: string) => {
      if (dsai_path === "auth/tenants") {
        return Promise.resolve([
          {
            id: "9",
            name: "Test Tenant",
            slug: "test-tenant",
            active: true,
            created_at: "2026-09-24T00:00:00Z",
            plugin_config: { sector: "commercial" },
          },
        ]);
      }
      return Promise.resolve([]);
    });

    const dsai_apiPatchMock = dsaiClient.dsai_apiPatch as jest.Mock;
    dsai_apiPatchMock.mockResolvedValue({
      id: "9",
      name: "Test Tenant",
      slug: "test-tenant",
      active: false,
      created_at: "2026-09-24T00:00:00Z",
      plugin_config: { sector: "commercial" },
    });

    render(<AdminPage />);

    await screen.findByText("Test Tenant");
    fireEvent.click(screen.getByRole("button", { name: /Suspend/i }));

    await screen.findByRole("button", { name: /Activate/i });
    expect(dsai_apiPatchMock).toHaveBeenCalledWith(
      "auth/tenants/9",
      "test-token",
      "1",
      { active: false }
    );
    expect(screen.getByText("Suspended")).toBeInTheDocument();

    dsai_apiPatchMock.mockReset();
  });

  it("loads the Users tab via a single GET to /auth/users, not one request per tenant", async () => {
    mockUseSession.mockReturnValue({
      data: {
        user: { name: "Super Admin" },
        dsai_roles: ["admin"],
        dsai_accessToken: "test-token",
        dsai_tenantId: "1",
      },
      status: "authenticated",
    });

    dsai_apiGetMock.mockImplementation((dsai_path: string) => {
      if (dsai_path === "auth/tenants") {
        return Promise.resolve([
          { id: "9", name: "Tenant Nine", slug: "tenant-nine", active: true, created_at: "2026-09-24T00:00:00Z", plugin_config: {} },
          { id: "10", name: "Tenant Ten", slug: "tenant-ten", active: true, created_at: "2026-09-24T00:00:00Z", plugin_config: {} },
        ]);
      }
      if (dsai_path === "auth/users") {
        return Promise.resolve([
          { id: "1", email: "member@nine.example", tenant_id: "9", roles: ["viewer"], created_at: "2026-09-24T00:00:00Z" },
        ]);
      }
      return Promise.resolve([]);
    });

    render(<AdminPage />);

    fireEvent.click(screen.getByRole("button", { name: /^Users$/i }));

    await screen.findByText("member@nine.example");
    expect(dsai_apiGetMock).toHaveBeenCalledWith("auth/users", "test-token", "1");
    expect(dsai_apiGetMock).not.toHaveBeenCalledWith("auth/tenants/9/users", "test-token", "1");
    expect(dsai_apiGetMock).not.toHaveBeenCalledWith("auth/tenants/10/users", "test-token", "1");
  });
});
