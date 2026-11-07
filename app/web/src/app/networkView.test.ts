import { describe, expect, it } from "vitest";
import { covidExperiment } from "../test/fixtures";
import { candidateHover, networkView } from "./networkView";

const TYK2 = "ENSG00000105397";
const JAK1 = "ENSG00000162434";
const IFNAR2 = "ENSG00000159110";
const NR3C1 = "ENSG00000113580";
const STAT1 = "ENSG00000115415";

describe("networkView", () => {
  const experiment = covidExperiment();

  it("shows disease proteins on steps 1 and 2, narrowed by a hovered protein", () => {
    expect(networkView("disease", experiment, null, null)).toMatchObject({
      mode: "disease",
      highlight: null,
    });
    const hover = { highlight: [TYK2], focus: [TYK2] };
    expect(networkView("biology", experiment, null, hover)).toMatchObject({
      mode: "disease",
      highlight: [TYK2],
      focus: [TYK2],
    });
  });

  it("highlights the candidates' targets and the disease proteins on step 3", () => {
    const view = networkView("candidates", experiment, null, null);
    expect(view.mode).toBe("roles");
    expect(view.highlight).toEqual(expect.arrayContaining([TYK2, JAK1, IFNAR2]));
    // Connecting proteins that no candidate acts on stay in the background.
    expect(view.highlight).not.toContain(STAT1);
  });

  it("draws the focus drug's route to a disease protein on step 4", () => {
    expect(networkView("evidence", experiment, "CHEMBL384467", null)).toMatchObject({
      mode: "path",
      route: [NR3C1, STAT1, IFNAR2],
      focus: [NR3C1, STAT1, IFNAR2],
      drug: { label: "Dexamethasone", targets: [NR3C1] },
    });
  });

  it("falls back to disease proteins for a drug with no place on the network", () => {
    expect(networkView("evidence", experiment, "CHEMBL4065616", null)).toMatchObject({
      mode: "disease",
      route: null,
      drug: null,
    });
  });
});

describe("candidateHover", () => {
  it("points at the disease proteins and the drug's own targets", () => {
    const hover = candidateHover(covidExperiment(), "CHEMBL2105759");
    expect(hover?.focus).toEqual(expect.arrayContaining([JAK1, TYK2]));
    expect(hover?.highlight).toEqual(expect.arrayContaining([JAK1, TYK2, IFNAR2]));
  });
});
