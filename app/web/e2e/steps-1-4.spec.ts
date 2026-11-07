import type { Page } from "@playwright/test";
import { expect, test } from "./console";

/*
 * Walks the network steps against the real API in fixture mode (COVID-19), the plan's first
 * working demonstration: step 1 opens the first common disease (COVID-19) and draws its network,
 * search still finds it, then Next to biology, candidate drugs and evidence,
 * including the drugs whose closeness can't be measured, the one that can't be placed on the
 * network, and an antibody with no 3D model. Wording comes from web/src/copy/en.ts.
 */

async function expectStep(page: Page, title: string) {
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
  await expect(page.getByRole("link", { name: title, exact: true })).toHaveAttribute(
    "aria-current",
    "step",
  );
}

test("a student walks from choosing COVID-19 to the evidence for baricitinib", async ({ page }) => {
  // Step 1 opens the first common disease, marks it in the list and draws its network.
  await page.goto("/explore");
  await expect(page).toHaveURL(/\/e\/[0-9a-f-]{36}\/disease$/);
  await expectStep(page, "Choose a disease");
  await expect(page.getByText("Common diseases", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /COVID-19/ })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect(
    page.getByRole("img", { name: "Protein network in 3D. Drag to rotate." }),
  ).toBeVisible({ timeout: 15_000 });

  // Typing searches every disease instead, with the matched synonym and the ID.
  await page.getByRole("searchbox", { name: "Search diseases" }).fill("sars-cov");
  const covid = page.getByRole("button", { name: /COVID-19/ });
  await expect(covid).toContainText("MONDO_0100096");
  await expect(covid).toContainText("SARS-CoV-2");
  await expect(page.getByText("Common diseases", { exact: true })).toHaveCount(0);

  // Next, at the bottom right, carries on to its proteins.
  await page.getByRole("contentinfo").getByRole("button", { name: "Next", exact: true }).click();
  await expect(page).toHaveURL(/\/e\/[0-9a-f-]{36}\/biology$/);
  const banner = page.getByRole("banner");
  await expect(banner.getByText("COVID-19", { exact: true })).toBeVisible();
  const bars = page.getByRole("list", { name: "Disease proteins by link strength" });
  await expect(bars).toBeVisible({ timeout: 15_000 });
  await expectStep(page, "Disease proteins");
  await expect(bars.getByRole("listitem")).toHaveCount(8);
  await expect(
    page.getByText("CCR2 isn’t in the protein network, so it can’t be used."),
  ).toHaveCount(1);
  await expect(
    page.getByRole("img", { name: "Protein network in 3D. Drag to rotate." }),
  ).toBeVisible();
  await expect(page.getByText("COVID-19", { exact: true })).toHaveCount(1);

  // Step 3: candidate drugs, five first.
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expectStep(page, "Candidate drugs");
  await expect(page.getByTestId(/^slope-row-/)).toHaveCount(5);
  await expect(page.getByText("Baricitinib", { exact: true })).toHaveCount(1);
  await expect(page.getByText(/^Baricitinib is already used for COVID-19\./)).toHaveCount(1);
  await expect(page.getByText(/^Not measured/)).toHaveCount(0);

  await page.getByRole("checkbox", { name: "Show all 15" }).check();
  await expect(page.getByTestId(/^slope-row-/)).toHaveCount(14);
  // Tocilizumab has a network rank but no closeness: no dot, never a zero.
  const tocilizumab = page.getByTestId("slope-row-CHEMBL1237022");
  await expect(tocilizumab).toContainText("Tocilizumab");
  await expect(tocilizumab.locator("circle")).toHaveCount(2);
  // Once for both drugs, with its note marker (an SVG superscript).
  await expect(page.getByText(/^Not measured\d$/)).toHaveCount(1);
  await expect(page.getByText(/^Random proteins all landed at the same distance/)).toHaveCount(1);
  // Remdesivir can't be placed: listed under the chart with its reason, and no score.
  await expect(page.getByTestId("slope-row-CHEMBL4065616")).toHaveCount(0);
  await expect(page.getByText("Remdesivir", { exact: true })).toBeVisible();
  await expect(page.getByText(/^None of this drug’s targets are human proteins/)).toHaveCount(1);

  // The known-answer drug's evidence, which the steps place just before History.
  await page.getByRole("link", { name: "Evidence", exact: true }).click();
  await expectStep(page, "Evidence");
  await expect(page.getByRole("heading", { level: 2, name: "Baricitinib" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Baricitinib in 3D. Drag to rotate." })).toBeVisible();
  const facts = page.getByRole("list", { name: "Sourced facts" });
  await expect(facts.getByRole("listitem")).toHaveCount(6);
  await expect(facts.getByText(/Black Box Warning/i)).toHaveCount(0);
  await expect(page.getByText("Label warning", { exact: true })).toHaveCount(1);
  await expect(page.getByRole("link", { name: "DailyMed" })).toBeVisible();
  await expect(page.getByText("Why it ranks high", { exact: true })).toHaveCount(1);
  await expect(
    page.getByText("Baricitinib acts on TYK2, which is itself a disease protein."),
  ).toHaveCount(1);

  // An antibody: a plain line instead of a 3D model, and nothing broken.
  await page.goto(`${new URL(page.url()).pathname}?drug=CHEMBL1237022`);
  await expect(page.getByRole("heading", { level: 2, name: "Tocilizumab" })).toBeVisible();
  await expect(page.getByText("Antibody: no small-molecule 3D model")).toHaveCount(1);
  await expect(page.getByRole("img", { name: "Tocilizumab in 3D. Drag to rotate." })).toHaveCount(
    0,
  );
});

test("the network persists across steps instead of being rebuilt", async ({ page }) => {
  await page.goto("/explore");
  // Wait for the build: until then the later steps show its progress in place of the network.
  await expect(page).toHaveURL(/\/e\/[0-9a-f-]{36}\/disease$/);
  const id = new URL(page.url()).pathname.split("/")[2] ?? "";
  await expect
    .poll(
      async () => {
        const response = await page.request.get(`/api/experiments/${id}`);
        return ((await response.json()) as { status: string }).status;
      },
      { timeout: 15_000 },
    )
    .toBe("ready");
  const network = page.getByRole("img", { name: "Protein network in 3D. Drag to rotate." });
  await expect(network).toBeVisible({ timeout: 15_000 });
  // Tag the network's element; if a step change rebuilt the network, the tag would be gone.
  await network.evaluate((element) => {
    element.setAttribute("data-marker", "first");
  });

  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Disease proteins");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Candidate drugs");
  await page.getByRole("link", { name: "Evidence", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Evidence");
  await expect(network).toHaveAttribute("data-marker", "first");
});

test.describe("an unknown Experiment", () => {
  // The API's 404 is what the page explains; the browser logs the failed request itself.
  test.use({ expectedConsoleErrors: [/the server responded with a status of 404/] });

  test("says so plainly", async ({ page }) => {
    await page.goto("/e/00000000-0000-4000-8000-000000000000/biology");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Experiment not found");
  });
});
