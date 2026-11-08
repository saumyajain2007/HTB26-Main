import { describe, expect, it } from "vitest";
import { covidExperiment, dockJob, structures } from "../test/fixtures";
import {
  bacterialStructures,
  bestScore,
  defaultDockingChoice,
  dockFilesForStructure,
  dockingPairs,
  isBacterialStructure,
  jobFor,
  structureFor,
  structureForAntibiotic,
  structurePreviewId,
  structuresForAntibiotic,
} from "./docking";

const { candidates } = covidExperiment();

function candidate(id: string) {
  const found = candidates.find((c) => c.candidate_id === id);
  if (found === undefined) throw new Error(`No candidate ${id}`);
  return found;
}

describe("structureFor", () => {
  it("prefers the drug's own co-crystal structure, else the first of one of its targets", () => {
    expect(structureFor(candidate("CHEMBL2105759"), structures)?.id).toBe("6WTO_A");
    expect(structureFor(candidate("CHEMBL1789941"), structures)?.id).toBe("6WTN_A");
    expect(structureFor(candidate("CHEMBL221959"), structures)?.id).toBe("6WTO_A");
    expect(structureFor(candidate("CHEMBL468"), structures)?.id).toBe("7BQU_A");
  });

  it("never offers a structure of a protein the drug doesn't act on", () => {
    // Venetoclax's structure (BCL2) is prepared, but no COVID-19 candidate acts on BCL2.
    for (const c of candidates) {
      const structure = structureFor(c, structures);
      if (structure === undefined) continue;
      expect(c.targets.map((t) => t.id)).toContain(structure.target_id);
    }
  });
});

describe("dockingPairs", () => {
  it("keeps the shortlist's dockable drugs, in shortlist order", () => {
    const pairs = dockingPairs(candidates, structures);
    expect(pairs.map(({ candidate: c }) => c.name)).toEqual([
      "BARICITINIB",
      "RUXOLITINIB",
      "TOFACITINIB",
      "UPADACITINIB",
      "FEDRATINIB",
      "THALIDOMIDE",
    ]);
    expect(defaultDockingChoice(pairs)).toBe("CHEMBL2105759");
  });

  it("leaves out a small molecule without what docking needs", () => {
    const blocked = { ...candidate("CHEMBL1789941"), dockable: false };
    expect(dockingPairs([blocked], structures)).toEqual([]);
  });

  it("opens on the first dockable drug when the known answer can't be docked", () => {
    const withoutKnownAnswer = candidates.map((c) =>
      c.known_answer ? { ...c, dockable: false } : c,
    );
    expect(defaultDockingChoice(dockingPairs(withoutKnownAnswer, structures))).toBe(
      "CHEMBL1789941",
    );
    expect(defaultDockingChoice(dockingPairs(candidates, []))).toBeUndefined();
  });
});

describe("jobFor", () => {
  it("finds the latest request for the pair, ignoring controls and other pairs", () => {
    const failed = dockJob("failed", "00000000-0000-4000-8000-000000000001");
    const done = {
      ...dockJob("done", "00000000-0000-4000-8000-000000000002"),
      created_at: "2026-10-25T09:20:00Z",
    };
    const other = dockJob("done", "00000000-0000-4000-8000-000000000003", "CHEMBL1789941");
    const control = { ...dockJob("done"), kind: "redock_control" as const, experiment_id: null };
    expect(jobFor([done, failed, other, control], "CHEMBL2105759", "6WTO_A")?.id).toBe(done.id);
    expect(jobFor([control], "CHEMBL2105759", "6WTO_A")).toBeUndefined();
    expect(bestScore(done)).toBe(-10.2);
    expect(bestScore(failed)).toBeNull();
  });
});

describe("bacterial structures and antibiotic matching", () => {
  it("lists the four bacterial crystal structures (3G7B, 3U2K, 2VES, 3P3E) from GET /api/structures", () => {
    const bacterial = bacterialStructures(structures);
    expect(bacterial.map((s) => s.id)).toEqual(["3G7B_A", "3U2K_A", "2VES_A", "3P3E_A"]);
    expect(bacterial.every(isBacterialStructure)).toBe(true);
    const human = structures[0];
    if (human === undefined) throw new Error("No structures in fixture");
    expect(isBacterialStructure(human)).toBe(false);
  });

  it("matches a Candidate carrying a bacterial UniProt target_id or gene symbol in structureFor", () => {
    const gyrBCandidate = {
      ...candidate("CHEMBL2105759"),
      candidate_id: "CHEMBL1923431",
      targets: [{ id: "P0A0K8", name: "gyrB", mechanism: null }],
    };
    expect(structureFor(gyrBCandidate, structures)?.id).toBe("3U2K_A");

    const lpxCCandidate = {
      ...candidate("CHEMBL2105759"),
      candidate_id: "CHEMBL999999",
      targets: [{ id: "P47205", name: "lpxC", mechanism: null }],
    };
    expect(structureFor(lpxCCandidate, structures)?.id).toBe("2VES_A");
  });

  it("matches an antibiotic candidate by generated pocket_pdb_id, co-crystal ligand, or bacterial target", () => {
    expect(
      structureForAntibiotic(
        {
          id: "GEN-0001",
          generated: { pocketPdbId: "3P3E" },
          target: null,
        },
        structures,
      )?.id,
    ).toBe("3P3E_A");

    expect(
      structureForAntibiotic(
        {
          id: "CHEMBL261713",
          target: null,
        },
        structures,
      )?.id,
    ).toBe("2VES_A");

    const gyrMatches = structuresForAntibiotic(
      {
        id: "CHEMBL-GYR",
        target: { name: "DNA gyrase subunit B (gyrB)", geneLabels: [] },
      },
      structures,
    );
    expect(gyrMatches.map((s) => s.id)).toEqual(["3G7B_A", "3U2K_A"]);
  });

  it("builds deterministic preview file URLs when a structure has no control job_id", () => {
    const gyrB = structures.find((s) => s.id === "3G7B_A");
    if (gyrB === undefined) throw new Error("No 3G7B_A structure in fixture");
    const previewId = structurePreviewId("3G7B_A");
    expect(previewId).toBe("00000000-0000-4000-8000-334737425f41");
    const files = dockFilesForStructure(gyrB);
    expect(files.receptor.url).toBe(`/api/files/${previewId}/receptor.pdb`);
    expect(files.poses.url).toBe(`/api/files/${previewId}/poses.sdf`);
    expect(files.crystal_ligand.url).toBe(`/api/files/${previewId}/crystal_ligand.sdf`);
  });
});
