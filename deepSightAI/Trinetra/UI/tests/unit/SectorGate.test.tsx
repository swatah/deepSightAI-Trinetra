import React from "react";
import { render, screen } from "@testing-library/react";
import { useSession } from "next-auth/react";
import { useTenant } from "@/hooks/useTenant";
import { SectorGate } from "@/components/tenant/SectorGate";

jest.mock("next-auth/react", () => ({
  useSession: jest.fn(),
}));

jest.mock("@/hooks/useTenant", () => ({
  useTenant: jest.fn(),
}));

const mockUseSession = useSession as jest.Mock;
const mockUseTenant = useTenant as jest.Mock;

describe("SectorGate (#49/#50/#51 access control)", () => {
  it("shows a loading state while the tenant context is resolving", () => {
    mockUseSession.mockReturnValue({ data: null, status: "loading" });
    mockUseTenant.mockReturnValue({ dsai_sector: null, dsai_isLoading: true });

    render(
      <SectorGate dsai_requiredSector="law_enforcement" dsai_label="Law Enforcement">
        <div>Protected Content</div>
      </SectorGate>
    );

    expect(screen.getByText(/Loading tenant context/i)).toBeInTheDocument();
    expect(screen.queryByText("Protected Content")).not.toBeInTheDocument();
  });

  it("blocks a non-admin user whose tenant sector does not match", () => {
    mockUseSession.mockReturnValue({
      data: { user: { name: "Retail Operator" }, dsai_roles: ["operator"] },
      status: "authenticated",
    });
    mockUseTenant.mockReturnValue({ dsai_sector: "commercial", dsai_isLoading: false });

    render(
      <SectorGate dsai_requiredSector="law_enforcement" dsai_label="Law Enforcement">
        <div>Protected Content</div>
      </SectorGate>
    );

    expect(screen.getByText(/403 Sector Access Restricted/i)).toBeInTheDocument();
    expect(screen.queryByText("Protected Content")).not.toBeInTheDocument();
  });

  it("allows a non-admin user whose tenant sector matches", () => {
    mockUseSession.mockReturnValue({
      data: { user: { name: "Patrol Officer" }, dsai_roles: ["operator"] },
      status: "authenticated",
    });
    mockUseTenant.mockReturnValue({ dsai_sector: "law_enforcement", dsai_isLoading: false });

    render(
      <SectorGate dsai_requiredSector="law_enforcement" dsai_label="Law Enforcement">
        <div>Protected Content</div>
      </SectorGate>
    );

    expect(screen.getByText("Protected Content")).toBeInTheDocument();
    expect(screen.queryByText(/403 Sector Access Restricted/i)).not.toBeInTheDocument();
  });

  it("allows a platform admin regardless of their tenant's sector", () => {
    mockUseSession.mockReturnValue({
      data: { user: { name: "Super Admin" }, dsai_roles: ["admin"] },
      status: "authenticated",
    });
    mockUseTenant.mockReturnValue({ dsai_sector: "commercial", dsai_isLoading: false });

    render(
      <SectorGate dsai_requiredSector="law_enforcement" dsai_label="Law Enforcement">
        <div>Protected Content</div>
      </SectorGate>
    );

    expect(screen.getByText("Protected Content")).toBeInTheDocument();
    expect(screen.queryByText(/403 Sector Access Restricted/i)).not.toBeInTheDocument();
  });
});
