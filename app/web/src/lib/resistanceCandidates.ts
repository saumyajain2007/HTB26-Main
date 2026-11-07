/**
 * Derivations for the candidate antibiotics view (issue #31), kept apart from the markup so they
 * can be read and tested on their own, as `lib/resistanceMap.ts` is.
 *
 * Rules from `docs/contracts.md`:
 * - Approved drugs (`source: "approved"`) carry ranks `1..n` and are ordered by `rank`.
 * - Generated molecules (`source: "generated"`) have `rank: null` and are kept visibly separate
 *   from approved drugs; they are never ranked alongside them.
 * - Joins between a candidate and the `ResistanceProfile` use ARO IDs, never display names.
 * - Features (`activity`, `target_hit`, `docking`, `safety`) are kept separate, never blended
 *   into a single score, and `available: false` is never turned into zero.
 */
import { capitalise, drugName } from "./format";
import type {
  AntibioticCandidate,
  AntibioticCandidateResult,
  ResistanceProfile,
} from "./resistance";
import { geneLabel, mapStatus, releaseLabel, type MapStatus } from "./resistanceMap";

export type FeatureKey = "activity" | "target_hit" | "docking" | "safety";

export const FEATURE_KEYS: readonly FeatureKey[] = ["activity", "target_hit", "docking", "safety"];

/** A determinant in the profile that rules out or partly affects a candidate, joined by ARO ID. */
export interface DefeatingDeterminant {
  geneAroId: string;
  /** Short determinant label from the profile, e.g. "mecA" or "gyrA S84L". */
  geneLabel: string;
  mechanismAroId: string;
  /** CARD's mechanism term, e.g. "antibiotic target replacement". */
  mechanismName: string;
}

/** One separate feature on a candidate (`docs/contracts.md`). */
export interface CandidateFeatureRow {
  key: FeatureKey;
  available: boolean;
  /** Formatted value and unit when `available` is true, or null when unavailable. */
  displayValue: string | null;
  evidenceIds: readonly string[];
}

/** A cited evidence statement (either `P#` from the profile or `E#` from the candidate). */
export interface CitedStatement {
  id: string;
  source: string;
  release: string;
  statement: string;
}

/** Provenance of a generated molecule, with its parent candidate resolved if present. */
export interface GeneratedInfo {
  model: string;
  modelVersion: string;
  seed: number;
  pocketPdbId: string | null;
  parentCandidateId: string | null;
  parentCandidateName: string | null;
}

/** One prepared candidate for the list and reading pane. */
export interface CandidateEntry {
  id: string;
  name: string;
  source: "approved" | "generated";
  rank: number | null;
  smiles: string;
  inchikey: string;
  drugClass: { aroId: string; name: string } | null;
  mechanismOfAction: string | null;
  target: { name: string; geneLabels: readonly string[] } | null;
  evasionStatus: MapStatus;
  evasionRationale: string;
  defeatedBy: readonly DefeatingDeterminant[];
  features: readonly CandidateFeatureRow[];
  activitySummary: string | null;
  explanation: {
    summary: string;
    mechanismsEvaded: readonly string[];
    missing: readonly string[];
    caveats: readonly string[];
  };
  smokeTest: AntibioticCandidate["smoke_test"];
  certificateStatus: AntibioticCandidate["certificate_status"];
  certificate: AntibioticCandidate["certificate"];
  generated: GeneratedInfo | null;
  evidence: readonly CitedStatement[];
}

const SAFETY_VALUES: Record<string, string> = {
  alerts_recorded: "Structural alerts recorded",
  rules_failed: "Property rules failed",
  passed: "Passed property rules",
};

/** Formats a single feature value without blending or inventing zeros for missing data. */
export function formatFeatureValue(
  key: FeatureKey,
  feature: AntibioticCandidate["features"][FeatureKey],
): string | null {
  if (!feature.available || feature.value === null) return null;
  if (key === "safety" && typeof feature.value === "string") {
    return SAFETY_VALUES[feature.value] ?? capitalise(feature.value.replaceAll("_", " "));
  }
  const raw = typeof feature.value === "number" ? String(feature.value) : feature.value;
  return feature.unit !== null && feature.unit !== "" ? `${raw} ${feature.unit}` : raw;
}

