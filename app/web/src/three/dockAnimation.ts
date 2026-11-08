/**
 * The motion of the docking animation as pure functions of time, so it can be tested without
 * WebGL. It is an illustration of the verdict, not a simulated trajectory: a drug that binds
 * glides in and settles in its docked pose; one that doesn't approaches, is turned away and
 * drifts back out.
 */
import type { BindingVerdict } from "../lib/bindingVerdict";

export interface DockFrame {
  /** How far from the start toward the docked pose, 0 at the start and 1 fully docked. */
  approach: number;
  /** How much of the starting tumble is left, 1 at the start and 0 when it has aligned. */
  tumble: number;
}

/** Milliseconds each animation takes. */
export const DOCK_DURATION_MS: Record<BindingVerdict, number> = {
  binds: 2600,
  does_not_bind: 3400,
};

/** How close a failed drug gets to the pocket before it is turned away (share of the way). */
export const REJECT_REACH = 0.72;
/** Where a failed drug comes to rest on its way back out (share of the way). */
export const REJECT_REST = 0.4;

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const easeInOut = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const easeOut = (x: number) => 1 - Math.pow(1 - x, 3);

/** The drug's place `elapsedMs` into the animation. Holds its last frame afterwards. */
export function dockFrame(verdict: BindingVerdict, elapsedMs: number): DockFrame {
  const t = clamp01(elapsedMs / DOCK_DURATION_MS[verdict]);
  if (verdict === "binds") {
    return { approach: easeInOut(t), tumble: 1 - easeInOut(clamp01(t * 1.15)) };
  }
  // Approach for the first 55%, then recoil with a decaying wobble.
  const split = 0.55;
  if (t < split) {
    const u = easeInOut(t / split);
    return { approach: REJECT_REACH * u, tumble: 1 - 0.55 * u };
  }
  const u = (t - split) / (1 - split);
  const wobble = Math.sin(u * Math.PI * 5) * (1 - u) * 0.04;
  return {
    approach: REJECT_REACH + (REJECT_REST - REJECT_REACH) * easeOut(u) + wobble,
    tumble: 0.45 + 0.35 * easeOut(u),
  };
}

/** Where the animation ends, for readers who prefer no motion. */
export function dockEndFrame(verdict: BindingVerdict): DockFrame {
  return dockFrame(verdict, DOCK_DURATION_MS[verdict]);
}
