"""General-purpose Candidate scoring and deterministic shortlist integration."""

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from . import __version__
from .artifacts import Artifacts, file_record, load_artifacts
from .data import Disease, Drugs, Targets, load_disease, load_drugs
from .proximity import ConditionalNull, nearest_distances


@dataclass(frozen=True)
class RankingSettings:
    top_targets: int = 50
    randomisations: int = 200
    seed: int = 0
    min_bin_size: int = 100
    network_slots: int = 10
    evidence_slots: int = 5

    def __post_init__(self):
        for name, value in asdict(self).items():
            minimum = 2 if name == "randomisations" else 0 if name in ("seed", "network_slots", "evidence_slots") else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")


def coverage(targets: Targets, selected: list[str], graph_ids: set[str], lcc_ids: set[str], upstream_unmapped: list[dict] | None = None) -> dict:
    exclusions = list(targets.exclusions)
    selected_set = set(selected)
    for identifier in targets.rows:
        reason = ("outside_top_n" if identifier not in selected_set else "not_in_graph" if identifier not in graph_ids
                  else "outside_largest_component" if identifier not in lcc_ids else None)
        if reason:
            exclusions.append({"target_id": identifier, "reason": reason})
    retained = sorted(selected_set.intersection(lcc_ids))
    upstream_unmapped = upstream_unmapped or []
    return {
        "total": targets.total, "mapped": len(targets.rows.keys() & graph_ids), "selected": len(selected),
        "selected_mapped": len(selected_set & graph_ids), "retained": len(retained),
        "excluded": targets.total - len(retained), "input_rows": targets.input_rows,
        "duplicates_removed": targets.duplicates_removed, "retained_target_ids": retained,
        "excluded_targets": exclusions,
        "excluded_by_reason": dict(sorted(Counter(row["reason"] for row in exclusions).items())),
        "upstream_unmapped_items": len(upstream_unmapped),
        "upstream_unmapped_by_reason": dict(sorted(Counter(row.get("reason") if isinstance(row.get("reason"), str) else "unknown" for row in upstream_unmapped).items())),
    }


def assign_ranks(candidates: list[dict]) -> None:
    scored = sorted((c for c in candidates if c["status"] == "scored"), key=lambda c: (c["network"]["degree_matched_z"], c["network"]["mean_distance"], c["candidate_id"]))
    distance_only = sorted((c for c in candidates if c["status"] == "distance_only"), key=lambda c: (c["network"]["mean_distance"], c["candidate_id"]))
    for rank, candidate in enumerate([*scored, *distance_only], 1):
        candidate["network"]["rank"] = rank
    evidence = sorted((c for c in candidates if c["direct_evidence"]["score"] is not None),
                      key=lambda c: (-c["direct_evidence"]["score"], -c["direct_evidence"]["breadth"], c["candidate_id"]))
    for rank, candidate in enumerate(evidence, 1):
        candidate["direct_evidence_rank"] = rank
    shared = sorted((c for c in candidates if c["shared_target_count"] is not None), key=lambda c: (-c["shared_target_count"], c["candidate_id"]))
    for rank, candidate in enumerate(shared, 1):
        candidate["shared_target_rank"] = rank


def make_shortlist(candidates: list[dict], settings: RankingSettings) -> list[str]:
    network = sorted((c for c in candidates if c["status"] == "scored"), key=lambda c: c["network"]["rank"])
    evidence = sorted((c for c in candidates if (c["direct_evidence"]["score"] or 0) > 0), key=lambda c: c["direct_evidence_rank"])
    selected: dict[str, dict] = {}

    def add(candidate: dict, source: str, reason: str) -> None:
        selected[candidate["candidate_id"]] = candidate
        if source not in candidate["selected_by"]:
            candidate["selected_by"].append(source)
        candidate["selection_reasons"].append(reason)

    for candidate in network[:settings.network_slots]:
        add(candidate, "network", "initial_network_quota")
    for candidate in evidence[:settings.evidence_slots]:
        add(candidate, "evidence", "initial_evidence_quota")
    target = settings.network_slots + settings.evidence_slots
    # Overlap consumes one slot. Fill from subsequent supported evidence first,
    # then valid network results; never fill with unsupported/scoreless entries.
    for pool, source in ((evidence, "evidence"), (network, "network")):
        for candidate in pool:
            if len(selected) >= target:
                break
            if candidate["candidate_id"] not in selected:
                add(candidate, source, f"{source}_fill_after_deduplication")
    for rank, candidate in enumerate(selected.values(), 1):
        candidate["shortlist_rank"] = rank
    return list(selected)


