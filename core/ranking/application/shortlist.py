"""Application-only defaults around the unchanged, sealed ranking package."""

import argparse
import json
from pathlib import Path

from ranking.artifacts import file_record, write_json
from ranking.integration import adapt_ranking
from ranking.paths import explain_files
from ranking.shortlist import ShortlistSettings, project_shortlist


DEFAULT_METHOD = "physical_rwr"


def generate_shortlist(ranking: Path, artifacts: Path, out: Path, method: str = DEFAULT_METHOD) -> dict:
    """Select a new application panel and regenerate its proximity explanations.

    Keep this orchestration outside ranking/*.py so frozen code and its original
    seal remain verifiable. Selection, reconstruction and publication are delegated
    to the existing package; no scores are recalculated.
    """
    if out.exists():
        raise FileExistsError(f"Application output already exists: {out}")
    source = file_record(ranking)
    payload = json.loads(ranking.read_text(encoding="utf-8"))
    if method == "physical_rwr":
        physical = payload.get("rwr_provenance", {}).get("physical")
        if not physical:
            raise ValueError("physical_rwr requires an existing physical RWR ranking")
        if physical["graph"]["manifest"] != file_record(artifacts / "manifest.json"):
            raise ValueError("Physical RWR and path graph manifests differ")
    selected = adapt_ranking(project_shortlist(payload, ShortlistSettings(method=method)))
    # Old explanations cover the old panel. Clear only this new copy, then let
    # ranking.paths regenerate every selected Candidate against saved distances.
    selected.pop("network_paths_provenance", None)
    for candidate in selected["candidates"]:
        candidate.pop("network_paths", None)
    selected["application_shortlist"] = {
        "default_method": DEFAULT_METHOD, "method": method,
        "source_ranking": {"path": str(ranking.resolve()), **source},
        "network_paths_explain": "shortest_path_proximity_not_rwr_diffusion",
    }
    if file_record(ranking) != source:
        raise ValueError("Source ranking changed during application selection")
    out.mkdir(parents=True, exist_ok=False)
    selection_path = out / "selection.json"
    write_json(selection_path, selected)
    # Retain the intermediate selection for the path publisher's source hashes.
    # Final application JSONs are application/ranking.json and shortlist.json.
    return explain_files(artifacts, selection_path, out / "application")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranking", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New directory; final JSON is application/ranking.json")
    parser.add_argument("--method", choices=("physical_rwr", "zscore"), default=DEFAULT_METHOD)
    args = parser.parse_args(argv)
    print(json.dumps(generate_shortlist(**vars(args)), indent=2))


if __name__ == "__main__":
    main()
