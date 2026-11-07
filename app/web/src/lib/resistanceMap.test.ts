import { describe, expect, it } from "vitest";
import { antibioticCandidates, resistanceProfile } from "../test/resistance";
import type { AntibioticCandidateResult, ResistanceProfile } from "./resistance";
import {
  determinants,
  geneLabel,
  mapClassRows,
  mapMechanisms,
  mapStatus,
  releaseLabel,
  statusesInUse,
  unplacedDrugs,
} from "./resistanceMap";

const MEC_A = "ARO:3000617";
const GYR_A = "ARO:3003296";
const REPLACEMENT = "ARO:0001002"; // antibiotic target replacement, mecA's mechanism
const ALTERATION = "ARO:0001001"; // antibiotic target alteration, gyrA's
const PENICILLIN = "ARO:3000008";
const OXAZOLIDINONE = "ARO:3000079"; // linezolid's class, which nothing in the profile touches

function row(
  profile: ResistanceProfile,
  candidates: AntibioticCandidateResult | undefined,
  aroId: string,
) {
  const found = mapClassRows(profile, candidates).find((candidate) => candidate.aroId === aroId);
  if (found === undefined) throw new Error(`No row for ${aroId}`);
  return found;
}

describe("mapStatus", () => {
  it("keeps no known link and nothing said apart", () => {
    expect(mapStatus("unaffected")).toBe("no_known_link");
    expect(mapStatus("unknown")).toBe("unknown");
    expect(mapStatus("defeated")).toBe("ruled_out");
    expect(mapStatus("partly_affected")).toBe("partly_affected");
  });
});

describe("mapMechanisms", () => {
  it("is one column per mechanism in the profile, in its own order", () => {
    expect(mapMechanisms(resistanceProfile())).toEqual([
      { aroId: ALTERATION, name: "antibiotic target alteration", geneAroIds: [GYR_A] },
      { aroId: REPLACEMENT, name: "antibiotic target replacement", geneAroIds: [MEC_A] },
    ]);
  });
});

describe("mapClassRows", () => {
  it("marks a class in the column of the determinant that rules it out, and nowhere else", () => {
    const penicillin = row(resistanceProfile(), antibioticCandidates(), PENICILLIN);

    expect(penicillin.status).toBe("ruled_out");
    expect(penicillin.cells).toEqual([
      { mechanismAroId: ALTERATION, geneAroIds: [] },
      { mechanismAroId: REPLACEMENT, geneAroIds: [MEC_A] },
    ]);
    expect(penicillin.evidenceIds).toEqual(["P1"]);
  });

  it("joins on ARO IDs, not names", () => {
    const profile = resistanceProfile();
    for (const klass of profile.defeated_classes) klass.name = "renamed";
    for (const gene of profile.genes) {
      for (const klass of gene.defeated_classes) klass.name = "renamed too";
    }

    expect(row(profile, undefined, PENICILLIN).cells[1]?.geneAroIds).toEqual([MEC_A]);
  });

  it("adds the classes the ranked drugs sit in, and takes their standing from evasion", () => {
    const oxazolidinone = row(resistanceProfile(), antibioticCandidates(), OXAZOLIDINONE);

    expect(oxazolidinone.status).toBe("no_known_link");
    expect(oxazolidinone.cells.every((cell) => cell.geneAroIds.length === 0)).toBe(true);
    expect(oxazolidinone.drugs).toEqual([
      {
        id: "CHEMBL126",
        name: "Linezolid",
        status: "no_known_link",
        generated: false,
        className: "oxazolidinone antibiotic",
      },
    ]);
  });

  it("puts the classes ruled out first, gathered by column, and what is left last", () => {
    const rows = mapClassRows(resistanceProfile(), antibioticCandidates());

    expect(rows.map((each) => each.status)).toEqual([
      "ruled_out",
      "ruled_out",
      "ruled_out",
      "ruled_out",
      "no_known_link",
      "no_known_link",
    ]);
    // The first two rows are gyrA's (the first column), the next two mecA's, so the marks sit in
    // blocks rather than scattering.
    expect(rows.slice(0, 4).map((each) => each.name)).toEqual([
      "fluoroquinolone antibiotic",
      "nybomycin-like antibiotic",
      "cephalosporin",
      "penicillin beta-lactam",
    ]);
  });

  it("draws the classes ruled out without the ranked drugs", () => {
    const rows = mapClassRows(resistanceProfile(), undefined);

    expect(rows).toHaveLength(4);
    expect(rows.every((each) => each.status === "ruled_out")).toBe(true);
    expect(rows.every((each) => each.drugs.length === 0)).toBe(true);
  });

  it("keeps a class ruled out by the profile even when a drug on it says otherwise", () => {
    const candidates = antibioticCandidates();
    const oxacillin = candidates.candidates.find((each) => each.name === "OXACILLIN");
    if (oxacillin === undefined) throw new Error("No oxacillin in the fixture");
    oxacillin.evasion.status = "unaffected";

    expect(row(resistanceProfile(), candidates, PENICILLIN).status).toBe("ruled_out");
  });

  it("gives a class the worst standing of the drugs on it", () => {
    const candidates = antibioticCandidates();
    const linezolid = candidates.candidates.find((each) => each.name === "LINEZOLID");
    const vancomycin = candidates.candidates.find((each) => each.name === "VANCOMYCIN");
    if (linezolid === undefined || vancomycin === undefined) throw new Error("Fixture changed");
    // Both in one class, one of them only partly affected.
    vancomycin.drug_class = linezolid.drug_class;
    vancomycin.evasion.status = "partly_affected";

    expect(row(resistanceProfile(), candidates, OXAZOLIDINONE).status).toBe("partly_affected");
  });

  it("has no rows when nothing resolved", () => {
    const profile = resistanceProfile();
    profile.genes = [];
    profile.mechanisms = [];
    profile.defeated_classes = [];

    expect(mapClassRows(profile, undefined)).toEqual([]);
  });

  it("holds a profile of a single determinant", () => {
    const profile = resistanceProfile();
    profile.genes = profile.genes.filter((gene) => gene.aro_id === MEC_A);
    profile.mechanisms = profile.mechanisms.filter((each) => each.aro_id === REPLACEMENT);
    profile.defeated_classes = profile.defeated_classes.filter((each) =>
      each.gene_aro_ids.includes(MEC_A),
    );

    const rows = mapClassRows(profile, undefined);

    expect(rows.map((each) => each.name)).toEqual(["cephalosporin", "penicillin beta-lactam"]);
    // One column, marked on every row.
    expect(rows.map((each) => each.cells.map((cell) => cell.geneAroIds))).toEqual([
      [[MEC_A]],
      [[MEC_A]],
    ]);
  });
});

