import {
  resistanceStepIndex,
  resistanceStepSlugs,
  stepIndex,
  stepSlugs,
  type ResistanceStepSlug,
  type StepSlug,
} from "../copy/en";

/** Step 1 before any Experiment exists: the disease search that the introduction leads to. */
export const EXPLORE_PATH = "/explore";

/** Where a step lives. Without an Experiment only step 1 has a page: the disease search. */
export function stepPath(experimentId: string | undefined, slug: StepSlug): string | undefined {
  if (experimentId === undefined) return slug === "disease" ? EXPLORE_PATH : undefined;
  return `/e/${encodeURIComponent(experimentId)}/${slug}`;
}

/** The step `offset` places away from `slug`, or undefined past either end. */
export function neighbourStep(slug: StepSlug, offset: -1 | 1): StepSlug | undefined {
  return stepSlugs[stepIndex(slug) + offset];
}

/** Step 1 of the resistance flow, before a profile has been built: the pathogen input. */
export const RESISTANCE_PATH = "/resistance";

/**
 * Where a resistance step lives. Without a profile only step 1 has a page, as in the disease
 * flow: nothing can be mapped before an isolate's determinants are known.
 */
export function resistanceStepPath(
  profileId: string | undefined,
  slug: ResistanceStepSlug,
): string | undefined {
  if (profileId === undefined) return slug === "pathogen" ? RESISTANCE_PATH : undefined;
  return `${RESISTANCE_PATH}/${encodeURIComponent(profileId)}/${slug}`;
}

/** The resistance step `offset` places away from `slug`, or undefined past either end. */
export function neighbourResistanceStep(
  slug: ResistanceStepSlug,
  offset: -1 | 1,
): ResistanceStepSlug | undefined {
  return resistanceStepSlugs[resistanceStepIndex(slug) + offset];
}
