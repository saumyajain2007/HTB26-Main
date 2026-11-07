import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { Experiment } from "../api/types";
import { copy, unscorableReasonText } from "../copy/en";
import { EXPERIMENT_ID, evidenceOnlyExperiment } from "../test/fixtures";
import { renderApp } from "../test/render";
import { serveExperiment } from "../test/server";

/**
 * A live Experiment without a protein network (ranking_method evidence_only): no network panel,
 * legend or empty canvas on any step, and "no network ranking ran" said once per screen.
 */

const E = `/e/${EXPERIMENT_ID}`;
const NO_ROUTE = unscorableReasonText("network_unavailable");

function expectOnce(...texts: string[]) {
  for (const text of texts) {
    const found = screen.getAllByText(text, {
      ignore: "script, style, option, [aria-hidden='true'] *",
    });
    expect(found, text).toHaveLength(1);
  }
}

/** Nothing of the network is drawn or keyed. */
function expectNoNetwork() {
  expect(screen.queryByRole("img", { name: copy.network.label })).not.toBeInTheDocument();
  expect(screen.queryByText(copy.network.empty)).not.toBeInTheDocument();
  for (const key of Object.values(copy.legend)) {
    expect(screen.queryByText(key)).not.toBeInTheDocument();
  }
}

/**
 * Like live data: Baricitinib has the same summary from three ChEMBL records, and Tofacitinib
 * (a small molecule) has no PubChem compound, as live peficitinib doesn't.
 */
function liveLike(): Experiment {
  const experiment = evidenceOnlyExperiment();
  for (const candidate of experiment.candidates) {
    if (candidate.candidate_id === "CHEMBL2105759") {
      const jak2 = candidate.evidence.find((item) => item.summary === "Blocks JAK2.");
      if (jak2 === undefined) throw new Error("No JAK2 fact in the fixture");
      candidate.evidence.push(
        {
          ...jak2,
          id: "E-dup-1",
          url: "https://www.ebi.ac.uk/chembl/api/data/mechanism/9001.json",
        },
        {
          ...jak2,
          id: "E-dup-2",
          url: "https://www.ebi.ac.uk/chembl/api/data/mechanism/9002.json",
        },
      );
    }
    if (candidate.candidate_id === "CHEMBL221959") {
      candidate.pubchem_cid = null;
      candidate.dockable = false;
    }
  }
  return experiment;
}

beforeEach(() => {
  serveExperiment(liveLike());
});

