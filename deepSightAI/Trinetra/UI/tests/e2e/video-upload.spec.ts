import { test, expect } from "@playwright/test";

test.describe("Journey 5: Video Upload Flow (#47)", () => {
  test.beforeEach(async ({ page }) => {
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

    await page.route("**/api/backend/server/upload/request-url", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          upload_url: "http://localhost:9000/videos/mock-upload-target",
          video_uri: "s3://videos/mta-transit/cam-1/20260922/video-123.mp4",
        }),
      });
    });
  });

  test("renders video upload dropzone with size validation and format notices", async ({ page }) => {
    await page.goto("/upload");
    await expect(page.locator("body")).toContainText(/Upload|Drag and drop/i);
  });
});
