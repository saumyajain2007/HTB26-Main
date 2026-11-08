import { describe, expect, it } from "vitest";
import { antibioticCandidates, certificates, resistanceProfile } from "../test/resistance";
import { formatFeatureValue, formatSignedMargin, splitCandidates } from "./resistanceCandidates";

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

  it("derives all six property rules with signed margins and Lean confirmation for approved drugs", () => {
    const { approved } = splitCandidates(resistanceProfile(), antibioticCandidates());
    const [linezolid, vancomycin] = approved;

    expect(linezolid?.passedRuleCount).toBe(6);
    expect(linezolid?.failedRuleCount).toBe(0);
    expect(linezolid?.saExceedsSoftLimit).toBe(false);
    expect(linezolid?.propertyRules).toEqual([
      {
        rule: "mw",
        passed: true,
        value: 337.14,
        limit: 850,
        margin: -512.86,
        signedMargin: "-512.86",
        leanChecked: true,
      },
      {
        rule: "logp",
        passed: true,
        value: 1.12,
        limit: 5,
        margin: -3.88,
        signedMargin: "-3.88",
        leanChecked: true,
      },
      {
        rule: "hbd",
        passed: true,
        value: 1,
        limit: 13,
        margin: -12,
        signedMargin: "-12",
        leanChecked: true,
      },
      {
        rule: "hba",
        passed: true,
        value: 5,
        limit: 17,
        margin: -12,
        signedMargin: "-12",
        leanChecked: true,
      },
      {
        rule: "rot_bonds",
        passed: true,
        value: 4,
        limit: 13,
        margin: -9,
        signedMargin: "-9",
        leanChecked: true,
      },
      {
        rule: "psa",
        passed: true,
        value: 71.11,
        limit: 340,
        margin: -268.89,
        signedMargin: "-268.89",
        leanChecked: true,
      },
    ]);

    expect(vancomycin?.passedRuleCount).toBe(2);
    expect(vancomycin?.failedRuleCount).toBe(4);
    expect(vancomycin?.saExceedsSoftLimit).toBe(true);
    expect(
      vancomycin?.propertyRules.map((r) => ({
        rule: r.rule,
        passed: r.passed,
        signedMargin: r.signedMargin,
      })),
    ).toEqual([
      { rule: "mw", passed: false, signedMargin: "+597.43" },
      { rule: "logp", passed: true, signedMargin: "-4.89" },
      { rule: "hbd", passed: false, signedMargin: "+6" },
      { rule: "hba", passed: false, signedMargin: "+8" },
      { rule: "rot_bonds", passed: true, signedMargin: "0" },
      { rule: "psa", passed: false, signedMargin: "+190.49" },
    ]);
  });

  it("derives passed rules from descriptors when inline certificate is null and attaches standalone certificates by InChIKey", () => {
    const withoutCerts = splitCandidates(resistanceProfile(), antibioticCandidates()).generated[0];
    expect(withoutCerts?.certificate).toBeNull();
    expect(withoutCerts?.passedRuleCount).toBe(6);
    expect(withoutCerts?.propertyRules.every((rule) => rule.passed && !rule.leanChecked)).toBe(
      true,
    );
    expect(withoutCerts?.propertyRules[0]?.signedMargin).toBe("-496.89");

    const withCerts = splitCandidates(resistanceProfile(), antibioticCandidates(), certificates())
      .generated[0];
    expect(withCerts?.certificate?.inchikey).toBe("BJAMGMKJQLOUBR-ZDUSSCGKSA-N");
    expect(withCerts?.certificate?.ran).toBe(false);
    expect(withCerts?.certificate?.detail).toBe(
      "Lean is not installed or the HtbVerify library did not build",
    );
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

  it("formats signed margins with an explicit plus for rule violations", () => {
    expect(formatSignedMargin(597.43)).toBe("+597.43");
    expect(formatSignedMargin(0)).toBe("0");
    expect(formatSignedMargin(-512.86)).toBe("-512.86");
  });
});
