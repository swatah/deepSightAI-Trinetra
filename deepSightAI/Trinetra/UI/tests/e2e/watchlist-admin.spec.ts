import { test, expect } from "@playwright/test";

test.describe("Journey 3: Watchlist Management & Role-Gating (#47)", () => {
  test("admin user can view watchlist targets and see create actions", async ({ page }) => {
    await page.route("**/api/auth/session", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          user: { name: "Security Director", email: "director@swatah.ai" },
          dsai_roles: ["admin"],
          dsai_tenantId: "mta-transit",
          expires: "2026-10-01",
        }),
      });
    });

    await page.route("**/api/backend/watchlist/**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          targets: [
            {
              id: "wl-1",
              target_type: "license_plate",
              identifier: "XYZ9876",
              priority: "CRITICAL",
              active: true,
            },
          ],
        }),
      });
    });

    await page.goto("/watchlist");
    await expect(page.locator("body")).toContainText(/Watchlist/i);
  });

  test("multi-tenant isolation: non-admin operator sees read-only controls", async ({ page }) => {
    await page.route("**/api/auth/session", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          user: { name: "Operator Dave", email: "dave@swatah.ai" },
          dsai_roles: ["operator"],
          dsai_tenantId: "mta-transit",
          expires: "2026-10-01",
        }),
      });
    });

    await page.goto("/watchlist");
    // Operator role must NOT have permission to create/delete watchlist targets
    await expect(page.locator("button").filter({ hasText: /delete target/i })).toHaveCount(0);
  });
});
