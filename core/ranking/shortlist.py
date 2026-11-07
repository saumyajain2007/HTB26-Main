"""Opt-in shortlist projections; never mutate a ranking or its scoring policy."""

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from .data import CANDIDATE_ID
from .evaluation import canonical_hash
from .scoring import RankingSettings, make_shortlist


@dataclass(frozen=True)
class ShortlistSettings:
    method: str = "zscore"
    network_slots: int = 10
    evidence_slots: int = 5

    def __post_init__(self):
        if self.method not in {"zscore", "physical_rwr"}:
            raise ValueError("Shortlist method must be zscore or physical_rwr")
        RankingSettings(network_slots=self.network_slots, evidence_slots=self.evidence_slots)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def select_shortlist(payload: dict, settings: ShortlistSettings = ShortlistSettings()) -> dict:
    """Reuse the legacy quota/fill algorithm with a separate network ranking view.

    Eligibility is the upstream approved-Candidate universe, without another
    filter. A lane requires a usable score; missing scores never become zero.
    Source lanes describe selection events, not merely feature availability.
    """
    candidates = payload["candidates"]
    ids = [c["candidate_id"] for c in candidates]
    if len(ids) != len(set(ids)) or any(not isinstance(i, str) or not CANDIDATE_ID.fullmatch(i) for i in ids):
        raise ValueError("Expected unique stable Candidate IDs in the eligible universe")
    by_id = {c["candidate_id"]: c for c in candidates}
    network, unavailable = [], Counter()
    for c in candidates:
        if settings.method == "zscore":
            n = c.get("network") or {}
            valid = c.get("status") == "scored" and _finite(n.get("degree_matched_z")) and _finite(n.get("mean_distance"))
            key = (n.get("degree_matched_z"), n.get("mean_distance"), c["candidate_id"]) if valid else None
            reason = c.get("unscorable_reason") or "no_valid_zscore"
        else:
            n = c.get("rwr", {}).get("physical") or {}
            if n and "physical" not in n.get("graph_kind", ""):
                raise ValueError("physical_rwr requires the physical graph slot")
            valid = n.get("status") == "scored" and n.get("converged") is True and _finite(n.get("score")) and n["score"] >= 0
            key = (-n["score"], c["candidate_id"]) if valid else None
            reason = n.get("reason") or ("missing_physical_rwr" if not n else "no_valid_converged_physical_rwr_score")
        if valid:
            network.append((key, c["candidate_id"]))
        else:
            unavailable[reason] += 1
    network_ids = [i for _, i in sorted(network)]
    # Include zero-evidence rows when assigning ranks, exactly as Stage 2 does.
    evidence = sorted((c for c in candidates if _finite(c.get("direct_evidence", {}).get("score"))),
                      key=lambda c: (-c["direct_evidence"]["score"], -c["direct_evidence"]["breadth"], c["candidate_id"]))
    evidence_ranks = {c["candidate_id"]: rank for rank, c in enumerate(evidence, 1)}
    network_ranks = {i: rank for rank, i in enumerate(network_ids, 1)}
    views = [{"candidate_id": i, "status": "scored" if i in network_ranks else "not_scorable",
              "network": {"rank": network_ranks.get(i)},
              "direct_evidence": c["direct_evidence"] if i in evidence_ranks else {"score": None},
              "direct_evidence_rank": evidence_ranks.get(i), "selected_by": [], "selection_reasons": [],
              "shortlist_rank": None} for i, c in by_id.items()]
    # No edits to make_shortlist or to original Candidate score/rank fields.
    selected = make_shortlist(views, RankingSettings(network_slots=settings.network_slots, evidence_slots=settings.evidence_slots))
    view_by_id = {c["candidate_id"]: c for c in views}
    entries = []
    for i in selected:
        c = view_by_id[i]
        entries.append({"candidate_id": i, "rank": c["shortlist_rank"],
                        "source_lane": "both" if len(c["selected_by"]) == 2 else c["selected_by"][0],
                        "selected_by": c["selected_by"], "reasons": c["selection_reasons"],
                        "network_rank": network_ranks.get(i), "direct_evidence_rank": evidence_ranks.get(i)})
    supported = {c["candidate_id"] for c in evidence if c["direct_evidence"]["score"] > 0}
    available = set(network_ids) | supported
    requested = settings.network_slots + settings.evidence_slots
    physical = payload.get("rwr_provenance", {}).get("physical", {})
    versions = sorted({c["network"]["graph_version"] for c in candidates if c.get("network") and c["network"].get("graph_version")})
    graph = (deepcopy(physical.get("graph")) if settings.method == "physical_rwr" else
             {"graph_version": versions[0] if len(versions) == 1 else None, "graph_versions": versions, "network_kind": "human_physical_gene_undirected_unweighted",
              "manifest": payload.get("provenance", {}).get("stage1_manifest")})
    return {"format_version": 1, "contract": "oxhack.shortlist.v1", "disease_id": payload["disease"]["id"],
            "selection_method": settings.method, "configuration": asdict(settings),
            "seed": payload.get("provenance", {}).get("settings", {}).get("seed"),
            "selection_randomness": "none", "graph": graph,
            "scoring_configuration": {"zscore": deepcopy(payload.get("provenance", {}).get("settings")),
                                      "physical_rwr": deepcopy(physical.get("settings"))},
            "eligible_universe": {"count": len(ids), "ids_sha256": canonical_hash(sorted(ids)),
                                  "source": deepcopy(payload.get("provenance", {}).get("inputs", {}).get("drugs"))},
            "shortlist": selected, "entries": entries,
            "coverage": {"eligible": len(ids), "network_scorable": len(network_ids), "supported_evidence": len(supported),
                         "selectable_union": len(available), "network_unavailable_by_reason": dict(sorted(unavailable.items())),
                         "disease": deepcopy(payload.get("disease", {}).get("coverage")),
                         "physical_rwr_disease": deepcopy(physical.get("disease", {}).get("coverage"))},
            "requested_size": requested, "selected_size": len(selected),
            "shortfall": requested - len(selected),
            "shortfall_reason": "insufficient_unique_candidates_with_valid_network_or_positive_evidence" if len(selected) < requested else None,
            "lane_warnings": [name for condition, name in (
                (len(network_ids) < settings.network_slots, "network_pool_below_quota"),
                (len(supported) < settings.evidence_slots, "supported_evidence_pool_below_quota")) if condition],
            "policy": "Legacy policy: initial network quota, initial positive-evidence quota, mark initial overlaps both; fill unique vacancies from next supported evidence then valid network. Source lane records selection events.",
            "tie_breaking": {"zscore": "ascending z, raw distance, Candidate ID", "physical_rwr": "descending score, Candidate ID",
                             "evidence": "descending score, breadth, Candidate ID"},
            "network_paths_interpretation": "shortest-path proximity explanations; not RWR diffusion explanations",
            "interpretation": "Network association, not treatment-success probability."}


