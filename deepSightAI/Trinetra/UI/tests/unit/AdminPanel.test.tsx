import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import AdminPage from "../../app/admin/page";
import { useSession } from "next-auth/react";

jest.mock("next-auth/react", () => ({
  useSession: jest.fn(),
}));

describe("Super-Admin Panel Suite (#53)", () => {
  const mockUseSession = useSession as jest.Mock;

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

  it("displays tenant directory and opens provision modal", () => {
    mockUseSession.mockReturnValue({
      data: {
        user: { name: "Super Admin" },
        dsai_roles: ["admin"],
      },
      status: "authenticated",
    });

    render(<AdminPage />);
    expect(screen.getByText("Metropolitan Transit Authority")).toBeInTheDocument();

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
    expect(screen.getByText(/Edge Camera Stream Ingest Key/i)).toBeInTheDocument();
  });
});
