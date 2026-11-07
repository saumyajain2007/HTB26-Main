"""Deterministic network-path enrichment of saved rankings; no scoring changes."""

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
from time import perf_counter

from .artifacts import Artifacts, file_record, load_artifacts, write_json
from .data import CANDIDATE_ID
from .network import GENE_ID


TIE_POLICY = "minimum hop count, then Disease Target Ensembl ID; lexicographically smallest Ensembl-ID path to that endpoint"
REPRESENTATIVE_POLICY = "sort all verified paths by (hops, drug_target_id, disease_target_id, target_ids); include all if <=3, otherwise first, lower median and last"
INTERPRETATION = "Network associations in an undirected gene-level graph, not proven biological mechanisms, causal routes or treatment evidence."


class PathReconstructor:
    """Follow decreasing saved distances, with separate graph and matrix indexes."""

    def __init__(self, artifacts: Artifacts, disease_targets: list[str]):
        self.artifacts = artifacts
        self.graph_index = {g: i for i, g in enumerate(artifacts.graph_gene_ids)}
        self.distance_index = {g: i for i, g in enumerate(artifacts.distance_gene_ids)}
        versions = [r for r in artifacts.manifest["releases"] if r.startswith("string-")]
        if len(versions) != 1:
            raise ValueError("Exactly one STRING graph release is required")
        self.graph_version = versions[0]
        self.sentinel = artifacts.manifest["distances"]["unreachable_sentinel"]
        self.disease_targets, self.excluded_disease_targets = [], []
        if not isinstance(disease_targets, list) or any(not isinstance(g, str) for g in disease_targets):
            raise ValueError("Disease Targets must be a list of identifiers")
        for gene in sorted(set(disease_targets)):
            reason = self.exclusion_reason(gene)
            if reason:
                self.excluded_disease_targets.append({"target_id": gene, "reason": reason})
            else:
                self.disease_targets.append(gene)
        self.cache: dict[str, dict] = {}

    def exclusion_reason(self, gene):
        if not isinstance(gene, str) or not GENE_ID.fullmatch(gene):
            return "invalid_target_id"
        if gene not in self.graph_index:
            return "not_in_graph"
        if gene not in self.distance_index:
            return "outside_largest_component"
        return None

    def validate_path(self, record):
        """Check endpoints, every saved edge, nearest distance and integer hops."""
        target_ids = record["target_ids"]
        start, end, hops = record["drug_target_id"], record["disease_target_id"], record["hops"]
        if (not target_ids or target_ids[0] != start or target_ids[-1] != end
                or end not in self.disease_targets or len(set(target_ids)) != len(target_ids)
                or isinstance(hops, bool) or not isinstance(hops, int) or hops < 0
                or len(target_ids) != hops + 1 or record["graph_version"] != self.graph_version
                or any(g not in self.distance_index for g in target_ids)):
            raise ValueError("Invalid path identifiers, endpoints or hop count")
        for left, right in zip(target_ids, target_ids[1:]):
            if self.artifacts.graph[self.graph_index[left], self.graph_index[right]] != 1:
                raise ValueError(f"Path contains an absent graph edge: {left}, {right}")
        row = self.artifacts.distances[self.distance_index[start]]
        expected = int(row[self.distance_index[end]])
        nearest = min(int(row[self.distance_index[g]]) for g in self.disease_targets)
        if expected == self.sentinel or hops != expected or hops != nearest:
            raise ValueError("Path hop count does not match nearest saved distance")

    def nearest_path(self, drug_target: str) -> dict:
        if isinstance(drug_target, str) and drug_target in self.cache:
            return deepcopy(self.cache[drug_target])
        record = {"drug_target_id": drug_target, "disease_target_id": None, "target_ids": [],
                  "hops": None, "graph_version": self.graph_version, "status": "unavailable", "reason": None}
        reason = self.exclusion_reason(drug_target)
        if reason:
            record["reason"] = reason
            return record
        if not self.disease_targets:
            record["reason"] = "no_retained_disease_targets"
            return record
        row = self.artifacts.distances[self.distance_index[drug_target]]
        finite = [(int(row[self.distance_index[g]]), g) for g in self.disease_targets
                  if int(row[self.distance_index[g]]) != self.sentinel]
        if not finite:
            record["reason"] = "unreachable_disease_targets"
            return record
        hops, destination = min(finite)
        current, remaining, target_ids = drug_target, hops, [drug_target]
        destination_index = self.distance_index[destination]
        while remaining > 0:
            index = self.graph_index[current]
            neighbors = self.artifacts.graph.indices[self.artifacts.graph.indptr[index]:self.artifacts.graph.indptr[index + 1]]
            choices = [self.artifacts.graph_gene_ids[int(n)] for n in neighbors
                       if self.artifacts.graph_gene_ids[int(n)] in self.distance_index
                       and int(self.artifacts.distances[self.distance_index[self.artifacts.graph_gene_ids[int(n)]], destination_index]) == remaining - 1]
            if not choices:
                raise ValueError(f"Graph/distance inconsistency while reconstructing {drug_target}")
            current = min(choices)
            target_ids.append(current)
            remaining -= 1
        record.update(disease_target_id=destination, target_ids=target_ids, hops=hops, status="available")
        self.validate_path(record)
        self.cache[drug_target] = deepcopy(record)
        return record


