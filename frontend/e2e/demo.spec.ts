import { expect, test } from "@playwright/test";

const destinations = [
  { link: "Dashboard", heading: "Dashboard" },
  { link: "Accounts", heading: "Accounts" },
  { link: "Transactions", heading: "Transactions" },
  { link: "Budget", heading: "Budget" },
  { link: "Plan", heading: "Plan" },
  { link: "Calendar", heading: "Financial calendar" },
  { link: "Insights", heading: "Insights" },
  { link: "Reports", heading: "Reports" },
  { link: "Trends", heading: "Trends" },
  { link: "Settings", heading: "Settings" },
] as const;

test("demo user can lazy-load every core Phase 5 workspace", async ({ page }) => {
  test.skip(process.env.PLAYWRIGHT_SKIP_DEMO === "1", "Explicitly skipped with PLAYWRIGHT_SKIP_DEMO=1");
  await page.goto("/login");
  const demoButton = page.getByRole("button", { name: "Explore the demo" });
  await expect(demoButton).toBeVisible();
  await demoButton.click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
  await expect(page.getByText("Net worth", { exact: true })).toBeVisible();

  for (const destination of destinations.slice(1)) {
    const mobileMenuButton = page.getByRole("button", { name: "Open navigation" });
    if (await mobileMenuButton.isVisible()) await mobileMenuButton.click();
    const primaryNavigation = page.locator('nav[aria-label="Primary navigation"]:visible');
    await primaryNavigation.getByRole("link", { name: destination.link, exact: true }).click();
    await expect(page.getByRole("heading", { name: destination.heading, exact: true })).toBeVisible();
  }

  await page.goto("/recurring");
  await expect(page.getByRole("heading", { name: "Financial calendar", exact: true })).toBeVisible();
});