describe("An evidence-only Experiment", () => {
  it("step 2 lists every protein and says once that the network isn't available", async () => {
    renderApp(`${E}/biology`);
    const bars = await screen.findByRole("list", { name: copy.biology.targetsLabel });
    expect(within(bars).getAllByRole("listitem")).toHaveLength(9);
    expectOnce(copy.biology.ruleNoNetwork(9), copy.biology.noNetwork, "COVID-19");
    expect(screen.queryByText(copy.biology.rule(9, 9))).not.toBeInTheDocument();
    expectNoNetwork();
    expect(document.querySelectorAll("canvas")).toHaveLength(0);
  });

  it("step 3 ranks the shortlist by evidence in one list, titled and explained once", async () => {
    renderApp(`${E}/candidates`);
    const list = await screen.findByRole("list", { name: copy.candidates.evidenceOnly.listLabel });
    const names = within(list)
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(names).toEqual([
      `${copy.candidates.evidenceOnly.rank(1)}1Baricitinib`,
      `${copy.candidates.evidenceOnly.rank(2)}2Tofacitinib`,
      `${copy.candidates.evidenceOnly.rank(3)}3Upadacitinib`,
      `${copy.candidates.evidenceOnly.rank(4)}4Tocilizumab`,
      `${copy.candidates.evidenceOnly.rank(5)}5Sarilumab`,
    ]);
    expectOnce(
      copy.candidates.evidenceOnly.title,
      copy.candidates.evidenceOnly.help,
      copy.candidates.knownAnswer("Baricitinib", "COVID-19"),
    );
    // No network ranking ran: no slope chart, closeness or per-drug "not measured".
    expect(screen.queryAllByTestId(/^slope-row-/)).toHaveLength(0);
    expect(screen.queryByText(copy.candidates.notMeasured)).not.toBeInTheDocument();
    expect(screen.queryByText(copy.candidates.closeness)).not.toBeInTheDocument();
    expect(screen.queryByText(NO_ROUTE)).not.toBeInTheDocument();
    expectNoNetwork();
  });

  it("step 4 says the drug's reason once instead of a route, and merges repeated facts", async () => {
    renderApp(`${E}/evidence`);
    const facts = await screen.findByRole("list", { name: copy.evidence.listLabel });
    expectOnce(NO_ROUTE, "Blocks JAK2.");
    expect(screen.queryByText(copy.evidence.noRouteTitle)).not.toBeInTheDocument();
    expect(screen.queryByText(copy.evidence.pathTitle)).not.toBeInTheDocument();
    expectNoNetwork();
    // Three records say "Blocks JAK2.": one row, one ChEMBL link, the first record's.
    expect(within(facts).getAllByRole("listitem")).toHaveLength(6);
    const jak2 = within(facts).getByText("Blocks JAK2.").closest("li");
    if (!(jak2 instanceof HTMLElement)) throw new Error("No JAK2 row");
    const links = within(jak2).getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAccessibleName("ChEMBL");
    expect(links[0]).toHaveAttribute(
      "href",
      "https://www.ebi.ac.uk/chembl/api/data/mechanism/5294.json",
    );
  });

  it("step 4 says neutrally that a small molecule without a PubChem compound has no model", async () => {
    renderApp(`${E}/evidence?drug=CHEMBL221959`);
    expect(await screen.findByText(copy.evidence.noModelNeutral)).toBeInTheDocument();
    expectOnce("Tofacitinib", copy.evidence.noModelNeutral);
    expect(screen.queryByText(copy.evidence.noModel)).not.toBeInTheDocument();
  });

  it("step 4 keeps the antibody wording for an antibody", async () => {
    renderApp(`${E}/evidence?drug=CHEMBL1237022`);
    expect(await screen.findByText(copy.evidence.noModel)).toBeInTheDocument();
    expect(screen.queryByText(copy.evidence.noModelNeutral)).not.toBeInTheDocument();
  });

  it("step 6 says once per row that no network rank exists, and leaves out the drug with no model", async () => {
    renderApp(`${E}/compare`);
    await screen.findByRole("table", { name: copy.compare.tableLabel });
    const header = screen.getByRole("rowheader", { name: copy.candidates.networkRank });
    const row = header.closest("[role='row']");
    if (!(row instanceof HTMLElement)) throw new Error("No network-rank row");
    expect(
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual([copy.candidates.notRanked]);
    expectOnce(copy.candidates.notRanked);
    // Tofacitinib has no PubChem compound here, so no 3D model: Compare doesn't offer it at all.
    for (const picker of screen.getAllByRole("combobox", { name: copy.compare.pick })) {
      expect(within(picker).queryByRole("option", { name: "Tofacitinib" })).toBeNull();
    }
    expect(screen.queryByText(copy.evidence.noModelNeutral)).not.toBeInTheDocument();
    expect(screen.queryByText(copy.evidence.noModel)).not.toBeInTheDocument();
    expect(screen.queryByText(NO_ROUTE)).not.toBeInTheDocument();
  });
});

describe("Label warning sources", () => {
  it("links each source once, even when its warnings cite different pages", async () => {
    const experiment = evidenceOnlyExperiment();
    const baricitinib = experiment.candidates.find((c) => c.candidate_id === "CHEMBL2105759");
    if (baricitinib === undefined) throw new Error("No baricitinib in the fixture");
    const cited = new Set(baricitinib.warnings.map((warning) => warning.evidence_id));
    let page = 0;
    for (const item of baricitinib.evidence) {
      if (cited.has(item.id))
        item.url = `https://dailymed.nlm.nih.gov/dailymed/page-${String(++page)}`;
    }
    expect(page).toBeGreaterThan(1);
    serveExperiment(experiment);
    renderApp(`${E}/evidence`);
    const box = await screen.findByRole("note", { name: copy.evidence.warningTitle });
    expect(within(box).getAllByRole("link", { name: "DailyMed" })).toHaveLength(1);
  });
});
