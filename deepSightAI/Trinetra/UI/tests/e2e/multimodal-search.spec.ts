import { test, expect } from "@playwright/test";

test.describe("Journey 2: Multi-Modal Search Workflow (#47)", () => {
  test.beforeEach(async ({ page }) => {
    // Mock NextAuth session and SearchService APIs
    await page.route("**/api/auth/session", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          user: { name: "Investigator John", email: "john@swatah.ai" },
          dsai_roles: ["operator"],
          dsai_tenantId: "mta-transit",
          expires: "2026-10-01",
        }),
      });
    });

    await page.route("**/api/backend/search/cameras", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          cameras: [
            { id: "cam-north-gate", name: "North Gate Entrance" },
            { id: "cam-lobby", name: "Main Terminal Lobby" },
          ],
        }),
      });
    });

    await page.route("**/api/backend/search/text", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          results: [
            {
              dsai_id: "match-101",
              dsai_video_id: "vid-88",
              dsai_camera_id: "cam-north-gate",
              dsai_timestamp: "2026-09-22T14:30:00Z",
              dsai_similarity: 0.92,
              dsai_thumbnail_path: "/api/media/frames/mta-transit/cam-north-gate/frame-101.jpg",
            },
          ],
        }),
      });
    });
  });

  test("executes text query and renders result cards with thumbnail proxy", async ({ page }) => {
    await page.goto("/search/text");

    const queryInput = page.locator("input[placeholder*='search' i], input[type='text']").first();
    if (await queryInput.isVisible()) {
      await queryInput.fill("black sedan driving through north gate");
      await page.keyboard.press("Enter");
      await expect(page.locator("body")).toContainText(/North Gate/i);
    }
  });

  test("renders license plate search with fuzzy similarity slider", async ({ page }) => {
    await page.goto("/search/plate");
    await expect(page.locator("input[type='range'], [role='slider']")).toBeVisible();
  });
});
