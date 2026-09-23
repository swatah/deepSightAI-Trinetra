import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import CommercialDashboard from "../../app/dashboard/commercial/page";

// Mock canvas 2D context for jsdom
beforeAll(() => {
  HTMLCanvasElement.prototype.getContext = jest.fn().mockReturnValue({
    clearRect: jest.fn(),
    fillRect: jest.fn(),
    createRadialGradient: jest.fn().mockReturnValue({
      addColorStop: jest.fn(),
    }),
    beginPath: jest.fn(),
    arc: jest.fn(),
    fill: jest.fn(),
  }) as any;
});

describe("Commercial & Retail Dashboard Suite (#50)", () => {
  it("renders commercial dashboard title and P2 Beta badge", () => {
    render(<CommercialDashboard />);
    expect(screen.getByText(/Commercial & Retail Analytics Dashboard/i)).toBeInTheDocument();
    expect(screen.getByText(/P2 Beta • ML In Training Mode/i)).toBeInTheDocument();
  });

  it("displays key store traffic metrics", () => {
    render(<CommercialDashboard />);
    expect(screen.getByText("Today's Total Foot Traffic")).toBeInTheDocument();
    expect(screen.getByText("Average Dwell Time")).toBeInTheDocument();
    expect(screen.getByText("Store Conversion Rate")).toBeInTheDocument();
  });

  it("toggles heatmap visibility layer on button click", () => {
    render(<CommercialDashboard />);
    const toggleButton = screen.getByText("Heatmap: Visible");
    expect(toggleButton).toBeInTheDocument();

    fireEvent.click(toggleButton);
    expect(screen.getByText("Heatmap: Hidden")).toBeInTheDocument();
  });

  it("displays camera selector dropdown for heatmap feed", () => {
    render(<CommercialDashboard />);
    expect(screen.getByText("Main Store Entrance")).toBeInTheDocument();
  });
});
