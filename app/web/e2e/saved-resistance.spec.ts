import { expect, test } from "./console";
import { checkReferencePreview } from "./reference-preview";

test("all three saved real rankings open without external requests", async ({ page, baseURL }) => {
  test.skip(process.env.E2E_RESISTANCE !== "saved", "Run with E2E_RESISTANCE=saved");
  if (baseURL === undefined) throw new Error("A local baseURL is required");
  const external: string[] = [];
  await page.route("**/*", async (route) => {
    if (new URL(route.request().url()).origin === new URL(baseURL).origin) {
      await route.continue();
    } else {
      external.push(route.request().url());
      await route.abort();
    }
  });
  for (const label of [
    "MRSA (S. aureus)",
    "ESBL/KPC K. pneumoniae",
    "Carbapenem-resistant A. baumannii",
  ]) {
    await page.goto("/resistance");
    await page.getByRole("button", { name: label, exact: true }).click();
    await expect(page.getByRole("table")).toBeVisible();
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Why it sits here", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Cited evidence" })).toBeVisible();
    await expect(
      page.getByText("Lean 4 did not run for this molecule; Python smoke test only."),
    ).toBeVisible();
    await expect(
      page.getByText(/Fixture data\. The scores, MICs and ranks are made up/),
    ).toHaveCount(0);
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Why it sits here", exact: true }),
    ).toBeVisible();
    await checkReferencePreview(page);
  }
  expect(external).toEqual([]);
});
