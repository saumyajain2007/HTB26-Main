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
  Certificate,
  ResistanceProfile,
} from "./resistance";
import { geneLabel, mapStatus, releaseLabel, type MapStatus } from "./resistanceMap";

export type FeatureKey = "activity" | "target_hit" | "docking" | "safety";

export const FEATURE_KEYS: readonly FeatureKey[] = ["activity", "target_hit", "docking", "safety"];

export type PropertyRuleKey = "mw" | "logp" | "hbd" | "hba" | "rot_bonds" | "psa";

export const PROPERTY_RULE_KEYS: readonly PropertyRuleKey[] = [
  "mw",
  "logp",
  "hbd",
  "hba",
  "rot_bonds",
  "psa",
];

/**
 * Property rule limits from `core/verify/htb_verify/rules.py` and `lean/HtbVerify/Rules.lean`,
 * used when a candidate's inline `certificate` is null so passed rules and margins are still shown.
 */
export const RULE_LIMITS: Readonly<
  Record<string, Readonly<Record<PropertyRuleKey, number>> | undefined>
> = {
  oral_druglike: {
    mw: 500,
    logp: 5,
    hbd: 5,
    hba: 10,
    rot_bonds: 10,
    psa: 140,
  },
  antibiotic_relaxed: {
    mw: 850,
    logp: 5,
    hbd: 13,
    hba: 17,
    rot_bonds: 13,
    psa: 340,
  },
};

/** Soft synthetic-accessibility ceiling (`sa_max_x10 / 10` in `core/verify/htb_verify/rules.py`). */
export const SA_SOFT_LIMITS: Readonly<Record<string, number | undefined>> = {
  oral_druglike: 6.0,
  antibiotic_relaxed: 6.5,
};

/** One property rule check for the per-candidate smoke-test and certificate table. */
export interface PropertyRuleRow {
  rule: PropertyRuleKey;
  passed: boolean;
  value: number;
  limit: number;
  /** Signed margin (`value - limit`): negative or zero when passed, positive when failed. */
  margin: number;
  /** Formatted signed margin, e.g. `"-512.86"`, `"0"`, or `"+597.43"`. */
  signedMargin: string;
  /** True when a Lean 4 certificate ran and machine-checked this rule. */
  leanChecked: boolean;
}

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
  /** All encoded property rules (passed and failed) with values, limits and signed margins. */
  propertyRules: readonly PropertyRuleRow[];
  passedRuleCount: number;
  failedRuleCount: number;
  saSoftLimit: number | null;
  saExceedsSoftLimit: boolean;
  generated: GeneratedInfo | null;
  evidence: readonly CitedStatement[];
}

const SAFETY_VALUES: Record<string, string> = {
  alerts_recorded: "Structural alerts recorded",
  rules_failed: "Property rules failed",
  passed: "Passed property rules",
};

function isPropertyRuleKey(value: string): value is PropertyRuleKey {
  return (PROPERTY_RULE_KEYS as readonly string[]).includes(value);
}

/** Formats a signed margin from a threshold (`+597.43`, `0`, `-512.86`). */
export function formatSignedMargin(margin: number): string {
  const rounded = Number(margin.toFixed(2));
  if (rounded === 0) return "0";
  return rounded > 0 ? `+${String(rounded)}` : String(rounded);
}

/**
 * Builds the full 6-rule property check table (`mw`, `logp`, `hbd`, `hba`, `rot_bonds`, `psa`)
 * from a candidate's `certificate` when available, or from `smokeTest.descriptors`,
 * `smokeTest.violations` and `RULE_LIMITS` when Lean did not run.
 */