class RankingEngine:
    """Own no source files and rebuild no graph; the caller owns Artifacts lifetime."""

    def __init__(self, artifacts: Artifacts, settings: RankingSettings = RankingSettings()):
        self.artifacts, self.settings = artifacts, settings
        self.graph_ids = set(artifacts.graph_gene_ids)
        self.lcc_ids = set(artifacts.distance_gene_ids)
        self.index = {identifier: i for i, identifier in enumerate(artifacts.distance_gene_ids)}
        graph_index = {identifier: i for i, identifier in enumerate(artifacts.graph_gene_ids)}
        self.degrees = np.diff(artifacts.graph.indptr)[[graph_index[g] for g in artifacts.distance_gene_ids]]

    def rank(self, disease: Disease, drugs: Drugs) -> dict:
        started = perf_counter()
        if disease.release not in self.artifacts.manifest["releases"] or disease.release not in drugs.releases:
            raise ValueError("Disease, drug and graph Open Targets releases do not match")
        settings = self.settings
        selected = sorted(disease.targets.rows, key=lambda g: (-disease.targets.rows[g]["evidence_only_score"], g))[:settings.top_targets]
        disease_coverage = coverage(disease.targets, selected, self.graph_ids, self.lcc_ids)
        disease_indices = [self.index[g] for g in disease_coverage["retained_target_ids"]]
        nearest = None if not disease_indices else nearest_distances(self.artifacts.distances, disease_indices, self.artifacts.manifest["distances"]["unreachable_sentinel"])
        null = None if nearest is None else ConditionalNull(self.degrees, nearest, disease.id, minimum_size=settings.min_bin_size, randomisations=settings.randomisations, seed=settings.seed)
        disease_scores = {g: row["evidence_only_score"] for g, row in disease.targets.rows.items()}
        candidates = []
        for drug in drugs.drugs:
            target_coverage = coverage(drug.targets, list(drug.targets.rows), self.graph_ids, self.lcc_ids, drug.unmapped)
            retained = [self.index[g] for g in target_coverage["retained_target_ids"]]
            supported = sorted(drug.targets.rows.keys() & disease_scores.keys())
            scores = [disease_scores[g] for g in supported]
            evidence_score = max(scores, default=0.0) if disease_scores else None
            candidate = {
                "candidate_id": drug.id, "name": drug.name, "status": "not_scorable", "network": None,
                "unscorable_reason": None, "coverage": target_coverage,
                "direct_evidence_rank": None, "direct_evidence": {
                    "score": evidence_score, "breadth": sum(scores) if disease_scores else None,
                    "supporting_target_ids": supported, "scope": "supplied_disease_targets",
                    "status": "missing_disease_scores" if not disease_scores else "supported" if evidence_score > 0 else "no_supplied_support",
                },
                "shared_target_count": len(supported) if disease_scores else None, "shared_target_rank": None,
                "targets": [{"id": g, "name": row.get("name", g), "mechanism": row.get("action_type", "unknown"),
                             **{key: row[key] for key in ("support", "median_pchembl", "n_activities", "target_type") if key in row}}
                            for g, row in sorted(drug.targets.rows.items())],
                "approval_sources": drug.approval_sources, "source_chembl_ids": drug.source_chembl_ids,
                "selected_by": [], "selection_reasons": [], "shortlist_rank": None,
            }
            if nearest is None:
                candidate["unscorable_reason"] = "no_retained_disease_targets"
            elif not retained:
                candidate["unscorable_reason"] = "no_retained_drug_targets"
            else:
                observed = float(nearest[retained].mean())
                assessment = null.score(retained, observed)
                candidate.update(status="distance_only" if assessment["warning"] else "scored", network={
                    "rank": None, "mean_distance": observed, **assessment,
                    "direct_overlap_count": len(set(target_coverage["retained_target_ids"]) & set(disease_coverage["retained_target_ids"])),
                    "graph_version": next(r for r in self.artifacts.manifest["releases"] if r.startswith("string-")),
                })
            candidates.append(candidate)
        assign_ranks(candidates)
        shortlist = make_shortlist(candidates, settings)
        settings_payload = asdict(settings)
        warnings = ["Direct-evidence and shared-Target baselines use only supplied Disease Target scores; an absent association is not evidence of no biological association.",
                    "Ranking payload requires Stream A evidence/safety enrichment before jury review; hide scores, ranks and selection reasons from blinded jurors."]
        if not disease.targets.rows:
            warnings.append("No valid Disease evidence_only scores were supplied.")
        return {
            "format_version": 2,
            "disease": {"id": disease.id, "name": disease.name, "coverage": disease_coverage,
                        "selected_target_ids": selected, "input_rule": disease.rule},
            "candidates": candidates, "shortlist": shortlist, "excluded_candidates": drugs.excluded,
            "summary": {"eligible_candidates": len(candidates), "statuses": dict(Counter(c["status"] for c in candidates)),
                        "network_warnings": dict(Counter(c["network"]["warning"] for c in candidates if c["network"] and c["network"]["warning"])),
                        "shortlist_size": len(shortlist), "null_profiles": 0 if null is None else len(null.cache)},
            "provenance": {
                "method": "conditional_degree_matched_drug_targets_v1", "disease_targets_fixed": True,
                "settings": settings_payload, "settings_sha256": hashlib.sha256(json.dumps(settings_payload, sort_keys=True).encode()).hexdigest(),
                "rng": "PCG64; SHA-256-derived 128-bit seed per Disease and degree-bin count profile",
                "std_ddof": 0, "sampling": "distinct within each set; observed/Disease proteins eligible; size and bin-count matched",
                "degree_bins": [] if null is None else null.bin_report,
                "degree_pool_scope": "largest_connected_component", "stage1_files": self.artifacts.manifest["files"],
                "software": {"ranking": __version__, "ranking_format": 2, "numpy": np.__version__, "stage1": self.artifacts.manifest.get("software", {})},
                "inputs": {"disease": disease.source, "drugs": drugs.source}, "releases": sorted(set(drugs.releases + [disease.release] + self.artifacts.manifest["releases"])),
                "shortlist_policy": "initial 10 network + 5 supported evidence (or configured quotas); mark overlaps with both; fill from next supported evidence then valid network",
                "coverage_definition": "total=distinct supplied Target IDs plus invalid rows without IDs; mapped=full-graph IDs; retained=selected LCC IDs; excluded=total-retained. Upstream unmapped source items are separate, not a distinct-protein count.",
                "baseline_scope": "all supplied valid Disease scores, including those outside LCC/top-N; no drug-Disease indication/trial labels or docking scores",
            },
            "warnings": warnings, "interpretation": "Network proximity is a research prioritisation measure, not a treatment-success probability.",
            "created_utc": datetime.now(timezone.utc).isoformat(), "ranking_seconds": perf_counter() - started,
        }


def rank_files(artifacts_path: Path | str, drugs_path: Path | str, disease_path: Path | str, disease_id: str, settings: RankingSettings = RankingSettings()) -> dict:
    started = perf_counter()
    disease, drugs = load_disease(disease_path, disease_id), load_drugs(drugs_path)
    with load_artifacts(artifacts_path) as artifacts:
        result = RankingEngine(artifacts, settings).rank(disease, drugs)
        result["provenance"]["stage1_manifest"] = file_record(Path(artifacts_path) / "manifest.json")
    result["total_seconds"] = perf_counter() - started
    return result
