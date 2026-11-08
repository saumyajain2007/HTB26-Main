/**
 * Real AutoDock Vina poses for the first antibiotics of a saved ranking, docked into the four
 * prepared bacterial structures by `docking-test/antibiotic_poses.py`. The files stay in
 * `results/antibiotic_docking/` and are imported from there.
 *
 * Read what they are: a pose in a reference pocket (GyrB or LpxC) that these drugs are not known to
 * bind, so it shows how the molecule fits that pocket and not the drug's own binding mode.
 */

interface ManifestJob {
  candidate_id: string;
  structure: string;
  ok: boolean;
  best?: number;
}

interface Manifest {
  jobs: ManifestJob[];
  note: string;
}

const manifests = import.meta.glob<Manifest>("@antibiotic-docking/*/manifest.json", {
  eager: true,
  import: "default",
});
const poseUrls = import.meta.glob<string>("@antibiotic-docking/*/*/*/poses.sdf", {
  eager: true,
  query: "?url",
  import: "default",
});

/** A drug's Vina pose in one prepared structure. */
export interface DockedPose {
  /** Where the pose file is served from. */
  url: string;
  /** Vina's score for the best pose, in kcal/mol; more negative is a better fit. */
  score: number;
}

const poses = new Map<string, DockedPose>();
const failures = new Set<string>();
for (const [path, manifest] of Object.entries(manifests)) {
  const pathogen = path.split("/").at(-2);
  if (pathogen === undefined) continue;
  for (const job of manifest.jobs) {
    if (!job.ok) failures.add(`${job.candidate_id}:${job.structure}`);
    if (!job.ok || job.best === undefined) continue;
    const url = Object.entries(poseUrls).find(([file]) =>
      file.endsWith(`/${pathogen}/${job.candidate_id}/${job.structure}/poses.sdf`),
    )?.[1];
    if (url !== undefined)
      poses.set(`${job.candidate_id}:${job.structure}`, { url, score: job.best });
  }
}

/** The drug's Vina pose in a structure, or undefined when it was not docked there (or failed). */
export function dockedPose(candidateId: string, pdbId: string): DockedPose | undefined {
  return poses.get(`${candidateId}:${pdbId}`);
}

/** True when docking the drug into the structure was tried and gave no pose. */
export function dockingFailed(candidateId: string, pdbId: string): boolean {
  return failures.has(`${candidateId}:${pdbId}`);
}