export function buildPropertyRules(
  smokeTest: AntibioticCandidate["smoke_test"],
  certificate: Certificate | null,
): PropertyRuleRow[] {
  if (certificate !== null && certificate.rules.length > 0) {
    return certificate.rules
      .filter((item): item is Certificate["rules"][number] & { rule: PropertyRuleKey } =>
        isPropertyRuleKey(item.rule),
      )
      .map((item) => ({
        rule: item.rule,
        passed: item.passed,
        value: item.value,
        limit: item.limit,
        margin: item.margin,
        signedMargin: formatSignedMargin(item.margin),
        leanChecked: certificate.ran,
      }));
  }

  const violationsByRule = new Map(smokeTest.violations.map((v) => [v.rule, v]));
  const descriptors = smokeTest.descriptors;
  const limits = RULE_LIMITS[smokeTest.rule_set];

  if (descriptors !== null) {
    const rows: PropertyRuleRow[] = [];
    for (const key of PROPERTY_RULE_KEYS) {
      const violation = violationsByRule.get(key);
      const limit = violation?.limit ?? limits?.[key];
      if (limit === undefined) continue;
      const value = descriptors[key];
      const passed = violation === undefined && value <= limit;
      const margin = Number((value - limit).toFixed(2));
      rows.push({
        rule: key,
        passed,
        value,
        limit,
        margin,
        signedMargin: formatSignedMargin(margin),
        leanChecked: false,
      });
    }
    return rows;
  }

  return smokeTest.violations
    .filter(
      (
        v,
      ): v is AntibioticCandidate["smoke_test"]["violations"][number] & {
        rule: PropertyRuleKey;
      } => isPropertyRuleKey(v.rule),
    )
    .map((v) => ({
      rule: v.rule,
      passed: false,
      value: v.value,
      limit: v.limit,
      margin: v.margin,
      signedMargin: formatSignedMargin(v.margin),
      leanChecked: false,
    }));
}

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
  certificatesByKey: ReadonlyMap<string, Certificate>,
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
  const resolvedCertificate =
    candidate.certificate ??
    certificatesByKey.get(`${candidate.inchikey}::${candidate.smoke_test.rule_set}`) ??
    certificatesByKey.get(candidate.inchikey) ??
    null;

  const propertyRules = buildPropertyRules(candidate.smoke_test, resolvedCertificate);
  const passedRuleCount = propertyRules.filter((rule) => rule.passed).length;
  const failedRuleCount =
    propertyRules.length > 0
      ? propertyRules.filter((rule) => !rule.passed).length
      : candidate.smoke_test.violations.length;
  const saSoftLimit = SA_SOFT_LIMITS[candidate.smoke_test.rule_set] ?? null;
  const saExceedsSoftLimit =
    candidate.smoke_test.sa_score !== null &&
    saSoftLimit !== null &&
    candidate.smoke_test.sa_score > saSoftLimit;

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
    certificate: resolvedCertificate,
    propertyRules,
    passedRuleCount,
    failedRuleCount,
    saSoftLimit,
    saExceedsSoftLimit,
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
 * (`rank: null`, kept visibly apart), matching any standalone certificates by InChIKey and rule set.
 */
export function splitCandidates(
  profile: ResistanceProfile,
  result: AntibioticCandidateResult,
  certificates: readonly Certificate[] = [],
): {
  approved: CandidateEntry[];
  generated: CandidateEntry[];
} {
  const allNames = new Map(
    result.candidates.map((candidate) => [candidate.candidate_id, drugName(candidate.name)]),
  );
  const certificatesByKey = new Map<string, Certificate>();
  for (const cert of certificates) {
    certificatesByKey.set(`${cert.inchikey}::${cert.rule_set}`, cert);
    if (!certificatesByKey.has(cert.inchikey)) {
      certificatesByKey.set(cert.inchikey, cert);
    }
  }
  const approved = result.candidates
    .filter((candidate) => candidate.source === "approved")
    .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
    .map((candidate) => buildEntry(candidate, profile, allNames, certificatesByKey));

  const generated = result.candidates
    .filter((candidate) => candidate.source === "generated")
    .map((candidate) => buildEntry(candidate, profile, allNames, certificatesByKey));

  return { approved, generated };
}
