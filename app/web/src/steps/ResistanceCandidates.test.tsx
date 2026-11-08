import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { copy } from "../copy/en";
import { renderApp } from "../test/render";
import {
  FIXTURE_NOTE,
  PROFILE_ID,
  antibioticCandidates,
  certificates,
  resistanceProfile,
} from "../test/resistance";
import { http, networkError, server } from "../test/server";
import { ResistanceCandidates } from "./ResistanceCandidates";

const text = copy.resistance.candidates;
const mapText = copy.resistance.map;
const CANDIDATES_PATH = `/resistance/${PROFILE_ID}/candidates`;

function renderCandidates(candidates = antibioticCandidates(), certs = certificates()) {
  return render(
    <ResistanceCandidates
      profile={resistanceProfile()}
      candidates={candidates}
      certificates={certs}
    />,
  );
}

function approvedTable() {
  return screen.getByRole("table", { name: text.approvedTableLabel });
}

function generatedList() {
  return screen.getByRole("list", { name: text.generatedListLabel });
}

function readingPane(name: string) {
  return screen.getByRole("region", { name: text.readingLabel(name) });
}

function rulesTable(name: string) {
  return screen.getByRole("table", { name: text.rulesTableLabel(name) });
}

describe("the candidate antibiotics view", () => {
  it("lists approved antibiotics in rank order and keeps generated proposals in a separate section", () => {
    renderCandidates();

    const rows = within(approvedTable()).getAllByRole("rowheader");
    expect(rows.map((cell) => cell.textContent)).toEqual([
      "LinezolidOxazolidinone antibiotic",
      "VancomycinGlycopeptide antibiotic",
      "OxacillinPenicillin beta-lactam",
    ]);
    // Generated example 1 never appears in the approved table.
    expect(within(approvedTable()).queryByText("Generated example 1")).not.toBeInTheDocument();

    const proposals = within(generatedList()).getAllByRole("listitem");
    expect(proposals).toHaveLength(1);
    expect(proposals[0]).toHaveTextContent("Generated example 1");
    expect(proposals[0]).toHaveTextContent(text.proposalBadge);
  });

  it("opens on the top-ranked approved drug with its explanation, separate features, evidence, jury note and caveats", () => {
    renderCandidates();

    const pane = within(readingPane("Linezolid"));
    expect(pane.getByText(text.approvedKicker(1))).toBeInTheDocument();
    expect(
      pane.getByText(
        "Ranked first: its class is not linked to either resistance mechanism in the profile, and it has activity data against S. aureus.",
      ),
    ).toBeInTheDocument();
    expect(pane.getByText("2 mg/L (median MIC, fictional)")).toBeInTheDocument();
    expect(pane.getAllByText(text.featureUnavailable)).toHaveLength(2);
    expect(pane.getByText("Structural alerts recorded")).toBeInTheDocument();
    expect(pane.getByText(/Passes all encoded property rules/)).toBeInTheDocument();
    expect(pane.getByText(/Lean 4\.35\.0/)).toBeInTheDocument();
    expect(
      pane.getByText("Median MIC across records against S. aureus (value fictional)."),
    ).toBeInTheDocument();
    expect(pane.getByText(text.juryPending)).toBeInTheDocument();
    expect(
      pane.getByText("Evasion here means no known link in CARD. It is not a measured result."),
    ).toBeInTheDocument();
  });

  it("shows passed rules, highlighted failing rules with margins, alerts, SA score and Lean 4 certificate details", async () => {
    const user = userEvent.setup();
    renderCandidates();

    // Linezolid: all 6 rules passed and confirmed in Lean 4, with alerts warning and SA score.
    const linezolidPane = within(readingPane("Linezolid"));
    const linezolidRules = within(rulesTable("Linezolid")).getAllByRole("row").slice(1);
    expect(linezolidRules).toHaveLength(6);
    expect(linezolidRules.every((row) => row.getAttribute("data-passed") === "true")).toBe(true);
    expect(within(rulesTable("Linezolid")).getAllByText(text.ruleConfirmed)).toHaveLength(6);
    expect(linezolidPane.getByText("-512.86")).toBeInTheDocument();
    expect(linezolidPane.getByText("-268.89")).toBeInTheDocument();
    expect(linezolidPane.getByText(/anil_di_alk_A\(478\)/)).toBeInTheDocument();
    expect(linezolidPane.getByText(text.alertsWarningNote)).toBeInTheDocument();
    expect(linezolidPane.getByText(text.saScore(2.76))).toBeInTheDocument();
    expect(linezolidPane.getByText(text.heavyAtoms(24))).toBeInTheDocument();
    expect(linezolidPane.getByText("TYZROVQLWOKYKF-ZDUSSCGKSA-N")).toBeInTheDocument();
    expect(linezolidPane.getByText(text.leanRanCertified(6))).toBeInTheDocument();
    expect(linezolidPane.getByText(text.certificateScopeConfirmed)).toBeInTheDocument();

    // Vancomycin: 4 failing rules highlighted (data-passed="false") alongside 2 passed rules.
    await user.click(within(approvedTable()).getByRole("button", { name: /Vancomycin/i }));
    const vancoPane = within(readingPane("Vancomycin"));
    const vancoRules = within(rulesTable("Vancomycin")).getAllByRole("row").slice(1);
    const failedRows = vancoRules.filter((row) => row.getAttribute("data-passed") === "false");
    const passedRows = vancoRules.filter((row) => row.getAttribute("data-passed") === "true");
    expect(failedRows.map((row) => row.getAttribute("data-rule"))).toEqual([
      "mw",
      "hbd",
      "hba",
      "psa",
    ]);
    expect(passedRows.map((row) => row.getAttribute("data-rule"))).toEqual(["logp", "rot_bonds"]);
    expect(vancoPane.getByText("+597.43")).toBeInTheDocument();
    expect(vancoPane.getByText("+190.49")).toBeInTheDocument();
    expect(vancoPane.getByText("-4.89")).toBeInTheDocument();
    expect(vancoPane.getByText(text.noAlerts)).toBeInTheDocument();
    expect(
      vancoPane.getByText(`${text.saScore(8.21)} — ${text.saAboveCeiling(6.5)}`),
    ).toBeInTheDocument();
    expect(vancoPane.getByText(/Tactic `decide` proved that the proposition/)).toBeInTheDocument();
  });

  it("switches to another approved drug when picked, showing rule failures and defeated determinants", async () => {
    const user = userEvent.setup();
    renderCandidates();

    await user.click(within(approvedTable()).getByRole("button", { name: /Vancomycin/i }));
    const vancoPane = within(readingPane("Vancomycin"));
    expect(vancoPane.getByText(text.approvedKicker(2))).toBeInTheDocument();
    expect(vancoPane.getByText(/Fails 4 encoded property rules/)).toBeInTheDocument();
    expect(
      vancoPane.getByText(
        "The antibiotic_relaxed limits mark where 95% of approved antibiotics sit, so failing them flags a large glycopeptide as an outlier. It does not make the drug unsafe or inactive.",
      ),
    ).toBeInTheDocument();

    await user.click(within(approvedTable()).getByRole("button", { name: /Oxacillin/i }));
    const oxaPane = within(readingPane("Oxacillin"));
    expect(oxaPane.getByText(text.approvedKicker(3))).toBeInTheDocument();
    expect(oxaPane.getByText(/Affected in this isolate by mecA/)).toBeInTheDocument();
    expect(
      oxaPane.getByText(
        /Swaps in a target the drug can’t bind \(CARD: antibiotic target replacement\)/,
      ),
    ).toBeInTheDocument();
  });

  it("inspects a generated proposal with its generator provenance, passed smoke-test rules and unrun Lean status", async () => {
    const user = userEvent.setup();
    renderCandidates();

    await user.click(within(generatedList()).getByRole("button", { name: /Generated example 1/i }));
    const pane = within(readingPane("Generated example 1"));
    expect(pane.getByText(text.generatedKicker)).toBeInTheDocument();
    expect(pane.getByText("Model example-generator (fictional) (v0), seed 0")).toBeInTheDocument();
    expect(pane.getByText("Derived from Linezolid")).toBeInTheDocument();
    expect(
      pane.getByText("Generated molecules are hypotheses only. This one is a fictional example."),
    ).toBeInTheDocument();

    // All 6 rules pass in the Python smoke test, and the certificate card clearly says Lean did not run.
    const genRules = within(rulesTable("Generated example 1")).getAllByRole("row").slice(1);
    expect(genRules).toHaveLength(6);
    expect(genRules.every((row) => row.getAttribute("data-passed") === "true")).toBe(true);
    expect(within(rulesTable("Generated example 1")).getAllByText(text.rulePassed)).toHaveLength(6);
    expect(pane.getByText(text.leanNotRun)).toBeInTheDocument();
    expect(
      pane.getByText("Lean is not installed or the HtbVerify library did not build"),
    ).toBeInTheDocument();
    expect(pane.getByText(text.certificateScopeSmokeOnly)).toBeInTheDocument();
  });

  it("moves between candidates with ArrowDown and ArrowUp without leaving the step", async () => {
    const user = userEvent.setup();
    renderCandidates();

    const firstButton = within(approvedTable()).getByRole("button", { name: /Linezolid/i });
    firstButton.focus();
    await user.keyboard("{ArrowDown}");
    expect(readingPane("Vancomycin")).toBeInTheDocument();

    await user.keyboard("{End}");
    expect(readingPane("Generated example 1")).toBeInTheDocument();

    await user.keyboard("{Home}");
    expect(readingPane("Linezolid")).toBeInTheDocument();
  });

  it("shows the fixture note, profile caveats and data releases in the footer", () => {
    renderCandidates();

    expect(screen.getByText(FIXTURE_NOTE)).toBeInTheDocument();
    for (const caveat of resistanceProfile().caveats) {
      expect(screen.getByText(caveat)).toBeInTheDocument();
    }
    expect(
      screen.getByText(mapText.built("CARD 4.0.2, curated supplement 1 and ChEMBL 37")),
    ).toBeInTheDocument();
  });

  it("renders end to end on the candidates route and retries when the ranking fails", async () => {
    server.use(http.untyped.get("*/api/resistance/profiles/:id/candidates", networkError));
    const user = userEvent.setup();
    renderApp(CANDIDATES_PATH);

    expect(await screen.findByText(text.unavailable)).toBeInTheDocument();

    server.resetHandlers();
    await user.click(screen.getByRole("button", { name: copy.retry }));
    expect(await screen.findByRole("table", { name: text.approvedTableLabel })).toBeInTheDocument();
  });
});
