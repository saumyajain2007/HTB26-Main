import { describe, expect, it } from "vitest";
import { parseGeneList } from "./pathogenInput";

describe("parseGeneList", () => {
  it("reads nothing from text with no entries in it", () => {
    expect(parseGeneList("")).toEqual({ entries: [], repeated: [] });
    expect(parseGeneList("  \n , ; \n\n")).toEqual({ entries: [], repeated: [] });
  });

  it("splits on commas, semicolons and line breaks, in the order typed", () => {
    expect(parseGeneList("mecA, blaZ; tet(K)\nermA\r\nvanA").entries).toEqual([
      "mecA",
      "blaZ",
      "tet(K)",
      "ermA",
      "vanA",
    ]);
  });

  it("keeps a point mutation with its gene, because a space is not a separator", () => {
    expect(parseGeneList("gyrA S84L\ngrlA  S80F").entries).toEqual(["gyrA S84L", "grlA S80F"]);
  });

  it("tidies the whitespace around and inside an entry", () => {
    expect(parseGeneList("   mecA  \n\t ARO:3000617 \t").entries).toEqual(["mecA", "ARO:3000617"]);
  });

  it("keeps the first of a repeat and reports what was repeated, once each", () => {
    expect(parseGeneList("mecA, gyrA S84L, mecA, mecA, blaZ")).toEqual({
      entries: ["mecA", "gyrA S84L", "blaZ"],
      repeated: ["mecA"],
    });
  });

  it("does not treat a difference in case as a repeat: only CARD can say", () => {
    expect(parseGeneList("mecA, MECA")).toEqual({ entries: ["mecA", "MECA"], repeated: [] });
  });
});
