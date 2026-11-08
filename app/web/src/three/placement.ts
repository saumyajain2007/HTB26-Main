import type { AtomSpec } from "3dmol";
import { Quaternion, Vector3 } from "three";

/** Rigid illustrative frames ending at the prediction; these are not simulated dynamics. */
export function placementFrames(ligand: readonly AtomSpec[], protein: readonly AtomSpec[]) {
  const point = (a: AtomSpec) => new Vector3(a.x ?? 0, a.y ?? 0, a.z ?? 0);
  const centre = (atoms: readonly AtomSpec[]) => {
    const sum = new Vector3();
    for (const atom of atoms) sum.add(point(atom));
    return sum.divideScalar(Math.max(1, atoms.length));
  };
  const origin = centre(ligand);
  const outward = origin.clone().sub(centre(protein));
  if (outward.lengthSq() < 1e-6) outward.set(0, 0, 1);
  outward.normalize();
  return Array.from({ length: 61 }, (_, i) => {
    const t = i / 60;
    const remaining = 1 - t * t * (3 - 2 * t);
    const rotation = new Quaternion().setFromAxisAngle(outward, (remaining * Math.PI) / 4);
    return ligand.map((atom) => {
      if (i === 60) return { ...atom };
      const p = point(atom)
        .sub(origin)
        .applyQuaternion(rotation)
        .add(origin)
        .addScaledVector(outward, remaining * 12);
      return { ...atom, x: p.x, y: p.y, z: p.z };
    });
  });
}
