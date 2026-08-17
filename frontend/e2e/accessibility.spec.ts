import axe from "axe-core";
import { expect, test, type Page } from "@playwright/test";

async function loginDemo(page: Page) {
  await page.goto("/login");
  const demoButton = page.getByRole("button", { name: "Explore the demo" });
  await expect(demoButton).toBeVisible();
  await demoButton.click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
}

async function seriousAccessibilityViolations(page: Page) {
  await page.addScriptTag({ content: axe.source });
  const results = await page.evaluate(async () => {
    const browserAxe = (window as unknown as { axe: typeof import("axe-core") }).axe;
    return browserAxe.run(document, {
      resultTypes: ["violations"],
      rules: {
        "region": { enabled: false },
      },
    });
  });
  return results.violations.filter((violation) =>
    violation.impact === "serious" || violation.impact === "critical"
  );
}

test("Phase 5 primary analytics workspaces have no serious axe violations", async ({ page }) => {
  test.skip(process.env.PLAYWRIGHT_SKIP_DEMO === "1", "Explicitly skipped with PLAYWRIGHT_SKIP_DEMO=1");
  await loginDemo(page);

  for (const route of ["/dashboard", "/calendar", "/trends"]) {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    const violations = await seriousAccessibilityViolations(page);
    expect(violations, `${route} accessibility violations`).toEqual([]);
  }
});
