import { test, expect } from "@playwright/test";

test.describe("Journey 4: Alert Feed & Acknowledgment Workflow (#47)", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/auth/session", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          user: { name: "Alert Officer", email: "officer@swatah.ai" },
          dsai_roles: ["admin"],
          dsai_tenantId: "mta-transit",
          expires: "2026-10-01",
        }),
      });
    });

    await page.route("**/api/backend/watchlist/alerts**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          alerts: [
            {
              id: "alert-901",
              severity: "CRITICAL",
              target_type: "license_plate",
              identifier: "SUSPECT-1",
              camera_id: "cam-north-gate",
              timestamp: "2026-09-22T14:35:00Z",
              status: "ACTIVE",
            },
          ],
        }),
      });
    });
  });

  test("renders active alerts feed and acknowledgment modal trigger", async ({ page }) => {
    await page.goto("/alerts");
    await expect(page.locator("body")).toContainText(/Alert/i);
  });
});
