import { describe, expect, it } from "vitest";
import { BINDING_SCORE_THRESHOLD, bindingVerdict } from "./bindingVerdict";

describe("bindingVerdict", () => {
  it("binds when the score is at or below the threshold (more negative is better)", () => {
    expect(bindingVerdict(-9.1, -7)).toBe("binds");
    expect(bindingVerdict(-7, -7)).toBe("binds");
  });

  it("does not bind when the score is above the threshold", () => {
    expect(bindingVerdict(-6.9, -7)).toBe("does_not_bind");
    expect(bindingVerdict(0, -7)).toBe("does_not_bind");
  });

  it("gives no verdict without a score, never a cross", () => {
    expect(bindingVerdict(null, -7)).toBeNull();
    expect(bindingVerdict(Number.NaN, -7)).toBeNull();
  });

  it("uses the shared threshold by default", () => {
    expect(bindingVerdict(BINDING_SCORE_THRESHOLD)).toBe("binds");
    expect(bindingVerdict(BINDING_SCORE_THRESHOLD + 0.1)).toBe("does_not_bind");
  });
});
