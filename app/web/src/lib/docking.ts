import type { Candidate, DockJob, PoseFiles, Structure } from "../api/types";

/** Which drug can be docked into which prepared structure (plan.md §7). */

const HUMAN_ENSEMBL_ID = /^ENSG[0-9]{11}$/;

/** True when a prepared structure is a bacterial target (UniProt accession) rather than human. */
export function isBacterialStructure(structure: Structure): boolean {
  return !HUMAN_ENSEMBL_ID.test(structure.target_id);
}

/** Prepared bacterial structures in `GET /api/structures` (e.g. 3G7B, 3U2K, 2VES, 3P3E). */
export function bacterialStructures(structures: readonly Structure[]): Structure[] {
  return structures.filter(isBacterialStructure);
}

/**
 * The structure a Candidate is docked into: its own co-crystal structure when there is one, else
 * the first prepared structure of one of its targets. Matches both human Ensembl `target_id`s and
 * bacterial UniProt `target_id`s / gene symbols. A structure is only ever used for the protein it
 * contains. Undefined when the Candidate can't be docked.
 */
export function structureFor(
  candidate: Candidate,
  structures: readonly Structure[],
): Structure | undefined {
  if (!candidate.dockable) return undefined;
  const targets = new Set(candidate.targets.map((target) => target.id));
  const symbols = new Set(candidate.targets.map((target) => target.name.toLowerCase()));
  const usable = structures.filter(
    (structure) =>
      targets.has(structure.target_id) || symbols.has(structure.target_symbol.toLowerCase()),
  );
  return (
    usable.find((structure) => structure.ligand.candidate_id === candidate.candidate_id) ??
    usable[0]
  );
}

/** Input shape for matching an antibiotic candidate or reading-pane entry to a structure. */
export interface AntibioticStructureCandidate {
  id?: string;
  candidate_id?: string;
  target?: {
    name: string;
    gene_aro_ids?: readonly string[];
    geneLabels?: readonly string[];
  } | null;
  generated?: {
    pocket_pdb_id?: string | null;
    pocketPdbId?: string | null;
  } | null;
  evidence?: readonly {
    id: string;
    source: string;
    source_id?: string;
    statement: string;
  }[];
}

const BACTERIAL_TARGET_ALIASES: Readonly<Record<string, readonly string[]>> = {
  gyrb: ["gyrb", "dna gyrase subunit b", "dna gyrase b", "gyrase b", "p0a0k8"],
  lpxc: ["lpxc", "udp-3-o-acyl-n-acetylglucosamine deacetylase", "p47205"],
};

function matchesTargetText(structure: Structure, text: string): boolean {
  // Match complete tokens/phrases: a generic gyrase label does not identify subunit B.
  const normalize = (value: string) =>
    value
      .toLowerCase()
      .match(/[a-z0-9]+/g)
      ?.join(" ") ?? "";
  const normalized = normalize(text);
  if (normalized === "") return false;
  const symbol = structure.target_symbol.toLowerCase();
  const aliases = [structure.target_id, ...(BACTERIAL_TARGET_ALIASES[symbol] ?? [symbol])];
  return aliases.some((alias) => ` ${normalized} `.includes(` ${normalize(alias)} `));
}

/**
 * All prepared structures matching an antibiotic candidate (co-crystal ligand, generated pocket
 * PDB ID, docking evidence, or bacterial target UniProt ID / symbol), with its own co-crystal or
 * pocket structure ordered first.
 */
export function structuresForAntibiotic(
  candidate: AntibioticStructureCandidate,
  structures: readonly Structure[],
): Structure[] {
  const prepared = bacterialStructures(structures);
  const candidateId = candidate.candidate_id ?? candidate.id ?? "";
  const pocket = candidate.generated?.pocket_pdb_id ?? candidate.generated?.pocketPdbId ?? null;
  const matched: Structure[] = [];
  const seen = new Set<string>();
  const push = (structure: Structure) => {
    if (!seen.has(structure.id)) {
      seen.add(structure.id);
      matched.push(structure);
    }
  };

  if (pocket !== null) {
    const upper = pocket.toUpperCase();
    for (const structure of prepared) {
      if (structure.pdb_id.toUpperCase() === upper || structure.id.toUpperCase() === upper) {
        push(structure);
      }
    }
  }

  for (const structure of prepared) {
    if (candidateId !== "" && structure.ligand.candidate_id === candidateId) {
      push(structure);
    }
  }

  for (const item of candidate.evidence ?? []) {
    if (!["pdb", "htb_docking"].includes(item.source.toLowerCase())) continue;
    const sourceId = item.source_id?.toUpperCase();
    if (sourceId !== undefined) {
      for (const structure of prepared) {
        if (
          structure.pdb_id.toUpperCase() === sourceId ||
          structure.id.toUpperCase() === sourceId
        ) {
          push(structure);
        }
      }
    }
  }

  if (candidate.target !== null && candidate.target !== undefined) {
    const texts = [
      candidate.target.name,
      ...(candidate.target.gene_aro_ids ?? []),
      ...(candidate.target.geneLabels ?? []),
    ];
    for (const structure of prepared) {
      if (texts.some((text) => matchesTargetText(structure, text))) {
        push(structure);
      }
    }
  }

  return matched;
}

/** Primary prepared structure for an antibiotic candidate, or undefined when none matches. */
export function structureForAntibiotic(
  candidate: AntibioticStructureCandidate,
  structures: readonly Structure[],
): Structure | undefined {
  return structuresForAntibiotic(candidate, structures)[0];
}

/** Deterministic UUID for serving a prepared structure's crystal pocket and ligand in 3D. */
export function structurePreviewId(structureId: string): string {
  const hex = Array.from(structureId)
    .map((ch) => ch.charCodeAt(0).toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 12)
    .padEnd(12, "0");
  return `00000000-0000-4000-8000-${hex}`;
}

/** Local crystal coordinates, independent of any redocking-control or candidate job. */
export function dockFilesForStructure(structure: Structure): PoseFiles {
  const previewId = structurePreviewId(structure.id);
  const file = (name: string) => ({ url: `/api/files/${previewId}/${name}` });
  return {
    receptor: file("receptor.pdb"),
    poses: file("poses.sdf"),
    crystal_ligand: file("crystal_ligand.sdf"),
  };
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
