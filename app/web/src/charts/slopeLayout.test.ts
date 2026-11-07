import { describe, expect, it } from "vitest";
import {
  closenessDomain,
  evidenceSlots,
  missingGroups,
  rankBreaks,
  type SlopeRow,
} from "./slopeLayout";

const row = (id: string, extra: Partial<SlopeRow>): SlopeRow => ({
  id,
  name: id,
  networkRank: 1,
  closeness: -1,
  warning: null,
  evidenceRank: 1,
  emphasis: false,
  ...extra,
});

describe("evidenceSlots", () => {
  it("orders the right axis by evidence rank and skips rows without one", () => {
    const rows = [
      row("a", { evidenceRank: 241 }),
      row("b", { evidenceRank: 1 }),
      row("c", { evidenceRank: null }),
      row("d", { evidenceRank: 3 }),
    ];
    expect([...evidenceSlots(rows)]).toEqual([
      ["b", 0],
      ["d", 1],
      ["a", 2],
    ]);
  });
});

describe("missingGroups", () => {
  it("joins consecutive rows that miss closeness for the same reason", () => {
    const rows = [
      row("a", {}),
      row("b", { closeness: null, warning: "zero_null_variance" }),
      row("c", { closeness: null, warning: "zero_null_variance" }),
      row("d", { closeness: null, warning: "insufficient_degree_matched_pool" }),
    ];
    expect(missingGroups(rows)).toEqual([
      { first: 1, last: 2, warning: "zero_null_variance" },
      { first: 3, last: 3, warning: "insufficient_degree_matched_pool" },
    ]);
  });
});

describe("closenessDomain", () => {
  it("spans every value and zero in half steps", () => {
    expect(closenessDomain([-3.1, -1.1])).toEqual([-3.5, 0]);
    expect(closenessDomain([0.7])).toEqual([-1, 1]);
    expect(closenessDomain([])).toEqual([-1, 0]);
  });
});

describe("rankBreaks", () => {
  it("marks jumps between non-consecutive ranks", () => {
    expect(rankBreaks([1, 2, 3, 112, 241])).toEqual([2, 3]);
  });
});
