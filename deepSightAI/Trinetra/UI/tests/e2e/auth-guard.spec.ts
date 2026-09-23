import { test, expect } from "@playwright/test";

test.describe("Journey 1: Login & Route Guarding (#47)", () => {
  test("anonymous access to protected /search redirects to /login", async ({ page }) => {
    await page.goto("/search");
    await expect(page).toHaveURL(/\/login\?callbackUrl=%2Fsearch/);
    await expect(page.locator("input[type='email'], input[name='email']")).toBeVisible();
  });

  test("anonymous access to admin-only route redirects to /login", async ({ page }) => {
    await page.goto("/admin");
    await expect(page).toHaveURL(/\/login\?callbackUrl=%2Fadmin/);
  });

  test("login form renders with enterprise branding, email, and password fields", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator("h1, h2, h3").filter({ hasText: /Trinetra|Sign in/i })).toBeVisible();
    await expect(page.locator("input[type='password']")).toBeVisible();
    await expect(page.locator("button[type='submit']")).toBeVisible();
  });
});
