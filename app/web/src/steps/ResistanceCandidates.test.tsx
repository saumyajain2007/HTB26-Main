import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { copy } from "../copy/en";
import { renderApp } from "../test/render";
import {
  FIXTURE_NOTE,
  PROFILE_ID,
  antibioticCandidates,
  resistanceProfile,
} from "../test/resistance";
import { http, networkError, server } from "../test/server";
import { ResistanceCandidates } from "./ResistanceCandidates";

const text = copy.resistance.candidates;
const mapText = copy.resistance.map;
const CANDIDATES_PATH = `/resistance/${PROFILE_ID}/candidates`;

function renderCandidates(candidates = antibioticCandidates()) {
  return render(<ResistanceCandidates profile={resistanceProfile()} candidates={candidates} />);
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

  it("inspects a generated proposal with its generator provenance and unranked kicker", async () => {
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
