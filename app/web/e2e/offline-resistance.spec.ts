import { expect, test } from "./console";

// Real local API and built assets; no MSW, route fulfilment or remote resources.
test("offline MRSA preset reaches an explained shortlist and certificates", async ({
  page,
  baseURL,
}) => {
  test.skip(process.env.E2E_RESISTANCE === "saved", "Fixture fallback check");
  if (baseURL === undefined) throw new Error("A local baseURL is required");
  const localOrigin = new URL(baseURL).origin;
  const external: string[] = [];
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin === localOrigin) await route.continue();
    else {
      external.push(url.href);
      await route.abort();
    }
  });
  await page.goto("/resistance");
  await page.getByRole("button", { name: "MRSA (S. aureus)", exact: true }).click();
  await expect(page).toHaveURL(/\/resistance\/[0-9a-f-]+\/map$/);
  await expect(page.getByRole("table")).toBeVisible();
  await expect(page.getByText("mecA", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page).toHaveURL(/\/candidates$/);
  await expect(page.getByRole("heading", { name: "Why it sits here", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Property rules and certificate" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Cited evidence" })).toBeVisible();
  await expect(page.getByText(/Lean 4 checked and confirmed all/)).toBeVisible();
  await expect(
    page.getByText(/Fixture data\. The scores, MICs and ranks are made up/),
  ).toBeVisible();
  await page.getByRole("button", { name: /VANCOMYCIN/i }).click();
  await expect(page.getByRole("region", { name: /Details for VANCOMYCIN/i })).toBeVisible();
  await expect(page.getByText(/Lean 4 refuted failing rule theorems/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Why it sits here", exact: true })).toBeVisible();
  expect(external, "the complete demo must use only local resources").toEqual([]);
});
