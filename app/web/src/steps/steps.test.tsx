import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import type { Experiment } from "../api/types";
import { copy, networkWarningText, unscorableReasonText } from "../copy/en";
import { covidExperiment, EXPERIMENT_ID, randomWalkExperiment } from "../test/fixtures";
import { renderApp } from "../test/render";
import { http, serveExperiment, server } from "../test/server";

const E = `/e/${EXPERIMENT_ID}`;

/**
 * Each of these strings is said exactly once on screen (docs/engineering/design.md, "Say everything once").
 * Labels drawn on the 3D figures themselves (protein symbols, the drug's node) mark points in
 * the picture rather than repeat a statement, as in the prototype, so they don't count.
 */
function expectOnce(...texts: string[]) {
  for (const text of texts) {
    const found = screen.getAllByText(text, { ignore: "script, style, [aria-hidden='true'] *" });
    expect(found, text).toHaveLength(1);
  }
}

/** Waits for the step's figure: the network is the last thing a ready Experiment draws. */
async function ready() {
  return screen.findByRole("img", { name: copy.network.label });
}

beforeEach(() => {
  serveExperiment(covidExperiment());
});

describe("Step 1, Choose a disease, with an Experiment", () => {
  it("shows the search beside the network, with the disease proteins keyed once", async () => {
    renderApp(`${E}/disease`);
    await ready();
    expect(screen.getByRole("searchbox")).toHaveValue("COVID-19");
    expectOnce(copy.legend.disease);
    // The search lists the Disease, so the header doesn't name it again.
    expect(within(screen.getByRole("banner")).queryByText("COVID-19")).not.toBeInTheDocument();
  });

  it("says nothing about the build under the common diseases: the network is the progress", async () => {
    const done = covidExperiment();
    serveExperiment({
      ...covidExperiment("building", "evidence"),
      targets: done.targets,
      network: done.network,
    });
    renderApp(`${E}/disease`);
    await ready();
    expect(screen.getByText(copy.search.common)).toBeInTheDocument();
    expect(screen.queryByText(copy.experiment.stages.evidence)).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("Step 2, Disease proteins", () => {
  it("draws the proteins and network while the drugs are still being ranked", async () => {
    const done = covidExperiment();
    serveExperiment({
      ...covidExperiment("building", "evidence"),
      targets: done.targets,
      network: done.network,
    });
    renderApp(`${E}/biology`);
    await screen.findByRole("img", { name: copy.network.label });
    const bars = screen.getByRole("list", { name: copy.biology.targetsLabel });
    expect(within(bars).getAllByRole("listitem")).toHaveLength(8);
    // One line says what is still happening; the full stage list is gone.
    expect(screen.getByRole("status")).toHaveTextContent(copy.experiment.stages.evidence);
    expect(
      screen.queryByRole("list", { name: copy.experiment.buildLabel }),
    ).not.toBeInTheDocument();
  });

  it("keeps the full progress list until the proteins are known", async () => {
    serveExperiment(covidExperiment("building", "targets"));
    renderApp(`${E}/biology`);
    expect(
      await screen.findByRole("list", { name: copy.experiment.buildLabel }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: copy.network.label })).not.toBeInTheDocument();
  });

  it("lists the network's proteins by link strength and names the excluded one once", async () => {
    renderApp(`${E}/biology`);
    await ready();
    const bars = screen.getByRole("list", { name: copy.biology.targetsLabel });
    expect(within(bars).getAllByRole("listitem")).toHaveLength(8);
    expect(within(bars).getByText("ACE2")).toBeInTheDocument();
    expect(within(bars).getByText("0.82")).toBeInTheDocument();
    // CCR2 is not in the network: no bar, one sentence with the reason.
    expect(within(bars).queryByText("CCR2")).not.toBeInTheDocument();
    expectOnce(
      copy.biology.excluded.not_in_graph(["CCR2"]),
      copy.biology.rule(9, 8),
      copy.biology.strength,
      copy.legend.disease,
      copy.legend.link,
      "COVID-19",
    );
  });

  it("explains an empty network when none of the disease's proteins map into it", async () => {
    const experiment = covidExperiment();
    experiment.targets = experiment.targets.map((target) => ({
      ...target,
      retained: false,
      excluded_reason: "not_in_graph" as const,
    }));
    experiment.network = { graph_version: "string-12.5", nodes: [], edges: [] };
    serveExperiment(experiment);
    renderApp(`${E}/biology`);
    expect(await screen.findByText(copy.network.empty)).toBeInTheDocument();
    expectOnce(
      copy.biology.rule(9, 0),
      copy.biology.excluded.not_in_graph(experiment.targets.map((target) => target.symbol)),
    );
    expect(screen.queryByRole("list", { name: copy.biology.targetsLabel })).not.toBeInTheDocument();
  });
});

describe("Step 3, Candidate drugs", () => {
  it("shows the top five, each drug named once, with every label and note once", async () => {
    renderApp(`${E}/candidates`);
    await ready();
    for (const name of [
      "Baricitinib",
      "Ruxolitinib",
      "Tofacitinib",
      "Upadacitinib",
      "Fedratinib",
    ]) {
      expectOnce(name);
    }
    expect(screen.queryByText("Tocilizumab")).not.toBeInTheDocument();
    expect(screen.queryByText("BARICITINIB")).not.toBeInTheDocument();
    expectOnce(
      copy.candidates.ranking,
      copy.candidates.closeness,
      copy.candidates.networkRank,
      copy.candidates.evidenceRank,
      copy.candidates.closenessHelp,
      copy.candidates.evidenceRankHelp,
      copy.candidates.knownAnswer("Baricitinib", "COVID-19"),
      copy.candidates.showAll(15),
      copy.legend.disease,
      copy.legend.drug,
      copy.legend.both,
      "COVID-19",
    );
    // Closeness sits on the drug's own row.
    const row = screen.getByTestId("slope-row-CHEMBL2105759");
    expect(within(row).getByText("−3.1")).toBeInTheDocument();
    // Lines cross other drugs' rows, so no hover band spans the chart's width: past the network
    // rank axis a drug reacts only along its own line, traced by an invisible twin, and its end.
    const width = Number(row.closest("svg")?.getAttribute("width"));
    for (const band of row.querySelectorAll("rect")) {
      const x = Number(band.getAttribute("x"));
      expect(x > 0 || x + Number(band.getAttribute("width")) < width).toBe(true);
    }
    const ends = [...row.querySelectorAll("line")].map((line) =>
      ["x1", "y1", "x2", "y2"].map((name) => line.getAttribute(name)).join(" "),
    );
    expect(ends.filter((end, index) => ends.indexOf(end) !== index)).toHaveLength(1);
  });

  it("reveals the whole shortlist, with no closeness where it wasn't measured", async () => {
    const user = userEvent.setup();
    renderApp(`${E}/candidates`);
    await ready();
    await user.click(screen.getByRole("checkbox", { name: copy.candidates.showAll(15) }));

    // 14 drugs have a place on the network; tocilizumab and sarilumab only a distance.
    expect(screen.getAllByTestId(/^slope-row-/)).toHaveLength(14);
    for (const id of ["CHEMBL1237022", "CHEMBL2108730"]) {
      const row = screen.getByTestId(`slope-row-${id}`);
      // A rank point at each end, and no closeness dot or value (never a zero).
      expect(row.querySelectorAll("circle")).toHaveLength(2);
      expect(row).not.toHaveTextContent(/[0-9]\.[0-9]/);
    }
    // "Not measured" and its reason are said once for both drugs.
    expectOnce(copy.candidates.notMeasured, networkWarningText("zero_null_variance"));

    // Remdesivir can't be placed: listed under the chart with its plain reason, and no score.
    expect(screen.queryByTestId("slope-row-CHEMBL4065616")).not.toBeInTheDocument();
    expectOnce("Remdesivir", unscorableReasonText("no_retained_drug_targets"));
  });

  it("names the reason once when no drug can be placed on the network", async () => {
    const experiment: Experiment = covidExperiment();
    experiment.candidates = experiment.candidates.map((candidate) => ({
      ...candidate,
      status: "not_scorable" as const,
      network: null,
      unscorable_reason: "no_retained_disease_targets" as const,
      unscorable_detail: "None of the disease's proteins are in the network.",
    }));
    serveExperiment(experiment);
    renderApp(`${E}/candidates`);
    expect(
      await screen.findByText(unscorableReasonText("no_retained_disease_targets")),
    ).toBeInTheDocument();
    expect(screen.queryAllByTestId(/^slope-row-/)).toHaveLength(0);
    expectOnce("Baricitinib, Ruxolitinib, Tofacitinib, Upadacitinib and Fedratinib");
  });
});

describe("Step 3 with a random-walk shortlist", () => {
  it("orders drugs by their walk rank and says once how that rank was made", async () => {
    const experiment = randomWalkExperiment();
    serveExperiment(experiment);
    renderApp(`${E}/candidates`);
    await ready();
    expectOnce(copy.candidates.randomWalkHelp, copy.candidates.evidenceRankHelp);
    const first = experiment.candidates.find((candidate) => candidate.network?.rwr?.rank === 1);
    expect(first).toBeDefined();
    const rows = screen.getAllByTestId(/^slope-row-/);
    expect(rows[0]).toHaveAttribute("data-testid", `slope-row-${first?.candidate_id ?? ""}`);
    // The notes keep column order: closeness 1, network rank 2, evidence rank 3.
    const note = screen.getByText(copy.candidates.randomWalkHelp).closest("p");
    expect(note).toHaveTextContent(/^2/);
    expect(screen.getByText(copy.candidates.evidenceRankHelp).closest("p")).toHaveTextContent(/^3/);
  });

  it("keeps the closeness ranking, and no walk note, for a z-score shortlist", async () => {
    renderApp(`${E}/candidates`);
    await ready();
    expect(screen.queryByText(copy.candidates.randomWalkHelp)).not.toBeInTheDocument();
    expect(screen.getAllByTestId(/^slope-row-/)[0]).toHaveAttribute(
      "data-testid",
      "slope-row-CHEMBL2105759",
    );
  });
});

describe("Step 4, Evidence", () => {
  it("shows the known-answer drug's molecule, sourced facts, warnings once and its route", async () => {
    renderApp(`${E}/evidence`);
    await ready();
    expect(
      await screen.findByRole("img", { name: copy.evidence.moleculeLabel("Baricitinib") }),
    ).toBeInTheDocument();
    expectOnce(
      "Baricitinib",
      copy.evidence.warningTitle,
      copy.evidence.pathTitle,
      copy.evidence.route.self("Baricitinib", "TYK2"),
      "Blood clots and blood vessel problems, cancer, lung problems and serious infections.",
      copy.legend.disease,
      copy.legend.drug,
      copy.legend.path,
      "COVID-19",
    );
    const facts = screen.getByRole("list", { name: copy.evidence.listLabel });
    expect(within(facts).getAllByRole("listitem")).toHaveLength(6);
    // Facts are the API's plain summaries, not the source's technical statement.
    expect(within(facts).getByText("Blocks JAK1.")).toBeInTheDocument();
    expect(
      within(facts).getByText("Binds AAK1 very strongly in lab tests (9 tests)."),
    ).toBeInTheDocument();
    expect(within(facts).queryByText(/pChEMBL|association score|records/)).not.toBeInTheDocument();
    // Warnings live in the warning box only, never as a fact.
    expect(within(facts).queryByText(/cancer/i)).not.toBeInTheDocument();
    expect(within(facts).getAllByRole("link", { name: "ChEMBL" })[0]).toHaveAttribute(
      "href",
      "https://www.ebi.ac.uk/chembl/api/data/mechanism/5293.json",
    );
    expect(screen.getByRole("link", { name: "DailyMed" })).toBeInTheDocument();
  });

  it("says plainly that an antibody has no small-molecule model", async () => {
    renderApp(`${E}/evidence?drug=CHEMBL1237022`);
    await ready();
    expectOnce("Tocilizumab", copy.evidence.noModel, copy.evidence.routeTitle);
    // Ranked by distance only, so it doesn't claim to rank high.
    expect(screen.queryByText(copy.evidence.pathTitle)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("img", { name: copy.evidence.moleculeLabel("Tocilizumab") }),
    ).not.toBeInTheDocument();
  });

  it("says neutrally that a small molecule's missing conformer leaves no 3D model", async () => {
    server.use(
      http.get("/api/molecules/{pubchem_cid}/conformer", ({ response }) =>
        response(404).json({ detail: "No 3D structure." }),
      ),
    );
    renderApp(`${E}/evidence`);
    await ready();
    expect(await screen.findByText(copy.evidence.noModelNeutral)).toBeInTheDocument();
    expect(screen.queryByText(copy.evidence.noModel)).not.toBeInTheDocument();
  });

  it("explains a drug with no place on the network instead of a route", async () => {
    renderApp(`${E}/evidence?drug=CHEMBL4065616`);
    await ready();
    expectOnce(copy.evidence.noRouteTitle, unscorableReasonText("no_retained_drug_targets"));
    expect(screen.queryByText(copy.evidence.pathTitle)).not.toBeInTheDocument();
  });

  it("calls a drug's route just a route when evidence, not closeness, chose it", async () => {
    const experiment = covidExperiment();
    experiment.candidates = experiment.candidates.map((candidate) =>
      candidate.name === "BARICITINIB"
        ? {
            ...candidate,
            selected_by: ["evidence"],
            selection_reasons: ["initial_evidence_quota"],
          }
        : candidate,
    );
    serveExperiment(experiment);
    renderApp(`${E}/evidence`);
    await ready();
    expectOnce(copy.evidence.routeTitle, copy.evidence.route.self("Baricitinib", "TYK2"));
    expect(screen.queryByText(copy.evidence.pathTitle)).not.toBeInTheDocument();
  });

  it("links network routes to STRING and pathways to Reactome, saying the shown route once", async () => {
    const experiment = covidExperiment();
    const hash = "b".repeat(64);
    experiment.candidates = experiment.candidates.map((candidate) =>
      candidate.name === "BARICITINIB"
        ? {
            ...candidate,
            evidence: [
              ...candidate.evidence,
              {
                id: "E901",
                kind: "network_path",
                source: "string",
                source_id: `ENSG00000105397@${hash}`,
                url: "https://string-db.org/cgi/network?identifiers=9606.ENSP00000264818",
                release: "string-12.5",
                statement: "In the filtered STRING 12.5 physical network, TYK2 ...",
                summary: "TYK2 is itself a disease protein, so the drug acts on it directly.",
                values: { hops: 0 },
              },
              {
                id: "E902",
                kind: "network_path",
                source: "string",
                source_id: `ENSG00000162434>ENSG00000105397@${hash}`,
                url: "https://string-db.org/cgi/network?identifiers=9606.ENSP00000342850",
                release: "string-12.5",
                statement: "In the filtered STRING 12.5 physical network, JAK1 ...",
                summary: "JAK1 connects to TYK2 in 1 step in the protein network.",
                values: { hops: 1 },
              },
              {
                id: "E903",
                kind: "pathway",
                source: "reactome",
                source_id: "R-HSA-9020933",
                url: "https://reactome.org/content/detail/R-HSA-9020933",
                release: "reactome-97",
                statement: "In Reactome, at least one of this Candidate's Targets ...",
                summary:
                  "Targets a protein in the interleukin-23 signalling pathway, which also includes the disease protein TYK2.",
                values: { pathway_gene_count: 13 },
              },
            ],
          }
        : candidate,
    );
    serveExperiment(experiment);
    renderApp(`${E}/evidence`);
    await ready();
    const facts = screen.getByRole("list", { name: copy.evidence.listLabel });
    // The route the network panel says in words isn't listed again as a fact.
    expectOnce(copy.evidence.route.self("Baricitinib", "TYK2"));
    expect(within(facts).queryByText(/TYK2 is itself a disease protein/)).not.toBeInTheDocument();
    expect(
      within(facts).getByText("JAK1 connects to TYK2 in 1 step in the protein network."),
    ).toBeInTheDocument();
    expect(within(facts).getByRole("link", { name: "STRING" })).toHaveAttribute(
      "href",
      "https://string-db.org/cgi/network?identifiers=9606.ENSP00000342850",
    );
    expect(within(facts).getByRole("link", { name: "Reactome" })).toHaveAttribute(
      "href",
      "https://reactome.org/content/detail/R-HSA-9020933",
    );
  });

  it("names the route through connecting proteins", async () => {
    renderApp(`${E}/evidence?drug=CHEMBL384467`);
    await ready();
    expectOnce(copy.evidence.route.via("Dexamethasone", "NR3C1", "IFNAR2", "STAT1"));
  });

  it("keeps the evidence list and shows no warning box when there are no recorded warnings", async () => {
    renderApp(`${E}/evidence?drug=CHEMBL2103830`);
    await ready();
    expect(screen.getByRole("list", { name: copy.evidence.listLabel })).toBeInTheDocument();
    expect(screen.queryByText(copy.evidence.warningTitle)).not.toBeInTheDocument();
    expect(screen.queryByText(/\bsafe\b/)).not.toBeInTheDocument();
  });
});