function buildEntry(
  candidate: AntibioticCandidate,
  profile: ResistanceProfile,
  allNames: ReadonlyMap<string, string>,
): CandidateEntry {
  const species = profile.input.species.name;
  const geneLabels = new Map(profile.genes.map((gene) => [gene.aro_id, geneLabel(gene, species)]));
  const mechanismNames = new Map<string, string>();
  for (const mechanism of profile.mechanisms) {
    mechanismNames.set(mechanism.aro_id, mechanism.name);
  }
  for (const gene of profile.genes) {
    for (const mechanism of gene.mechanisms) {
      if (!mechanismNames.has(mechanism.aro_id)) {
        mechanismNames.set(mechanism.aro_id, mechanism.name);
      }
    }
  }
  const profileEvidence = new Map(profile.evidence.map((item) => [item.id, item]));

  const defeatedBy: DefeatingDeterminant[] = candidate.evasion.defeated_by.map((hit) => ({
    geneAroId: hit.gene_aro_id,
    geneLabel: geneLabels.get(hit.gene_aro_id) ?? hit.gene_aro_id,
    mechanismAroId: hit.mechanism_aro_id,
    mechanismName: mechanismNames.get(hit.mechanism_aro_id) ?? hit.mechanism_aro_id,
  }));

  const features: CandidateFeatureRow[] = FEATURE_KEYS.map((key) => {
    const feature = candidate.features[key];
    return {
      key,
      available: feature.available,
      displayValue: formatFeatureValue(key, feature),
      evidenceIds: feature.evidence_ids,
    };
  });

  const fromProfile: CitedStatement[] = candidate.evasion.profile_evidence_ids.flatMap((id) => {
    const item = profileEvidence.get(id);
    if (item === undefined) return [];
    return [
      {
        id: item.id,
        source: item.source.toUpperCase(),
        release: releaseLabel(item.release),
        statement: item.statement,
      },
    ];
  });

  const fromCandidate: CitedStatement[] = candidate.evidence.map((item) => ({
    id: item.id,
    source: item.source,
    release: releaseLabel(item.release),
    statement: item.statement,
  }));

  const parentId = candidate.generated?.parent_candidate_id ?? null;

  return {
    id: candidate.candidate_id,
    name: drugName(candidate.name),
    source: candidate.source,
    rank: candidate.rank,
    smiles: candidate.smiles,
    inchikey: candidate.inchikey,
    drugClass:
      candidate.drug_class === null
        ? null
        : { aroId: candidate.drug_class.aro_id, name: candidate.drug_class.name },
    mechanismOfAction: candidate.mechanism_of_action,
    target:
      candidate.target === null
        ? null
        : {
            name: candidate.target.name,
            geneLabels: candidate.target.gene_aro_ids.map(
              (aroId) => geneLabels.get(aroId) ?? aroId,
            ),
          },
    evasionStatus: mapStatus(candidate.evasion.status),
    evasionRationale: candidate.evasion.rationale,
    defeatedBy,
    features,
    activitySummary: formatFeatureValue("activity", candidate.features.activity),
    explanation: {
      summary: candidate.explanation.summary,
      mechanismsEvaded: candidate.explanation.mechanisms_evaded,
      missing: candidate.explanation.missing,
      caveats: candidate.explanation.caveats,
    },
    smokeTest: candidate.smoke_test,
    certificateStatus: candidate.certificate_status,
    certificate: candidate.certificate,
    generated:
      candidate.generated === null
        ? null
        : {
            model: candidate.generated.model,
            modelVersion: candidate.generated.model_version,
            seed: candidate.generated.seed,
            pocketPdbId: candidate.generated.pocket_pdb_id,
            parentCandidateId: parentId,
            parentCandidateName: parentId === null ? null : (allNames.get(parentId) ?? parentId),
          },
    evidence: [...fromProfile, ...fromCandidate],
  };
}

/**
 * Splits a ranking result into approved drugs (in rank order `1..n`) and generated molecules
 * (`rank: null`, kept visibly apart).
 */
export function splitCandidates(
  profile: ResistanceProfile,
  result: AntibioticCandidateResult,
): {
  approved: CandidateEntry[];
  generated: CandidateEntry[];
} {
  const allNames = new Map(
    result.candidates.map((candidate) => [candidate.candidate_id, drugName(candidate.name)]),
  );
  const approved = result.candidates
    .filter((candidate) => candidate.source === "approved")
    .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
    .map((candidate) => buildEntry(candidate, profile, allNames));

  const generated = result.candidates
    .filter((candidate) => candidate.source === "generated")
    .map((candidate) => buildEntry(candidate, profile, allNames));

  return { approved, generated };
}
