import { describe, expect, it } from "vitest";
import { drugName, listOf, releaseName, signed } from "./format";

describe("drugName", () => {
  it.each([
    ["BARICITINIB", "Baricitinib"],
    ["ACETYLSALICYLIC ACID", "Acetylsalicylic acid"],
    ["  TOCILIZUMAB ", "Tocilizumab"],
    ["Interferon beta-1a", "Interferon beta-1a"],
  ])("formats %s as %s", (input, expected) => {
    expect(drugName(input)).toBe(expected);
  });
});

describe("signed", () => {
  it("uses a true minus sign and never shows −0", () => {
    expect(signed(-3.1)).toBe("−3.1");
    expect(signed(2)).toBe("2.0");
    expect(signed(-0.01)).toBe("0.0");
    expect(signed(-2, 0)).toBe("−2");
  });
});

describe("listOf", () => {
  it("joins with commas and a final and", () => {
    expect(listOf([])).toBe("");
    expect(listOf(["A"])).toBe("A");
    expect(listOf(["A", "B"])).toBe("A and B");
    expect(listOf(["A", "B", "C"])).toBe("A, B and C");
  });
});

describe("releaseName", () => {
  it("names known sources and leaves others as they are", () => {
    expect(releaseName("opentargets-26.09")).toBe("Open Targets 26.09");
    expect(releaseName("chembl-37")).toBe("ChEMBL 37");
    expect(releaseName("string-12.5")).toBe("STRING 12.5");
    expect(releaseName("pdb-2026")).toBe("pdb-2026");
  });
});