describe("unplacedDrugs", () => {
  it("is the molecules CARD gives no drug class", () => {
    expect(unplacedDrugs(antibioticCandidates())).toEqual([
      {
        id: "GEN-0001",
        name: "Generated example 1",
        status: "unknown",
        generated: true,
        className: null,
      },
    ]);
  });

  it("is empty while the ranking has not loaded", () => {
    expect(unplacedDrugs(undefined)).toEqual([]);
  });
});

describe("geneLabel", () => {
  const species = "Staphylococcus aureus";

  it("cuts CARD's model name back to the gene and adds its mutations", () => {
    const profile = resistanceProfile();
    expect(profile.genes.map((gene) => geneLabel(gene, species))).toEqual(["mecA", "gyrA S84L"]);
  });

  it("leaves a name it does not recognise whole", () => {
    const [gene] = resistanceProfile().genes;
    if (gene === undefined) throw new Error("Fixture changed");
    const renamed = { ...gene, name: "Escherichia coli ampC", variants: [] };

    expect(geneLabel(renamed, species)).toBe("Escherichia coli ampC");
  });

  it("keeps whatever CARD names before its own phrase", () => {
    const [gene] = resistanceProfile().genes;
    if (gene === undefined) throw new Error("Fixture changed");
    const odd = { ...gene, name: `${species} conferring resistance to everything`, variants: [] };

    expect(geneLabel(odd, species)).toBe(species);
  });

  it("never cuts a name down to nothing", () => {
    const [gene] = resistanceProfile().genes;
    if (gene === undefined) throw new Error("Fixture changed");
    const odd = { ...gene, name: "  conferring resistance to everything", variants: [] };

    expect(geneLabel(odd, species)).toBe("  conferring resistance to everything");
  });
});

describe("determinants", () => {
  it("names each determinant, its CARD model and the statements cited for it", () => {
    const [mecA, gyrA] = determinants(resistanceProfile());

    expect(mecA).toMatchObject({
      aroId: MEC_A,
      label: "mecA",
      cardName: "mecA",
      modelType: "protein homolog model",
      mechanisms: ["antibiotic target replacement"],
      affectedTarget: "beta-lactam sensitive penicillin-binding protein",
      classCount: 2,
    });
    expect(mecA?.evidence[0]?.id).toBe("P1");
    expect(mecA?.evidence[0]?.statement).toContain("CARD links mecA");
    expect(gyrA?.label).toBe("gyrA S84L");
  });

  it("says nothing where CARD names no sensitive target", () => {
    const profile = resistanceProfile();
    const [gene] = profile.genes;
    if (gene === undefined) throw new Error("Fixture changed");
    gene.affected_target = null;

    expect(determinants(profile)[0]?.affectedTarget).toBeNull();
  });
});

describe("statusesInUse", () => {
  it("is every standing on screen, worst first", () => {
    const profile = resistanceProfile();
    const candidates = antibioticCandidates();

    expect(statusesInUse(mapClassRows(profile, candidates), unplacedDrugs(candidates))).toEqual([
      "ruled_out",
      "unknown",
      "no_known_link",
    ]);
  });

  it("is only what the profile says when the ranking has not loaded", () => {
    expect(statusesInUse(mapClassRows(resistanceProfile(), undefined), [])).toEqual(["ruled_out"]);
  });
});

describe("releaseLabel", () => {
  it("puts a CARD release in words", () => {
    expect(releaseLabel("card-4.0.2")).toBe("CARD 4.0.2");
  });

  it("falls back to the shared formatter, and then to the release itself", () => {
    expect(releaseLabel("chembl-36")).toBe("ChEMBL 36");
    expect(releaseLabel("card")).toBe("card");
  });
});
