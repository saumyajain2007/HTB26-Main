"""Retrospective retrieval evaluation of fixed rankings and separate references."""

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from .data import CANDIDATE_ID, DISEASE_ID


SCORE_METHODS = ("direct_evidence", "shared_targets", "raw_proximity", "degree_matched_z")
METHODS = (*SCORE_METHODS, "random")
METRICS = ("recall_at_5", "recall_at_10", "recall_at_20", "mrr")
CLASSIFICATION = "retrospective_known_relationship_recovery"
FORBIDDEN_FEATURE_KEYS = {"disease_ids", "indications", "clinicalReports", "clinical_reports", "known_treatment", "treatment_label", "docking_score"}


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass
class EvaluationCase:
    disease_id: str
    eligible_candidates: tuple[str, ...]
    rankings: dict[str, tuple[str, ...]]
    shortlist: tuple[str, ...]
    provenance: dict


@dataclass(frozen=True)
class EvaluationSettings:
    seed: int = 0
    bootstrap_samples: int = 1000
    missing_score_policy: str = "unretrieved"

    def __post_init__(self):
        if self.missing_score_policy not in ("unretrieved", "append_by_id"):
            raise ValueError("Missing-score policy must be unretrieved or append_by_id")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("Evaluation seed must be a nonnegative integer")
        if isinstance(self.bootstrap_samples, bool) or not isinstance(self.bootstrap_samples, int) or self.bootstrap_samples < 0:
            raise ValueError("bootstrap_samples must be a nonnegative integer")


def validate_case(case: EvaluationCase) -> None:
    if not DISEASE_ID.fullmatch(case.disease_id):
        raise ValueError("Invalid evaluation Disease ID")
    universe = set(case.eligible_candidates)
    if len(universe) != len(case.eligible_candidates) or any(not CANDIDATE_ID.fullmatch(g) for g in universe):
        raise ValueError("Eligible Candidate IDs must be valid and unique")
    if set(case.rankings) != set(SCORE_METHODS):
        raise ValueError(f"Rankings must define exactly {SCORE_METHODS}")
    for name, ordered in [*case.rankings.items(), ("shortlist", case.shortlist)]:
        if len(set(ordered)) != len(ordered) or not set(ordered).issubset(universe):
            raise ValueError(f"{name}: duplicate or ineligible Candidate ID")


def audit_stage2_features(payload: dict) -> dict:
    """Reject explicit label fields; this structural check cannot prove no leakage."""
    rule = payload.get("disease", {}).get("input_rule", {})
    if (rule.get("score") != "evidence_only" or not isinstance(rule.get("excluded_datasources"), list)
            or not {"clinical_precedence", "cancer_biomarkers"}.issubset(rule["excluded_datasources"])):
        raise ValueError("Cannot evaluate Stage 2 input without its evidence_only leakage-control declaration")

    def check(value: object) -> None:
        if isinstance(value, dict):
            if FORBIDDEN_FEATURE_KEYS.intersection(value):
                raise ValueError("Direct treatment/indication/docking label field found in Candidate feature payload")
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(payload.get("candidates", []))
    return {"structural_label_audit": "passed", "excluded_datasources": sorted(rule["excluded_datasources"]),
            "residual_leakage": "Not ruled out: current literature, drug-target curation, network study bias and shared source releases may encode known relationships indirectly."}


