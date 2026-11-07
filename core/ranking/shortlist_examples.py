"""Integration examples only: enrich existing rankings and emit both policies."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

from .artifacts import file_record, write_json
from .data import load_disease, load_drugs
from .functional_graph import load_rwr_graph
from .integration import validate_api_candidates
from .rwr import RWREngine, enrich_ranking
from .shortlist import ShortlistSettings, project_shortlist, select_shortlist


def generate_example(*, ranking: Path, disease_targets: Path, drugs: Path, physical_artifacts: Path,
                     functional_artifacts: Path, out: Path, complete_paths: Path | None = None) -> dict:
    started = perf_counter()
    payload = json.loads(ranking.read_text(encoding="utf-8"))
    disease = load_disease(disease_targets, payload["disease"]["id"])
    pool = load_drugs(drugs)
    for key, path in (("disease", disease_targets), ("drugs", drugs)):
        expected = payload["provenance"]["inputs"][key]
        if any(expected[k] != v for k, v in file_record(path).items()):
            raise ValueError(f"Example {key} input differs from original ranking")
    if sorted(d.id for d in pool.drugs) != sorted(c["candidate_id"] for c in payload["candidates"]):
        raise ValueError("Example eligible Candidate universe differs from original")
    if out.exists():
        raise FileExistsError("Use a new integration-example output directory")
    path_candidates = [c for c in payload["candidates"] if "network_paths" in c]
    if path_candidates:
        if complete_paths is None or not complete_paths.is_file():
            raise ValueError("Supply --complete-paths to preserve existing network_paths file references")
        record = file_record(complete_paths)
        for c in path_candidates:
            ref = c["network_paths"]["complete_paths_ref"]
            if ref["file"] != "all_paths.json" or (ref.get("sha256") and ref["sha256"] != record["sha256"]):
                raise ValueError("Complete paths do not match the preserved Candidate reference")
    timings = {}
    for key, directory in (("physical", physical_artifacts), ("functional", functional_artifacts)):
        graph = load_rwr_graph(directory)
        current = payload.get("rwr_provenance", {}).get(key)
        if current is None:
            start = perf_counter()
            score = RWREngine(graph).rank(disease, pool)
            payload = enrich_ranking(payload, score, key)
            timings[key] = {"reused": False, "seconds": perf_counter() - start, "convergence": score["convergence"]}
        else:
            if current["graph"]["manifest"] != graph.manifest_record:
                raise ValueError("Existing RWR slot belongs to different graph artifacts")
            timings[key] = {"reused": True, "seconds": 0, "convergence": deepcopy(current["convergence"])}
    payload["shortlist_example"] = {"purpose": "integration_example_not_replication", "labels_loaded": False,
                                    "source_ranking": {"path": str(ranking), **file_record(ranking)}}
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "ranking.json", payload)
    selections = {}
    for method in ("zscore", "physical_rwr"):
        settings = ShortlistSettings(method)
        selections[method] = select_shortlist(payload, settings)
        projected = project_shortlist(payload, settings)
        validate_api_candidates(projected["candidates"])
        write_json(out / f"{method}.json", projected)
        write_json(out / f"{method}.selection.json", selections[method])
    # Preserve every existing complete-path reference and its relative filename.
    # Some original bundles use hashed references; all paths and metadata stay verbatim.
    if path_candidates:
        (out / "all_paths.json").write_bytes(complete_paths.read_bytes())
    result = {"format_version": 1, "purpose": "integration_example_not_replication", "disease_id": disease.id,
              "labels_loaded": False, "timings": timings, "total_seconds": perf_counter() - started,
              "inputs": {"ranking": file_record(ranking), "disease_targets": file_record(disease_targets), "drugs": file_record(drugs)},
              "methods": {m: {"shortlist": s["shortlist"], "selected_size": s["selected_size"], "coverage": s["coverage"],
                              "selected_candidates_with_existing_proximity_paths": sum("network_paths" in c for c in payload["candidates"] if c["candidate_id"] in s["shortlist"])} for m, s in selections.items()},
              "files": {p.name: file_record(p) for p in sorted(out.iterdir()) if p.is_file()}}
    write_json(out / "manifest.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("ranking", "disease-targets", "drugs", "physical-artifacts", "functional-artifacts", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--complete-paths", type=Path)
    result = generate_example(**vars(parser.parse_args(argv)))
    print(json.dumps({"disease_id": result["disease_id"], "purpose": result["purpose"],
                      "selected": {m: s["selected_size"] for m, s in result["methods"].items()},
                      "seconds": result["total_seconds"]}, sort_keys=True))


if __name__ == "__main__":
    main()
