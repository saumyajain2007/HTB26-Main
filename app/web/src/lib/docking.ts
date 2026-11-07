import type { Candidate, DockJob, Structure } from "../api/types";

/** Which drug can be docked into which prepared structure (plan.md §7). */

/**
 * The structure a Candidate is docked into: its own co-crystal structure when there is one, else
 * the first prepared structure of one of its targets. A structure is only ever used for the
 * protein it contains. Undefined when the Candidate can't be docked.
 */
export function structureFor(
  candidate: Candidate,
  structures: readonly Structure[],
): Structure | undefined {
  if (!candidate.dockable) return undefined;
  const targets = new Set(candidate.targets.map((target) => target.id));
  const usable = structures.filter((structure) => targets.has(structure.target_id));
  return (
    usable.find((structure) => structure.ligand.candidate_id === candidate.candidate_id) ??
    usable[0]
  );
}

/** A drug that can be docked, with the structure it is docked into. */
export interface DockingPair {
  candidate: Candidate;
  structure: Structure;
}

/** The shortlist's drugs that can be docked, in shortlist order. */
export function dockingPairs(
  candidates: readonly Candidate[],
  structures: readonly Structure[],
): DockingPair[] {
  return candidates.flatMap((candidate) => {
    const structure = structureFor(candidate, structures);
    return structure === undefined ? [] : [{ candidate, structure }];
  });
}

/** The drug the step opens on: the known-answer drug when it can be docked, else the first. */
export function defaultDockingChoice(pairs: readonly DockingPair[]): string | undefined {
  const known = pairs.find(({ candidate }) => candidate.known_answer);
  return (known ?? pairs[0])?.candidate.candidate_id;
}

/** The latest request for this drug in this structure on the Experiment, if any. */
export function jobFor(
  jobs: readonly DockJob[],
  candidateId: string,
  structureId: string,
): DockJob | undefined {
  return jobs
    .filter(
      (job) =>
        job.kind === "candidate" &&
        job.candidate_id === candidateId &&
        job.structure_id === structureId,
    )
    .reduce<DockJob | undefined>(
      (latest, job) => (latest === undefined || job.created_at >= latest.created_at ? job : latest),
      undefined,
    );
}

/** The best pose's score, or null until there is one. Pose 1 is the best-scoring pose. */
export function bestScore(job: DockJob): number | null {
  const scores = job.scores ?? [];
  const best = scores.find((score) => score.pose === 1) ?? scores[0];
  return best?.score ?? null;
}
