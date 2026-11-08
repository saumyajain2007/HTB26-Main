import { describe, expect, it } from "vitest";
import {
  DOCK_DURATION_MS,
  REJECT_REACH,
  REJECT_REST,
  dockEndFrame,
  dockFrame,
} from "./dockAnimation";

describe("dockFrame", () => {
  it("starts away from the pocket and tumbling, for both verdicts", () => {
    for (const verdict of ["binds", "does_not_bind"] as const) {
      expect(dockFrame(verdict, 0)).toEqual({ approach: 0, tumble: 1 });
    }
  });

  it("a drug that binds ends fully docked and aligned", () => {
    const end = dockEndFrame("binds");
    expect(end.approach).toBeCloseTo(1, 5);
    expect(end.tumble).toBeCloseTo(0, 5);
  });

  it("a drug that binds only ever moves forward", () => {
    let last = -1;
    for (let ms = 0; ms <= DOCK_DURATION_MS.binds; ms += 50) {
      const { approach } = dockFrame("binds", ms);
      expect(approach).toBeGreaterThanOrEqual(last);
      last = approach;
    }
  });

  it("a drug that doesn't bind gets close, then ends short of the pocket and unaligned", () => {
    let peak = 0;
    for (let ms = 0; ms <= DOCK_DURATION_MS.does_not_bind; ms += 25) {
      peak = Math.max(peak, dockFrame("does_not_bind", ms).approach);
    }
    expect(peak).toBeGreaterThan(REJECT_REACH - 0.02);
    expect(peak).toBeLessThan(1);
    const end = dockEndFrame("does_not_bind");
    expect(end.approach).toBeCloseTo(REJECT_REST, 1);
    expect(end.tumble).toBeGreaterThan(0.3);
  });

  it("holds its last frame after the end", () => {
    expect(dockFrame("binds", 99999)).toEqual(dockEndFrame("binds"));
  });
});
