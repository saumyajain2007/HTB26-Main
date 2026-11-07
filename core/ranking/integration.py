"""Minimal Candidate adapter for plan.md section 9.2; no fabricated enrichment."""

from copy import deepcopy
import math
import re

from .data import CANDIDATE_ID
from .network import GENE_ID


EVIDENCE_ID = re.compile(r"E[0-9]+\Z")
REQUIRED = {"candidate_id", "name", "status", "selected_by", "network", "direct_evidence_rank", "targets", "evidence", "warnings", "safety_status", "dockable"}


def validate_api_candidates(candidates: list[dict]) -> None:
    identifiers, evidence_ids = set(), {}

    def finite(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    for candidate in candidates:
        if REQUIRED - candidate.keys():
            raise ValueError(f"Missing API Candidate fields: {sorted(REQUIRED - candidate.keys())}")
        identifier = candidate["candidate_id"]
        if not isinstance(identifier, str) or not CANDIDATE_ID.fullmatch(identifier) or identifier in identifiers:
            raise ValueError("Invalid or duplicate API Candidate ID")
        identifiers.add(identifier)
        if not isinstance(candidate["name"], str) or not candidate["name"]:
            raise ValueError("Candidate name must be a nonempty string")
        if (not isinstance(candidate["selected_by"], list) or any(not isinstance(v, str) for v in candidate["selected_by"])
                or not set(candidate["selected_by"]).issubset({"network", "evidence"})):
            raise ValueError("Invalid Candidate selection source")
        network, status = candidate["network"], candidate["status"]
        if status == "not_scorable":
            if network is not None or not candidate.get("unscorable_reason"):
                raise ValueError("Unscorable Candidate requires null network and a reason")
        elif status in ("scored", "distance_only"):
            if not isinstance(network, dict) or not finite(network.get("mean_distance")) or network["mean_distance"] < 0:
                raise ValueError("Network result requires finite nonnegative distance")
            if not isinstance(network.get("rank"), int) or isinstance(network["rank"], bool) or network["rank"] < 1 or not isinstance(network.get("graph_version"), str):
                raise ValueError("Network result requires rank and graph version")
            if status == "scored" and not finite(network.get("degree_matched_z")):
                raise ValueError("Scored Candidate requires a finite z-score")
            if status == "distance_only" and (network.get("degree_matched_z") is not None or not network.get("warning")):
                raise ValueError("Distance-only Candidate requires null z-score and warning")
        else:
            raise ValueError("Invalid API Candidate status")
        rank = candidate["direct_evidence_rank"]
        if rank is not None and (not isinstance(rank, int) or isinstance(rank, bool) or rank < 1):
            raise ValueError("Invalid direct-evidence rank")
        if not isinstance(candidate["targets"], list):
            raise ValueError("Candidate Targets must be an array")
        for target in candidate["targets"]:
            if (not isinstance(target, dict) or not isinstance(target.get("id"), str) or not GENE_ID.fullmatch(target["id"])
                    or any(not isinstance(target.get(k), str) for k in ("name", "mechanism"))):
                raise ValueError("Target requires Ensembl id, name and mechanism strings")
        if not isinstance(candidate["evidence"], list) or not isinstance(candidate["warnings"], list) or not isinstance(candidate["safety_status"], str) or not isinstance(candidate["dockable"], bool):
            raise ValueError("Invalid enrichment field types")
        for item in candidate["evidence"]:
            if not isinstance(item, dict):
                raise ValueError("Evidence item must be an object")
            evidence_id = item.get("id", "")
            if not isinstance(evidence_id, str) or not EVIDENCE_ID.fullmatch(evidence_id) or any(not isinstance(item.get(k), str) or not item[k] for k in ("source", "release", "url", "kind")):
                raise ValueError("Invalid evidence item")
            if evidence_id in evidence_ids and evidence_ids[evidence_id] != item:
                raise ValueError("Evidence ID identifies conflicting items within one Experiment")
            evidence_ids[evidence_id] = item


def adapt_ranking(payload: dict, enrichment: dict[str, dict] | None = None) -> dict:
    result = deepcopy(payload)
    enrichment = enrichment or {}
    if not isinstance(enrichment, dict) or any(not isinstance(item, dict) for item in enrichment.values()):
        raise ValueError("Enrichment must be a Candidate-ID keyed object of objects")
    candidates = result.get("candidates", [])
    if set(enrichment) - {c["candidate_id"] for c in candidates}:
        raise ValueError("Enrichment contains Candidate IDs absent from the ranking")
    missing = 0
    for candidate in candidates:
        groups = {"evidence": "evidence", "warnings": "safety", "safety_status": "safety", "dockable": "structures"}
        existing = {key: candidate[key] for key, group in groups.items()
                    if key in candidate and candidate.get("enrichment_status", {}).get(group) != "not_supplied"}
        supplied = {**existing, **enrichment.get(candidate["candidate_id"], {})}
        # Empty arrays mean not supplied, explicitly flagged. They are not a
        # claim that the Candidate has no evidence or is safe.
        candidate.update(evidence=deepcopy(supplied.get("evidence", [])), warnings=deepcopy(supplied.get("warnings", [])),
                         safety_status=supplied.get("safety_status", "unknown"), dockable=supplied.get("dockable", False),
                         enrichment_status={"evidence": "provided" if "evidence" in supplied else "not_supplied",
                                            "safety": "provided" if "warnings" in supplied and "safety_status" in supplied else "not_supplied",
                                            "structures": "provided" if "dockable" in supplied else "not_supplied"})
        missing += int(any(value == "not_supplied" for value in candidate["enrichment_status"].values()))
    validate_api_candidates(candidates)
    result["integration"] = {"contract": "plan.md section 9.2 Candidate fixture", "candidate_validation": "passed",
                             "candidates_missing_enrichment": missing,
                             "scope": "Candidate field compatibility only; no deployed API or full Experiment schema exists in this checkout.",
                             "missing_data": "Empty evidence/warnings are not supplied; safety remains unknown. dockable=false means no verified structure was supplied. Jury enrichment/blinding remains separate."}
    return result
