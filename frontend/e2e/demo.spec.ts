import { expect, test } from "@playwright/test";

test("demo user can visit every Phase 1 screen", async ({ page }) => {
  test.skip(process.env.PLAYWRIGHT_SKIP_DEMO === "1", "Explicitly skipped with PLAYWRIGHT_SKIP_DEMO=1");
  await page.goto("/login");
  const demoButton = page.getByRole("button", { name: "Explore the demo" });
  await expect(demoButton).toBeVisible();
  await demoButton.click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Net worth", { exact: true })).toBeVisible();
  for (const destination of ["Accounts", "Transactions", "Settings"]) {
    await page.getByRole("link", { name: destination }).first().click();
    await expect(page.getByRole("heading", { name: destination, exact: true })).toBeVisible();
  }
});
