import { expect, test } from "./console";

// Deliberate coordinate stub tests real PDB parsing/WebGL, not model inference.
const protein = [
  "ATOM      1  N   ALA A   1      10.000  10.000  10.000  1.00 80.00           N",
  "ATOM      2  CA  ALA A   1      11.400  10.000  10.000  1.00 80.00           C",
  "ATOM      3  C   ALA A   1      12.000  11.400  10.000  1.00 80.00           C",
  "ATOM      4  O   ALA A   1      11.400  12.400  10.000  1.00 80.00           O",
  "END",
  "",
].join("\n");
const ligand = [
  "HETATM    5  C1  LIG B   1      10.000  10.000  13.000  1.00 80.00           C",
  "HETATM    6  C2  LIG B   1      11.400  10.000  13.000  1.00 80.00           C",
  "HETATM    7  O1  LIG B   1      12.000  11.200  13.000  1.00 80.00           O",
  "END",
  "",
].join("\n");

test("Boltz PDB prediction renders and releases its viewer", async ({ page }) => {
  await page.route("**/api/resistance/profiles/*/candidates/*/boltz{,/*}", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith(".pdb")) {
      await route.fulfill({
        contentType: "chemical/x-pdb",
        body: url.pathname.endsWith("receptor.pdb") ? protein : ligand,
      });
    } else {
      const parts = url.pathname.split("/");
      await route.fulfill({
        json: {
          profile_id: parts[4],
          candidate_id: parts[6],
          smiles: "CCO",
          target_name: "Browser test protein",
          protein_sequence_sha256: "a".repeat(64),
          boltz_version: "test stub",
          confidence_score: 0.88,
          receptor: { url: `${url.pathname}/receptor.pdb`, sha256: "a".repeat(64) },
          ligand: { url: `${url.pathname}/ligand.pdb`, sha256: "b".repeat(64) },
        },
      });
    }
  });
  await page.goto("/resistance");
  await page.getByRole("button", { name: "MRSA (S. aureus)", exact: true }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("meter", { name: "Model confidence" })).toBeVisible();
  await page.getByRole("button", { name: "Show Boltz prediction" }).click();
  const viewer = page.getByRole("img", { name: /predicted by Boltz-2/ });
  await expect(viewer).toHaveAttribute("data-ready", "true");
  await expect(viewer.locator("canvas")).toBeVisible();
  await page.getByRole("button", { name: "Hide Boltz prediction" }).click();
  await expect(viewer).toHaveCount(0);
  await page.getByRole("button", { name: "Show Boltz prediction" }).click();
  await expect(page.getByRole("img", { name: /predicted by Boltz-2/ })).toHaveAttribute(
    "data-ready",
    "true",
  );
});
