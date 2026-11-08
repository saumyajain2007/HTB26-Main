import { expect, type Page } from "@playwright/test";

/** Exercise real locally served coordinates and WebGL, including a structure change. */
export async function checkReferencePreview(page: Page) {
  await page.getByRole("button", { name: "Show reference structure", exact: true }).click();
  const preview = page.getByRole("img", { name: /in 3D\. Drag to rotate/ });
  await expect(preview).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
  await expect(preview.locator("canvas")).toBeVisible();
  await expect(page.getByText(/not a computed pose of the selected candidate/)).toBeVisible();
  const firstLabel = await preview.getAttribute("aria-label");
  await page.getByRole("combobox", { name: "Prepared bacterial structure" }).selectOption("2VES_A");
  await expect(preview).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
  await expect(preview).not.toHaveAttribute("aria-label", firstLabel ?? "");
  await expect(preview).toHaveAttribute("aria-label", /lpxC/);
  await expect(preview.locator("canvas")).toHaveCount(1);
  await page.getByRole("button", { name: "Hide reference structure", exact: true }).click();
  await expect(preview).toHaveCount(0);
}
