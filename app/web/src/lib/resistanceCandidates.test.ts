import { describe, expect, it } from "vitest";
import { antibioticCandidates, resistanceProfile } from "../test/resistance";
import { formatFeatureValue, splitCandidates } from "./resistanceCandidates";

describe("splitCandidates", () => {
  it("keeps approved drugs in rank order and generated molecules visibly separate", () => {
    const { approved, generated } = splitCandidates(resistanceProfile(), antibioticCandidates());

    expect(approved.map((each) => ({ id: each.id, name: each.name, rank: each.rank }))).toEqual([
      { id: "CHEMBL126", name: "Linezolid", rank: 1 },
      { id: "CHEMBL262777", name: "Vancomycin", rank: 2 },
      { id: "CHEMBL819", name: "Oxacillin", rank: 3 },
    ]);
    expect(generated.map((each) => ({ id: each.id, name: each.name, rank: each.rank }))).toEqual([
      { id: "GEN-0001", name: "Generated example 1", rank: null },
    ]);
  });

  it("joins a defeated candidate's determinants and mechanisms by ARO ID, never by name", () => {
    const profile = resistanceProfile();
    const oxacillin = splitCandidates(profile, antibioticCandidates()).approved.find(
      (each) => each.id === "CHEMBL819",
    );
    expect(oxacillin?.evasionStatus).toBe("ruled_out");
    expect(oxacillin?.defeatedBy).toEqual([
      {
        geneAroId: "ARO:3000617",
        geneLabel: "mecA",
        mechanismAroId: "ARO:0001002",
        mechanismName: "antibiotic target replacement",
      },
    ]);
    expect(oxacillin?.target).toEqual({
      name: "penicillin-binding proteins",
      geneLabels: ["mecA"],
    });
  });

  it("keeps features separate and never turns unavailable data into zero", () => {
    const linezolid = splitCandidates(resistanceProfile(), antibioticCandidates()).approved[0];
    expect(linezolid?.features).toEqual([
      {
        key: "activity",
        available: true,
        displayValue: "2 mg/L (median MIC, fictional)",
        evidenceIds: ["E1"],
      },
      {
        key: "target_hit",
        available: false,
        displayValue: null,
        evidenceIds: [],
      },
      {
        key: "docking",
        available: false,
        displayValue: null,
        evidenceIds: [],
      },
      {
        key: "safety",
        available: true,
        displayValue: "Structural alerts recorded",
        evidenceIds: ["E2"],
      },
    ]);
  });

  it("resolves cited profile evidence (P#) and candidate evidence (E#) in order", () => {
    const linezolid = splitCandidates(resistanceProfile(), antibioticCandidates()).approved[0];
    expect(linezolid?.evidence.map((item) => item.id)).toEqual(["P1", "P2", "E1", "E2"]);
    expect(linezolid?.evidence[0]?.release).toBe("CARD 4.0.2");
    expect(linezolid?.evidence[2]?.release).toBe("ChEMBL 37");
  });

  it("resolves a generated molecule's parent drug name from the candidate pool", () => {
    const [proposal] = splitCandidates(resistanceProfile(), antibioticCandidates()).generated;
    expect(proposal?.generated).toEqual({
      model: "example-generator (fictional)",
      modelVersion: "0",
      seed: 0,
      pocketPdbId: null,
      parentCandidateId: "CHEMBL126",
      parentCandidateName: "Linezolid",
    });
  });
});

describe("formatFeatureValue", () => {
  it("returns null when a feature is unavailable", () => {
    expect(
      formatFeatureValue("docking", {
        available: false,
        value: null,
        unit: null,
        evidence_ids: [],
      }),
    ).toBeNull();
  });

  it("formats known safety codes in plain words", () => {
    expect(
      formatFeatureValue("safety", {
        available: true,
        value: "rules_failed",
        unit: null,
        evidence_ids: ["E4"],
      }),
    ).toBe("Property rules failed");
  });
});
