import { expect, test } from "./console";

// Opt-in integration check: requires a genuinely generated, locally published result.
// Example: E2E_RESISTANCE=saved E2E_PRECOMPUTED_BOLTZ=1 npm run e2e -- precomputed-boltz.spec.ts
test.use({ video: { mode: "on", size: { width: 1440, height: 900 } } });

const profileId = "434b687b-1254-43b4-8581-3ea836f1709b";
const metadataPath = `/api/resistance/profiles/${profileId}/candidates/CHEMBL22/boltz`;

test("saved trimethoprim Boltz prediction loads locally after reload", async ({
  page,
  baseURL,
}, testInfo) => {
  test.skip(
    process.env.E2E_PRECOMPUTED_BOLTZ !== "1",
    "Generate the real trimethoprim–DHFR prediction first",
  );
  test.skip(process.env.E2E_RESISTANCE !== "saved", "Requires the saved candidate ranking");
  if (baseURL === undefined) throw new Error("A local baseURL is required");
  const external: string[] = [];
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin === new URL(baseURL).origin) await route.continue();
    else {
      external.push(url.href);
      await route.abort();
    }
  });
  await page.goto(`/resistance/${profileId}/candidates`);
  await page.getByRole("button", { name: /^TRIMETHOPRIM/i }).click();
  await expect(page.getByText(/S\. aureus wild-type DHFR/)).toBeVisible();
  await expect(page.getByText(/Model confidence:/)).toBeVisible();
  await page.getByRole("button", { name: "Show Boltz prediction" }).click();
  const viewer = page.getByRole("img", { name: /TRIMETHOPRIM.*predicted by Boltz-2/i });
  await expect(viewer).toHaveAttribute("data-ready", "true", { timeout: 20_000 });
  await expect(viewer.locator("canvas")).toBeVisible();
  await viewer.scrollIntoViewIfNeeded();
  await expect(page.getByText(/Illustrative placement animation/)).toBeVisible();
  await expect(viewer).toHaveAttribute("data-placement", "playing");
  await expect(viewer).toHaveAttribute("data-placement", "complete", { timeout: 10_000 });
  await page.getByRole("button", { name: "Reset view", exact: true }).click();
  await expect(viewer).toHaveAttribute("data-placement", "idle");
  await page.screenshot({ path: testInfo.outputPath("precomputed-boltz.png") });
  await viewer.screenshot({ path: testInfo.outputPath("precomputed-boltz-closeup.png") });
  const response = await page.request.get(metadataPath);
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ candidate_id: "CHEMBL22", boltz_version: "2.2.1" });
  await page.reload();
  await page.getByRole("button", { name: /^TRIMETHOPRIM/i }).click();
  await page.getByRole("button", { name: "Show Boltz prediction" }).click();
  await expect(page.getByRole("img", { name: /predicted by Boltz-2/ })).toHaveAttribute(
    "data-ready",
    "true",
    { timeout: 20_000 },
  );
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.getByRole("button", { name: "Animate placement", exact: true })).toBeDisabled();
  await expect(page.getByRole("img", { name: /predicted by Boltz-2/ })).toHaveAttribute(
    "data-placement",
    "idle",
  );
  expect(
    external,
    "displaying a precomputed prediction must not contact external services",
  ).toEqual([]);
});
