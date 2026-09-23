import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { DsaiHeader } from "../../components/DsaiHeader";
import { useSession } from "next-auth/react";
import { usePathname } from "next/navigation";

jest.mock("next-auth/react", () => ({
  useSession: jest.fn(),
}));

jest.mock("next/navigation", () => ({
  usePathname: jest.fn(),
}));

describe("Mobile Responsive Header & Touch Targets Suite (#54)", () => {
  beforeEach(() => {
    (useSession as jest.Mock).mockReturnValue({
      data: {
        user: { name: "Officer Smith" },
        dsai_tenantId: "mta-transit",
        dsai_roles: ["operator"],
      },
    });
    (usePathname as jest.Mock).mockReturnValue("/dashboard");
  });

  it("renders mobile toggle button with accessible aria-label", () => {
    render(<DsaiHeader />);
    const toggleBtn = screen.getByLabelText(/Toggle navigation drawer/i);
    expect(toggleBtn).toBeInTheDocument();
    expect(toggleBtn).toHaveAttribute("aria-expanded", "false");
  });

  it("opens mobile navigation drawer with touch-compliant links on click", () => {
    render(<DsaiHeader />);
    const toggleBtn = screen.getByLabelText(/Toggle navigation drawer/i);
    fireEvent.click(toggleBtn);

    expect(toggleBtn).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByText("Officer Smith").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Scope: mta-transit/i)).toBeInTheDocument();

    const mobileSearchLink = screen.getAllByRole("link", { name: /Search/i })[1];
    expect(mobileSearchLink).toBeInTheDocument();

    fireEvent.click(mobileSearchLink);
    expect(toggleBtn).toHaveAttribute("aria-expanded", "false");
  });
});
