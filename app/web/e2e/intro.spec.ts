import { expect, test } from "./console";

/*
 * The introduction at `/`: the title, the lab plate and the three pathogens, then the way into
 * the resistance flow. Wording comes from web/src/copy/en.ts.
 */

test("the introduction leads into the pathogen step", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("HTB26");
  await expect(
    page.getByRole("heading", { level: 1, name: "Antibiotics that resistance doesn’t rule out" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Three pathogens" })).toBeVisible();
  for (const name of [
    "Staphylococcus aureus",
    "Klebsiella pneumoniae",
    "Acinetobacter baumannii",
  ]) {
    await expect(page.getByRole("link", { name: new RegExp(name) })).toBeVisible();
  }

  await page.getByRole("link", { name: "Start exploring" }).click();
  await expect(page).toHaveURL(/\/resistance$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Choose a pathogen");
});
