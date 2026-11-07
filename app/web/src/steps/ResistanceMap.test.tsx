import { render, screen, waitFor, within } from "@testing-library/react";
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
import { ResistanceMap } from "./ResistanceMap";

const text = copy.resistance.map;
const MAP_PATH = `/resistance/${PROFILE_ID}/map`;

/** The map on its own, with whatever data a test wants to give it. */
function renderMap(candidates = antibioticCandidates()) {
  return render(<ResistanceMap profile={resistanceProfile()} candidates={candidates} />);
}

/** The matrix, found by the caption that says how to read it. */
function matrix() {
  return screen.getByRole("table", { name: text.caption });
}

/** The row for one drug class, by the words in its row header. */
function classRow(name: string) {
  const header = screen.getByRole("rowheader", { name: new RegExp(name, "i") });
  const row = header.closest("tr");
  if (row === null) throw new Error(`No row for ${name}`);
  return row;
}

describe("the resistance map", () => {
  it("leads with what the mechanisms rule out", () => {
    renderMap();

    expect(
      screen.getByText(
        "2 resistance mechanisms in this isolate rule out 5 of the 7 drug classes below.",
      ),
    ).toBeInTheDocument();
  });

  it("names the mechanisms in plain words, with CARD's term beside them", () => {
    renderMap();

    const columns = within(matrix()).getAllByRole("columnheader");
    expect(columns.map((column) => column.textContent)).toEqual([
      text.mechanismsHead,
      text.classHead,
      "Changes what the drug binds CARD: antibiotic target alteration",
      "Swaps in a target the drug can’t bind CARD: antibiotic target replacement",
      text.drugsHead,
    ]);
  });

  it("marks a ruled-out class under the determinant that rules it out, and nowhere else", () => {
    renderMap();

    const cells = within(classRow("penicillin beta-lactam")).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent(text.noMark);
    expect(cells[1]).toHaveTextContent(`${text.status.ruled_out}, mecA`);
  });

  it("says a class is ruled out in words, not only in colour", () => {
    renderMap();

    expect(classRow("cephalosporin")).toHaveTextContent(text.status.ruled_out);
    expect(classRow("oxazolidinone")).toHaveTextContent(text.status.no_known_link);
  });

  it("puts a drug on the row of the class CARD gives it", () => {
    renderMap();

    expect(within(classRow("oxazolidinone")).getByText("Linezolid")).toBeInTheDocument();
    expect(within(classRow("penicillin beta-lactam")).getByText("Oxacillin")).toBeInTheDocument();
    expect(within(classRow("nybomycin-like")).getByText(text.noDrugs)).toBeInTheDocument();
  });

  it("explains every mark on screen, and no mark that isn’t", () => {
    renderMap();

    const section = screen.getByRole("heading", { name: text.keyTitle }).closest("section");
    if (section === null) throw new Error("The key has no section of its own");
    const key = within(section);
    expect(key.getAllByRole("term").map((term) => term.textContent)).toEqual([
      text.status.ruled_out,
      text.status.unknown,
      text.status.no_known_link,
    ]);
    expect(key.getByText(text.statusHelp.no_known_link)).toBeInTheDocument();
    expect(key.getByText(text.statusHelp.ruled_out)).toBeInTheDocument();
    expect(key.getByText(text.statusHelp.unknown)).toBeInTheDocument();
    // Nothing in the fixtures is partly affected, so the map never offers that key.
    expect(screen.queryByText(text.statusHelp.partly_affected)).not.toBeInTheDocument();
  });

  it("names a determinant plainly, with CARD's own name, ID and cited statement", () => {
    renderMap();

    const section = screen
      .getByRole("heading", { name: text.determinantsTitle })
      .closest("section");
    if (section === null) throw new Error("The determinants have no section of their own");
    const list = within(section);
    expect(list.getByText("gyrA S84L")).toBeInTheDocument();
    expect(
      list.getByText("Staphylococcus aureus gyrA conferring resistance to fluoroquinolones"),
    ).toBeInTheDocument();
    expect(list.getByText("ARO:3003296 · protein variant model")).toBeInTheDocument();
    expect(list.getByText(/CARD lists S84L among the resistance variants/)).toBeInTheDocument();
    // A determinant CARD already names plainly is named once, not twice.
    expect(list.getAllByText("mecA")).toHaveLength(1);
  });

  it("says the profile's caveats, its confidence and where the data came from", () => {
    renderMap();

    for (const caveat of resistanceProfile().caveats) {
      expect(screen.getByText(caveat)).toBeInTheDocument();
    }
    expect(screen.getByText(text.confidence.low)).toBeInTheDocument();
    expect(screen.getByText(resistanceProfile().confidence.basis)).toBeInTheDocument();
    expect(screen.getByText(text.built("CARD 4.0.2 and curated supplement 1"))).toBeInTheDocument();
  });

  it("says the numbers are made up, and names the input it could not resolve", () => {
    renderMap();

    expect(screen.getByText(FIXTURE_NOTE)).toBeInTheDocument();
    expect(
      screen.getByText(text.unresolved("blaZZ", "no CARD term or synonym matches this name")),
    ).toBeInTheDocument();
  });

  it("sets aside a molecule CARD gives no drug class, as a proposal rather than a drug", () => {
    renderMap();

    expect(screen.getByText(text.unplaced)).toBeInTheDocument();
    const proposal = screen.getByText("Generated example 1").closest("li");
    expect(proposal).not.toBeNull();
    expect(proposal).toHaveTextContent(text.status.unknown);
    expect(proposal).toHaveTextContent(text.proposed);
  });

  it("still draws the classes ruled out when the ranking has not loaded", () => {
    render(<ResistanceMap profile={resistanceProfile()} candidates={undefined} />);

    expect(
      screen.getByText("2 resistance mechanisms in this isolate rule out 5 drug classes."),
    ).toBeInTheDocument();
    expect(screen.getByText(text.withoutCandidates)).toBeInTheDocument();
    expect(within(matrix()).getAllByRole("rowheader")).toHaveLength(5);
    expect(within(matrix()).queryByText(text.drugsHead)).not.toBeInTheDocument();
    expect(screen.queryByText(FIXTURE_NOTE)).not.toBeInTheDocument();
    expect(screen.queryByText("Linezolid")).not.toBeInTheDocument();
  });

  it("draws nothing and says so when no determinant resolved", () => {
    const profile = resistanceProfile();
    profile.genes = [];
    profile.mechanisms = [];
    profile.defeated_classes = [];
    render(<ResistanceMap profile={profile} candidates={antibioticCandidates()} />);

    expect(screen.getByText(text.nothingMapped)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("is the whole of the map step, drawn from the API", async () => {
    renderApp(MAP_PATH);

    expect(await screen.findByRole("table", { name: text.caption })).toBeInTheDocument();
    expect(within(classRow("penicillin beta-lactam")).getByText("Oxacillin")).toBeInTheDocument();
    expect(screen.getByText(FIXTURE_NOTE)).toBeInTheDocument();
  });

  it("degrades to the profile alone when the ranking fails", async () => {
    server.use(http.untyped.get("*/api/resistance/profiles/:id/candidates", networkError));
    renderApp(MAP_PATH);

    expect(await screen.findByText(text.withoutCandidates)).toBeInTheDocument();
    await waitFor(() => {
      expect(within(matrix()).getAllByRole("rowheader")).toHaveLength(5);
    });
    expect(screen.queryByText("Linezolid")).not.toBeInTheDocument();
  });
});
