import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { useSession } from "next-auth/react";
import LogisticsDashboard from "../../app/dashboard/logistics/page";

jest.mock("next-auth/react", () => ({
  useSession: jest.fn(),
}));

// Admin bypasses the sector gate (SectorGate allows admins regardless of
// tenant sector) so these tests can exercise dashboard content directly.
const mockUseSession = useSession as jest.Mock;
beforeEach(() => {
  mockUseSession.mockReturnValue({
    data: { user: { name: "Super Admin" }, dsai_roles: ["admin"] },
    status: "authenticated",
  });
});

describe("Logistics & Warehouse Dashboard Suite (#51)", () => {
  it("renders logistics dashboard header and P2 Beta badge", () => {
    render(<LogisticsDashboard />);
    expect(screen.getByText(/Logistics & Warehouse Operations Dashboard/i)).toBeInTheDocument();
    expect(screen.getByText(/P2 Beta • ML In Training Mode/i)).toBeInTheDocument();
  });

  it("renders PPE compliance gauge and sub-breakdown scores", () => {
    render(<LogisticsDashboard />);
    expect(screen.getByText("PPE Compliance Gauge")).toBeInTheDocument();
    expect(screen.getAllByText("94%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Hard Hat Protection")).toBeInTheDocument();
    expect(screen.getByText("High-Visibility Vests")).toBeInTheDocument();
  });

  it("triggers safety threshold alert when compliance falls below 90%", () => {
    render(<LogisticsDashboard />);
    expect(screen.queryByText(/CRITICAL SAFETY THRESHOLD ALERT/i)).not.toBeInTheDocument();

    const slider = screen.getByRole("slider");
    fireEvent.change(slider, { target: { value: "85" } });

    expect(screen.getByText(/CRITICAL SAFETY THRESHOLD ALERT/i)).toBeInTheDocument();
    expect(screen.getAllByText("85%").length).toBeGreaterThanOrEqual(1);
  });

  it("renders dock door status grid with carriers and durations", () => {
    render(<LogisticsDashboard />);
    expect(screen.getByText("Inbound Bay 1")).toBeInTheDocument();
    expect(screen.getByText("DHL Express")).toBeInTheDocument();
    expect(screen.getByText("Outbound Bay 3")).toBeInTheDocument();
  });

  it("renders proximity violation safety feed", () => {
    render(<LogisticsDashboard />);
    expect(screen.getByText(/Forklift \/ Pedestrian Proximity Violation/i)).toBeInTheDocument();
    expect(screen.getByText(/CAM-AISLE-04/i)).toBeInTheDocument();
  });
});
