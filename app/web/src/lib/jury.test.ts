import { describe, expect, it } from "vitest";
import type { Decision, JuryVote } from "../api/types";
import { covidExperiment, covidJury } from "../test/fixtures";
import { copy } from "../copy/en";
import {
  countedJurors,
  decisionCounts,
  excludedJurors,
  failedCheck,
  juryRows,
  lastRank,
  rankSpread,
  retriedCount,
} from "./jury";

describe("the recorded COVID-19 jury", () => {
  const { candidates } = covidExperiment();
  const jury = covidJury();

  it("orders rows by consensus and splits on colchicine only", () => {
    const rows = juryRows(jury, candidates);
    expect(rows.map((row) => row.candidate.name).slice(0, 3)).toEqual([
      "BARICITINIB",
      "TOFACITINIB",
      "TOCILIZUMAB",
    ]);
    expect(rows.filter((row) => row.contested).map((row) => row.candidate.name)).toEqual([
      "COLCHICINE",
    ]);
  });

  it("gives each row its consensus place, tied drugs sharing one, and how far the ranks spread", () => {
    const rows = juryRows(jury, candidates);
    expect(rows.map((row) => row.consensusRank)).toEqual([
      1, 2, 3, 4, 5, 6, 6, 6, 9, 10, 10, 12, 12, 14, 15,
    ]);
    const colchicine = rows.find((row) => row.candidate.name === "COLCHICINE");
    expect(colchicine?.votes.map((vote) => vote?.rank)).toEqual([7, 3, 14]);
    expect(colchicine?.spread).toBe(11);
    expect(lastRank(jury, candidates)).toBe(15);
  });

  it("keeps a drug the consensus doesn't list, last and without a place", () => {
    const partial = {
      ...jury,
      consensus: jury.consensus && {
        ...jury.consensus,
        ranking: jury.consensus.ranking.filter((entry) => entry.candidate_id !== "CHEMBL2105759"),
      },
    };
    const rows = juryRows(partial, candidates);
    expect(rows).toHaveLength(15);
    expect(rows.at(-1)?.candidate.name).toBe("BARICITINIB");
    expect(rows.at(-1)?.consensusRank).toBeNull();
  });

  it("counts valid jurors only, and the one that needed a retry", () => {
    expect(countedJurors(jury)).toHaveLength(3);
    expect(excludedJurors(jury)).toEqual([]);
    expect(retriedCount(jury)).toBe(1);
  });

  it("has an agreement that matches Kendall's W of the ranks", () => {
    const n = candidates.length;
    const sums = candidates.map((c) =>
      jury.votes.filter((v) => v.candidate_id === c.candidate_id).reduce((s, v) => s + v.rank, 0),
    );
    const s = sums.reduce((total, sum) => total + (sum - (3 * (n + 1)) / 2) ** 2, 0);
    expect(jury.agreement).toBeCloseTo((12 * s) / (9 * (n ** 3 - n)), 4);
    expect(jury.agreement).toBeCloseTo(0.6167, 4);
  });
});

describe("failedCheck", () => {
  it("names the check the last attempt failed", () => {
    expect(
      failedCheck([
        "Attempt 1: C2: evidence belongs to another Candidate",
        "Attempt 2: C9: unsupported or unparseable number in objection",
      ]),
    ).toBe("numbers");
  });

  it("names the most basic failure when one attempt failed several checks", () => {
    expect(
      failedCheck([
        "Attempt 1: C3: unsupported or unparseable number in rationale",
        "Attempt 1: C5: unknown evidence ID",
      ]),
    ).toBe("unknownEvidence");
  });

  it("recognises refusals, and names nothing for errors it doesn't know", () => {
    expect(failedCheck(["Attempt 1: refused (provider stop_reason=refusal)"])).toBe("refused");
    expect(failedCheck(["Attempt 1: call failed (TimeoutError)"])).toBeNull();
    expect(failedCheck([])).toBeNull();
  });
});

describe("one drug's verdict", () => {
  const [recorded] = covidJury().votes;
  if (recorded === undefined) throw new Error("No votes in the fixture");
  const vote = (rank: number, decision: Decision): JuryVote => ({ ...recorded, rank, decision });

  it("counts each decision, most promising first, skipping missing votes", () => {
    const votes = [vote(3, "watch"), null, vote(1, "investigate"), vote(9, "watch")];
    expect(decisionCounts(votes)).toEqual([
      { decision: "investigate", count: 1 },
      { decision: "watch", count: 2 },
    ]);
    expect(rankSpread(votes)).toBe(8);
    expect(rankSpread([vote(4, "watch"), null])).toBeNull();
  });

  it("reads as plain words for every size of jury", () => {
    const all = (count: number) => [{ decision: "investigate" as const, count }];
    expect(copy.jury.verdict(all(3), true)).toBe("All 3 say Investigate");
    expect(copy.jury.verdict(all(2), true)).toBe("Both say Investigate");
    expect(copy.jury.verdict(all(1), true)).toBe("1 says Investigate");
    // One model didn't rank it, so the other two aren't "all".
    expect(copy.jury.verdict(all(2), false)).toBe("2 say Investigate");
    expect(
      copy.jury.verdict(
        [
          { decision: "investigate", count: 2 },
          { decision: "deprioritise", count: 1 },
        ],
        true,
      ),
    ).toBe("2 say Investigate, 1 says Set aside");
  });
});