def case_from_stage2(payload: dict) -> EvaluationCase:
    audit = audit_stage2_features(payload)
    candidates = payload.get("candidates", [])
    identifiers = [c["candidate_id"] for c in candidates]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate Stage 2 Candidate IDs")

    def number(value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Ranking scores must be finite numbers or null")
        return float(value)

    ordering = {}
    for method in SCORE_METHODS:
        available = []
        for candidate in candidates:
            network = candidate.get("network") or {}
            if method == "direct_evidence":
                value = number(candidate.get("direct_evidence", {}).get("score"))
                breadth = number(candidate.get("direct_evidence", {}).get("breadth"))
                key = None if value is None else (-value, -(breadth or 0), candidate["candidate_id"])
            elif method == "shared_targets":
                value = number(candidate.get("shared_target_count"))
                key = None if value is None else (-value, candidate["candidate_id"])
            elif method == "raw_proximity":
                value = number(network.get("mean_distance"))
                key = None if value is None else (value, candidate["candidate_id"])
            else:
                value, distance = number(network.get("degree_matched_z")), number(network.get("mean_distance"))
                if value is not None and distance is None:
                    raise ValueError("A valid z-score requires an observed distance")
                key = None if value is None else (value, distance, candidate["candidate_id"])
            if key is not None:
                available.append((key, candidate["candidate_id"]))
        ordering[method] = tuple(identifier for _, identifier in sorted(available))
    case = EvaluationCase(payload["disease"]["id"], tuple(sorted(identifiers)), ordering, tuple(payload.get("shortlist", [])),
                          {"ranking": payload.get("provenance", {}), "input_audit": audit})
    validate_case(case)
    return case


def retrieval_metrics(ranked: tuple[str, ...] | list[str], known: set[str] | None, universe: set[str]) -> dict:
    if len(set(ranked)) != len(ranked) or not set(ranked).issubset(universe):
        raise ValueError("Metric ranking must contain unique in-scope Candidate IDs")
    positives = set() if known is None else known & universe
    status = ("missing_labels" if known is None else "empty_universe" if not universe else
              "no_positive_references" if not known else "no_positive_in_scope" if not positives else "evaluated")
    result = {"label_status": status, "reference_total": None if known is None else len(known),
              "positive_in_scope": len(positives), "reference_outside_scope": None if known is None else len(known - universe),
              **{name: None for name in METRICS}}
    if status == "evaluated":
        for k in (5, 10, 20):
            result[f"recall_at_{k}"] = len(set(ranked[:k]) & positives) / len(positives)
        result["mrr"] = next((1 / rank for rank, identifier in enumerate(ranked, 1) if identifier in positives), 0.0)
    return result


def random_ranking(identifiers: set[str], disease_id: str, seed: int) -> tuple[str, ...]:
    """Stable keyed-hash permutation; common scope filters the same full order."""
    return tuple(sorted(identifiers, key=lambda g: (hashlib.sha256(f"{seed}\0{disease_id}\0{g}".encode()).digest(), g)))


def mean_and_interval(values: list[float], settings: EvaluationSettings) -> tuple[float | None, list[float] | None]:
    if not values:
        return None, None
    mean = float(np.mean(values))
    if len(values) < 2 or settings.bootstrap_samples == 0:
        return mean, None
    rng = np.random.Generator(np.random.PCG64(settings.seed))
    samples = rng.choice(np.asarray(values), size=(settings.bootstrap_samples, len(values)), replace=True).mean(axis=1)
    return mean, np.quantile(samples, [0.025, 0.975]).tolist()


def evaluate_cases(cases: list[EvaluationCase], references: dict[str, set[str]], settings: EvaluationSettings = EvaluationSettings()) -> dict:
    """Evaluate separate known labels; never feed them back into rankings."""
    if len({c.disease_id for c in cases}) != len(cases):
        raise ValueError("Duplicate Disease cases")
    rows, coverage_rows, shortlist_rows, comparisons = [], [], [], []
    for case in sorted(cases, key=lambda c: c.disease_id):
        validate_case(case)
        full = set(case.eligible_candidates)
        common = set.intersection(full, *(set(case.rankings[method]) for method in SCORE_METHODS))
        known = references.get(case.disease_id)
        random_order = random_ranking(full, case.disease_id, settings.seed)
        coverage_rows.append({"disease_id": case.disease_id, "eligible_candidates": len(full),
                              "common_scorable": len(common), "common_scorable_fraction": len(common) / len(full) if full else None,
                              "reference_total": None if known is None else len(known),
                              "positive_eligible": None if known is None else len(known & full),
                              "positive_common": None if known is None else len(known & common),
                              "positive_outside_eligible": None if known is None else sorted(known - full),
                              "positive_outside_common": None if known is None else sorted((known & full) - common),
                              "method_scorable": {method: len(case.rankings[method]) for method in SCORE_METHODS}})
        for scope, universe in (("full_eligible", full), ("common_scorable", common)):
            case_rows = {}
            for method in METHODS:
                available = [g for g in (random_order if method == "random" else case.rankings[method]) if g in universe]
                missing = sorted(universe - set(available))
                ranked = available + (missing if settings.missing_score_policy == "append_by_id" else [])
                metrics = retrieval_metrics(ranked, known, universe)
                row = {"disease_id": case.disease_id, "scope": scope, "method": method,
                       "universe_size": len(universe), "scorable_count": len(available), "missing_count": len(missing),
                       "coverage_fraction": len(available) / len(universe) if universe else None,
                       "missing_positive_count": None if known is None else len(set(missing) & known),
                       "missing_candidate_ids": missing, "ranked_candidate_ids": ranked,
                       "missing_score_policy": settings.missing_score_policy, **metrics}
                rows.append(row)
                case_rows[method] = row
            selected = [g for g in case.shortlist[:15] if g in universe]
            selected_metrics = retrieval_metrics(selected, known, universe)
            positives = set() if known is None else known & universe
            shortlist_rows.append({"disease_id": case.disease_id, "scope": scope, "label_status": selected_metrics["label_status"],
                                   "selected_count": len(selected), "known_selected": len(set(selected) & positives),
                                   "positive_in_scope": len(positives), "recall_at_15": len(set(selected) & positives) / len(positives) if positives else None,
                                   "candidate_ids": selected})
            comparisons.append({"disease_id": case.disease_id, "scope": scope,
                                **{f"delta_{metric}": None if case_rows["degree_matched_z"][metric] is None else
                                   case_rows["degree_matched_z"][metric] - case_rows["direct_evidence"][metric] for metric in METRICS}})
    aggregate = []
    for scope in ("full_eligible", "common_scorable"):
        for method in METHODS:
            subset = [r for r in rows if r["scope"] == scope and r["method"] == method]
            evaluated = [r for r in subset if r["label_status"] == "evaluated"]
            summary = {"scope": scope, "method": method, "total_cases": len(subset), "evaluated_cases": len(evaluated),
                       "evaluated_case_ids": [r["disease_id"] for r in evaluated],
                       "skipped_cases": [{"disease_id": r["disease_id"], "reason": r["label_status"]} for r in subset if r["label_status"] != "evaluated"]}
            for metric in METRICS:
                summary[metric], summary[f"{metric}_ci95"] = mean_and_interval([r[metric] for r in evaluated], settings)
            aggregate.append(summary)
    paired = []
    for scope in ("full_eligible", "common_scorable"):
        subset = [r for r in comparisons if r["scope"] == scope and r["delta_mrr"] is not None]
        summary = {"scope": scope, "comparison": "degree_matched_z_minus_direct_evidence", "paired_cases": len(subset),
                   "case_ids": [r["disease_id"] for r in subset]}
        for metric in METRICS:
            summary[f"delta_{metric}"], summary[f"delta_{metric}_ci95"] = mean_and_interval([r[f"delta_{metric}"] for r in subset], settings)
        paired.append(summary)
    return {"classification": CLASSIFICATION, "metrics": rows, "coverage": coverage_rows, "shortlist": shortlist_rows,
            "aggregate": aggregate, "case_comparisons": comparisons, "paired_comparisons": paired}
