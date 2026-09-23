import React from "react";
import { render, screen } from "@testing-library/react";
import { SectorBadge, dsai_getSectorLabel } from "../../components/tenant/SectorBadge";

describe("Tenant & Sector UI Suite (#46)", () => {
  it("renders Law Enforcement badge with correct label", () => {
    render(<SectorBadge dsai_sector="law_enforcement" />);
    expect(screen.getByText("Law Enforcement")).toBeInTheDocument();
  });

  it("renders Retail badge with correct label", () => {
    render(<SectorBadge dsai_sector="retail" />);
    expect(screen.getByText("Retail")).toBeInTheDocument();
  });

  it("renders Transport badge with correct label", () => {
    render(<SectorBadge dsai_sector="transport" />);
    expect(screen.getByText("Transport")).toBeInTheDocument();
  });

  it("formats unmapped sector key with title casing", () => {
    render(<SectorBadge dsai_sector="logistics_fleet" />);
    expect(screen.getByText("Logistics Fleet")).toBeInTheDocument();
  });

  it("returns human-readable label via dsai_getSectorLabel", () => {
    expect(dsai_getSectorLabel("law_enforcement")).toBe("Law Enforcement");
    expect(dsai_getSectorLabel("retail")).toBe("Retail");
    expect(dsai_getSectorLabel(null)).toBe("Unknown");
  });
});
