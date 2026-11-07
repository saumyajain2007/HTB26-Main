import { expect, test } from "./console";

/*
 * The introduction at `/`: the title, the lab plate and the workflow, then the way into step 1.
 * Wording comes from web/src/copy/en.ts.
 */

test("the introduction leads into step 1", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Half Life");
  await expect(
    page.getByRole("heading", { level: 1, name: "Repurposing existing drugs for diseases" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Workflow" })).toBeVisible();

  await page.getByRole("link", { name: "Start exploring" }).click();
  await expect(page).toHaveURL(/\/e\/[0-9a-f-]{36}\/disease$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Choose a disease");
});
