/**
 * The tick or cross shown after the docking animation: does the drug's best docking score clear
 * the binding threshold? Kept apart from the markup so it can be read and tested on its own.
 *
 * Vina docking scores are more negative for a better fit, so a drug "binds" when its score is at
 * or below the threshold. The score is a rough fit estimate, not a measured affinity
 * (`PoseScore` in the API schema), so the verdict is worded as a prediction.
 */

/**
 * The best docking score (more negative is better) at or below which a drug is predicted to bind.
 *
 * TODO: PROVISIONAL placeholder. Replace with the calibrated value once the team has it, and
 * delete this note. Until then every tick and cross is only as meaningful as this number.
 */
export const BINDING_SCORE_THRESHOLD = -7.0;

export type BindingVerdict = "binds" | "does_not_bind";

/** The verdict for a best docking score, or null when there is no score to judge. */
export function bindingVerdict(
  score: number | null,
  threshold: number = BINDING_SCORE_THRESHOLD,
): BindingVerdict | null {
  if (score === null || Number.isNaN(score)) return null;
  return score <= threshold ? "binds" : "does_not_bind";
}
