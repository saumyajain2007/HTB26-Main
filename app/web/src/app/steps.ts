import { stepIndex, stepSlugs, type StepSlug } from "../copy/en";

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
