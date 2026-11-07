import { Quaternion, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { faceOn, firstMolecule, frame, screenTurn } from "./poseScene";

describe("firstMolecule", () => {
  it("keeps only the best pose of an SDF file", () => {
    const sdf = "pose 1\nM  END\n$$$$\npose 2\nM  END\n$$$$\n";
    expect(firstMolecule(sdf)).toBe("pose 1\nM  END\n$$$$\n");
    expect(firstMolecule("pose 1\nM  END\n")).toBe("pose 1\nM  END\n");
  });
});

describe("faceOn", () => {
  // A flat drug, long along y and thin along z.
  const drug = [
    { x: 0, y: -3, z: 0 },
    { x: 0.8, y: -1, z: 0.05 },
    { x: -0.8, y: 1, z: -0.05 },
    { x: 0, y: 3, z: 0 },
  ];

  it("turns a flat drug to face the reader, its long side across the screen", () => {
    const turn = faceOn(drug, []);
    const long = new Vector3(0, 1, 0).applyQuaternion(turn);
    const thin = new Vector3(0, 0, 1).applyQuaternion(turn);
    expect(Math.abs(long.x)).toBeCloseTo(1, 2);
    expect(Math.abs(thin.z)).toBeCloseTo(1, 2);
  });

  it("looks in from the side with less protein in the way", () => {
    /** Where a wall of protein at depth `z` ends up: below 0 is behind the drug. */
    const wallDepth = (z: number) => {
      const wall = Array.from({ length: 20 }, (_, i) => ({ x: (i % 5) - 2, y: i / 5 - 2, z }));
      return new Vector3(0, 0, z).applyQuaternion(faceOn(drug, wall)).z;
    };
    expect(wallDepth(6)).toBeLessThan(0);
    expect(wallDepth(-6)).toBeLessThan(0);
  });
});

describe("frame", () => {
  const FOV = 20;
  const tan = Math.tan((FOV * Math.PI) / 360);
  // A drug around (10, 0, 0), with a pocket reaching further to the right and up than elsewhere.
  const drug = [new Vector3(4, 0, 0), new Vector3(16, 0, 0), new Vector3(10, 1, 1)];
  const pocket = [new Vector3(0, -6, 0), new Vector3(28, 0, 0), new Vector3(10, 14, -6)];

  /** Where each point lands in the view, as a fraction of its half-width and half-height. */
  function onScreen(points: Vector3[], turn: Quaternion, aspect: number, inset = 0) {
    const { centre, distance } = frame(drug, pocket, turn, aspect, inset, FOV);
    return points.map((point) => {
      const offset = point.clone().sub(centre).applyQuaternion(turn);
      const depth = distance - offset.z;
      return { x: offset.x / depth / (tan * aspect), y: offset.y / depth / tan };
    });
  }

  it("centres the drug and fits its pocket inside the view, with a margin", () => {
    for (const aspect of [0.6, 1, 1.7, 2.4]) {
      const turn = new Quaternion();
      const [middle] = onScreen([new Vector3(10, 0.5, 0.5)], turn, aspect);
      expect(middle?.x).toBeCloseTo(0, 6);
      expect(middle?.y).toBeCloseTo(0, 6);
      const reach = Math.max(
        ...onScreen([...drug, ...pocket], turn, aspect).map(({ x, y }) =>
          Math.max(Math.abs(x), Math.abs(y)),
        ),
      );
      expect(reach).toBeLessThan(0.95);
      expect(reach).toBeGreaterThan(0.85);
    }
  });

  it("frames the view as turned, and comes closer when the view is wider", () => {
    const turn = screenTurn("y", 90).multiply(screenTurn("x", -24));
    const reach = Math.max(
      ...onScreen([...drug, ...pocket], turn, 1.5).map(({ x, y }) =>
        Math.max(Math.abs(x), Math.abs(y)),
      ),
    );
    expect(reach).toBeGreaterThan(0.85);
    expect(reach).toBeLessThan(0.95);
    const narrow = frame(drug, pocket, new Quaternion(), 0.6, 0, FOV).distance;
    const wide = frame(drug, pocket, new Quaternion(), 2, 0, FOV).distance;
    expect(wide).toBeLessThan(narrow);
  });

  it("keeps the drug in the middle and the pocket clear of controls over the view's top", () => {
    const points = onScreen(
      [new Vector3(10, 0.5, 0.5), ...drug, ...pocket],
      new Quaternion(),
      3,
      0.1,
    );
    expect(points[0]?.y).toBeCloseTo(0, 6);
    // The top tenth is covered, and as much is kept clear at the bottom.
    const reach = Math.max(...points.map(({ y }) => Math.abs(y)));
    expect(reach).toBeLessThan(0.8);
    expect(reach).toBeGreaterThan(0.7);
  });

  it("doesn't blow a lone fragment up to fill the view", () => {
    const atom = [new Vector3(1, 2, 3)];
    const { centre, distance } = frame(atom, [], new Quaternion(), 1, 0, FOV);
    expect(centre.toArray()).toEqual([1, 2, 3]);
    expect(distance * tan).toBeGreaterThan(5);
  });
});

describe("screenTurn", () => {
  it("turns about the screen's upright axis, like a turntable", () => {
    const right = new Vector3(1, 0, 0).applyQuaternion(screenTurn("y", 90));
    expect(right.z).toBeCloseTo(-1, 6);
    expect(new Vector3(0, 1, 0).applyQuaternion(screenTurn("y", 30)).y).toBeCloseTo(1, 6);
  });
});
