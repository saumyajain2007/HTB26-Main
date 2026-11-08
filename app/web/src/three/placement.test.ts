import { expect, it } from "vitest";
import { placementFrames } from "./placement";

it("preserves molecular geometry and ends at the exact saved coordinates", () => {
  const atoms = [
    { x: 1, y: 2, z: 3 },
    { x: 2, y: 2, z: 3 },
    { x: 1, y: 3, z: 3 },
  ];
  const before = structuredClone(atoms);
  const frames = placementFrames(atoms, [{ x: 0, y: 0, z: 0 }]);
  expect(frames.at(-1)).toEqual(atoms);
  expect(frames[0]).not.toEqual(atoms);
  for (const frame of frames) {
    const a = frame[0];
    const b = frame[1];
    if (!a || !b) throw new Error("Missing animation atoms");
    expect(
      Math.hypot((b.x ?? 0) - (a.x ?? 0), (b.y ?? 0) - (a.y ?? 0), (b.z ?? 0) - (a.z ?? 0)),
    ).toBeCloseTo(1, 10);
  }
  expect(atoms).toEqual(before);
});