def project_shortlist(payload: dict, settings: ShortlistSettings = ShortlistSettings()) -> dict:
    """Explicit application opt-in: return a new ranking with this selection.

    All scores, ranking methods and network_paths are copied verbatim. Original
    selection metadata is retained for audit; never write over a source file.
    """
    if "shortlist_selection" in payload:
        raise ValueError("Project from the original ranking, not an existing projection")
    selection = select_shortlist(payload, settings)
    result = deepcopy(payload)
    result["legacy_shortlist_selection"] = {
        "shortlist": deepcopy(payload.get("shortlist", [])),
        "candidate_fields": {c["candidate_id"]: {k: deepcopy(c.get(k)) for k in ("selected_by", "selection_reasons", "shortlist_rank")} for c in payload["candidates"]}}
    result["shortlist_selection"] = selection
    result["shortlist"] = selection["shortlist"][:]
    result.setdefault("summary", {})["shortlist_size"] = selection["selected_size"]
    entries = {e["candidate_id"]: e for e in selection["entries"]}
    for c in result["candidates"]:
        e = entries.get(c["candidate_id"])
        c["selected_by"] = [] if e is None else e["selected_by"][:]
        c["selection_reasons"] = [] if e is None else e["reasons"][:]
        c["shortlist_rank"] = None if e is None else e["rank"]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranking", type=Path, required=True)
    parser.add_argument("--method", choices=("zscore", "physical_rwr"), default="zscore")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = json.loads(args.ranking.read_text(encoding="utf-8"))
    result = project_shortlist(payload, ShortlistSettings(method=args.method))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