def representatives(paths: list[dict]) -> list[dict]:
    ordered = sorted((p for p in paths if p["status"] == "available"),
                     key=lambda p: (p["hops"], p["drug_target_id"], p["disease_target_id"], p["target_ids"]))
    return deepcopy(ordered if len(ordered) <= 3 else [ordered[0], ordered[(len(ordered) - 1) // 2], ordered[-1]])


def retained_ids(coverage: dict) -> list[str]:
    identifiers = coverage.get("retained_target_ids")
    if (not isinstance(identifiers, list) or any(not isinstance(g, str) or not GENE_ID.fullmatch(g) for g in identifiers)
            or len(set(identifiers)) != len(identifiers) or coverage.get("retained") != len(identifiers)):
        raise ValueError("Coverage must contain unique retained Target IDs and a matching count")
    return sorted(identifiers)


def explain_ranking(payload: dict, artifacts: Artifacts) -> tuple[dict, dict]:
    """Return an additive ranking copy and all paths for every shortlisted Target."""
    if "network_paths_provenance" in payload or any("network_paths" in c for c in payload.get("candidates", [])):
        raise ValueError("Ranking already contains path enrichment; use the original input")
    if payload.get("provenance", {}).get("stage1_files") != artifacts.manifest["files"]:
        raise ValueError("Ranking and path graph artifact hashes do not match")
    disease_targets = retained_ids(payload["disease"]["coverage"])
    engine = PathReconstructor(artifacts, disease_targets)
    if engine.excluded_disease_targets:
        raise ValueError("Saved retained Disease Targets are absent from the scoring component")
    result = deepcopy(payload)
    candidates = {}
    for candidate in result["candidates"]:
        identifier = candidate["candidate_id"]
        if not isinstance(identifier, str) or not CANDIDATE_ID.fullmatch(identifier) or identifier in candidates:
            raise ValueError("Invalid or duplicate Candidate ID")
        candidates[identifier] = candidate
    shortlist = result.get("shortlist")
    if not isinstance(shortlist, list) or len(set(shortlist)) != len(shortlist) or not set(shortlist).issubset(candidates):
        raise ValueError("Shortlist requires unique Candidate IDs present in the ranking")
    graph = {"graph_version": engine.graph_version, "releases": artifacts.manifest["releases"],
             "filters": artifacts.manifest["filters"], "scope": "largest_connected_component",
             "provenance": "derived_from_pinned_filtered_STRING_graph", "edge_level_citations": "not_retained",
             "undirected": True, "unweighted": True, "artifact_files": artifacts.manifest["files"]}
    metadata = {"schema_version": 1, "graph": graph, "tie_policy": TIE_POLICY,
                "representative_policy": REPRESENTATIVE_POLICY, "interpretation": INTERPRETATION,
                "complete_paths_file": "all_paths.json"}
    complete = {"schema_version": 1, "disease_id": result["disease"]["id"], "disease_target_ids": disease_targets,
                "provenance": deepcopy(metadata), "candidates": []}
    for identifier in shortlist:
        candidate = candidates[identifier]
        drug_targets = retained_ids(candidate["coverage"])
        if any(engine.exclusion_reason(g) for g in drug_targets):
            raise ValueError(f"{identifier}: retained drug Target is outside the scoring component")
        paths = [engine.nearest_path(g) for g in drug_targets]
        available = [p for p in paths if p["status"] == "available"]
        network = candidate.get("network")
        contributing_count = 0
        if network is not None:
            observed = network.get("mean_distance")
            if (network.get("graph_version") != engine.graph_version or not drug_targets or len(available) != len(drug_targets)
                    or isinstance(observed, bool) or not isinstance(observed, (float, int)) or not math.isfinite(observed)
                    or not math.isclose(sum(p["hops"] for p in available) / len(available), observed, rel_tol=1e-12, abs_tol=1e-12)):
                raise ValueError(f"{identifier}: complete paths do not reproduce the saved mean distance/graph")
            contributing_count = len(drug_targets)
        elif candidate.get("status") != "not_scorable" or not candidate.get("unscorable_reason") or available:
            raise ValueError(f"{identifier}: missing network result is inconsistent with retained Targets")
        summary = {"schema_version": 1, "status": "available" if network is not None else "unavailable",
                   "reason": None if network is not None else candidate["unscorable_reason"],
                   "graph_version": engine.graph_version, "retained_drug_target_count": len(drug_targets),
                   "score_contributing_target_count": contributing_count, "disease_target_count": len(disease_targets),
                   "complete_path_count": len(available), "representative_policy": REPRESENTATIVE_POLICY,
                   "interpretation": INTERPRETATION, "provenance": "derived_from_pinned_filtered_STRING_graph",
                   "edge_level_citations": "not_retained"}
        complete["candidates"].append({"candidate_id": identifier, **deepcopy(summary), "paths": paths,
                                       "excluded_drug_targets": deepcopy(candidate["coverage"].get("excluded_targets", []))})
        candidate["network_paths"] = {**summary, "paths": representatives(paths),
                                      "complete_paths_ref": {"file": "all_paths.json", "candidate_id": identifier}}
    result["network_paths_provenance"] = metadata
    return result, complete


def explain_files(artifacts_path: Path | str, ranking_path: Path | str, output: Path | str) -> dict:
    """Publish a new bundle atomically; never overwrite ranking or graph inputs."""
    started = perf_counter()
    artifacts_path, ranking_path, output = Path(artifacts_path), Path(ranking_path), Path(output)
    if output.exists():
        raise FileExistsError(f"Path explanation output already exists: {output}")
    input_record = file_record(ranking_path)
    payload = json.loads(ranking_path.read_text(encoding="utf-8"))
    manifest_record = file_record(artifacts_path / "manifest.json")
    if payload.get("provenance", {}).get("stage1_manifest") != manifest_record:
        raise ValueError("Ranking Stage 1 manifest does not match the requested graph")
    with load_artifacts(artifacts_path) as artifacts:
        loaded = perf_counter()
        enriched, complete = explain_ranking(payload, artifacts)
        reconstructed = perf_counter()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".network-paths-", dir=output.parent) as temporary:
        staged = Path(temporary) / "bundle"
        staged.mkdir()
        write_json(staged / "all_paths.json", complete)
        complete_record = file_record(staged / "all_paths.json")
        selected = {c["candidate_id"]: c for c in enriched["candidates"] if "network_paths" in c}
        for candidate in selected.values():
            candidate["network_paths"]["complete_paths_ref"].update(complete_record)
        enriched["network_paths_provenance"].update(source_ranking={"name": ranking_path.name, **input_record},
                                                   stage1_manifest=manifest_record, complete_paths=complete_record)
        write_json(staged / "ranking.json", enriched)
        write_json(staged / "shortlist.json", {"schema_version": 1, "kind": "shortlist_network_path_explanations",
                   "disease": deepcopy(enriched["disease"]), "shortlist": enriched["shortlist"],
                   "candidates": [selected[cid] for cid in enriched["shortlist"]],
                   "network_paths_provenance": enriched["network_paths_provenance"]})
        if file_record(ranking_path) != input_record or file_record(artifacts_path / "manifest.json") != manifest_record:
            raise ValueError("Path enrichment source changed during calculation")
        manifest = {"schema_version": 1, "source_ranking": {"name": ranking_path.name, **input_record},
                    "stage1_manifest": manifest_record, "method": "saved_distance_decreasing_neighbors_v1",
                    "software_source": file_record(Path(__file__)), "graph": complete["provenance"]["graph"],
                    "shortlisted_candidates": len(selected),
                    "complete_verified_paths": sum(c["complete_path_count"] for c in complete["candidates"]),
                    "representative_paths": sum(len(c["network_paths"]["paths"]) for c in selected.values()),
                    "timing_seconds": {"input_and_artifact_verification": loaded - started,
                                       "path_reconstruction_and_validation": reconstructed - loaded,
                                       "total": perf_counter() - started},
                    "files": {name: file_record(staged / name) for name in ("all_paths.json", "ranking.json", "shortlist.json")}}
        write_json(staged / "manifest.json", manifest)
        staged.rename(output)
    return {"output": str(output), **{k: manifest[k] for k in ("shortlisted_candidates", "complete_verified_paths", "representative_paths", "timing_seconds", "files")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True, help="Saved Stage 2 or adapted Stage 3 ranking JSON")
    parser.add_argument("--output", type=Path, required=True, help="New directory; existing files are never overwritten")
    args = parser.parse_args()
    try:
        print(json.dumps(explain_files(args.artifacts, args.input, args.output), indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
