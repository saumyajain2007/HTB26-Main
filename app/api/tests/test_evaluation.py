"""Reading a frozen stream B Stage 3 evaluation (`ranking evaluate --output`)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from oxhack_api.schemas import Evaluation
from oxhack_api.services.evaluation import canonical_hash, from_stage3
from oxhack_api.settings import FIXTURES_DIR

METHODS = ("direct_evidence", "shared_targets", "raw_proximity", "degree_matched_z", "random")
MYELOMA, COVID = "MONDO_0009693", "MONDO_0100096"


def _metric_row(disease: str, scope: str, method: str, known: int | None) -> dict[str, Any]:
    evaluated = known is not None and known > 0
    return {
        "disease_id": disease,
        "scope": scope,
        "method": method,
        "universe_size": 1956 if scope == "full_eligible" else 1307,
        "scorable_count": 1307,
        "label_status": "evaluated" if evaluated else "no_positive_in_scope",
        "reference_total": 1 if known is not None else None,
        "positive_in_scope": known or 0,
        **dict.fromkeys(
            ("recall_at_5", "recall_at_10", "recall_at_20", "mrr"), 0.25 if evaluated else None
        ),
    }


def _aggregate(scope: str, method: str, evaluated: list[str]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "scope": scope,
        "method": method,
        "total_cases": 2,
        "evaluated_cases": len(evaluated),
        "evaluated_case_ids": evaluated,
    }
    for name in ("recall_at_5", "recall_at_10", "recall_at_20", "mrr"):
        row[name] = 0.25 if evaluated else None
        row[f"{name}_ci95"] = [0.1, 0.4] if len(evaluated) > 1 else None
    return row


def _ranking(directory: Path, disease: str, name: str) -> tuple[Path, dict[str, Any]]:
    path = directory / f"{disease}.json"
    path.write_text(json.dumps({"disease": {"id": disease, "name": name}}))
    record = {
        "name": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    return path, record


@pytest.fixture
def stage3(tmp_path: Path) -> tuple[Path, list[Path]]:
    myeloma, myeloma_record = _ranking(tmp_path, MYELOMA, "multiple myeloma")
    covid, covid_record = _ranking(tmp_path, COVID, "COVID-19")
    releases = ["chembl-37", "opentargets-26.09", "string-12.5"]
    manifest = {
        "format_version": 1,
        "case_ids": [MYELOMA, COVID],
        "references": {"definition": "test", "releases": ["opentargets-26.09"]},
        "cases": [
            {
                "disease_id": disease,
                "ranking_source": record,
                "ranking_provenance": {"ranking": {"releases": releases}},
            }
            for disease, record in ((MYELOMA, myeloma_record), (COVID, covid_record))
        ],
    }
    known = {
        ("full_eligible", MYELOMA): 32,
        ("full_eligible", COVID): 1,
        ("common_scorable", MYELOMA): 25,
        ("common_scorable", COVID): 0,
    }
    evaluated = {"full_eligible": [MYELOMA, COVID], "common_scorable": [MYELOMA]}
    results = {
        "metrics": [
            _metric_row(disease, scope, method, known[scope, disease])
            for scope in ("full_eligible", "common_scorable")
            for disease in (MYELOMA, COVID)
            for method in METHODS
        ],
        "coverage": [{"disease_id": MYELOMA}, {"disease_id": COVID}],
        "aggregate": [
            _aggregate(scope, method, evaluated[scope])
            for scope in ("full_eligible", "common_scorable")
            for method in METHODS
        ],
        "manifest_content_sha256": canonical_hash(manifest),
    }
    folder = tmp_path / "stage3"
    folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (folder / "results.json").write_text(json.dumps(results))
    return folder, [myeloma, covid]


def test_reads_every_method_in_both_scopes(stage3: tuple[Path, list[Path]]) -> None:
    evaluation = from_stage3(*stage3)
    assert evaluation.fixture_note is None
    assert {(r.scope, r.method) for r in evaluation.results} == {
        (scope, method) for scope in ("full_eligible", "common_scorable") for method in METHODS
    }
    full = next(r for r in evaluation.results if (r.scope, r.method) == ("full_eligible", "random"))
    assert full.experiment == "retrieval"
    assert full.data_releases == ["chembl-37", "opentargets-26.09", "string-12.5"]
    assert full.metrics == {
        "recall_at_5": 0.25,
        "recall_at_10": 0.25,
        "recall_at_20": 0.25,
        "mrr": 0.25,
    }
    assert full.coverage == {
        "diseases": 2,
        "diseases_tested": 2,
        "candidates": 2 * 1956,
        "scored_candidates": 2 * 1307,
        "known_pairs": 33,
    }
    assert full.confidence_intervals is not None
    assert full.confidence_intervals["mrr"].low == 0.1


def test_a_single_disease_has_no_interval(stage3: tuple[Path, list[Path]]) -> None:
    evaluation = from_stage3(*stage3)
    common = next(r for r in evaluation.results if r.scope == "common_scorable")
    assert common.coverage["diseases"] == 1
    assert common.coverage["known_pairs"] == 25
    assert common.confidence_intervals is None


def test_lists_each_disease_once_per_scope_with_why_it_was_left_out(
    stage3: tuple[Path, list[Path]],
) -> None:
    diseases = {(d.scope, d.disease_id): d for d in from_stage3(*stage3).diseases}
    assert len(diseases) == 4
    covid = diseases["common_scorable", COVID]
    assert (covid.name, covid.status, covid.known, covid.candidates) == (
        "COVID-19",
        "no_positive_in_scope",
        0,
        1307,
    )
    assert diseases["full_eligible", MYELOMA].known == 32


def test_refuses_a_changed_manifest(stage3: tuple[Path, list[Path]]) -> None:
    folder, rankings = stage3
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["case_ids"].reverse()
    (folder / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="does not match the hash"):
        from_stage3(folder, rankings)


def test_refuses_a_ranking_file_it_did_not_read(stage3: tuple[Path, list[Path]]) -> None:
    folder, rankings = stage3
    rankings[0].write_text(json.dumps({"disease": {"id": MYELOMA, "name": "myeloma"}}))
    with pytest.raises(ValueError, match="not the ranking file"):
        from_stage3(folder, rankings)


def test_committed_evaluation_parses() -> None:
    evaluation = Evaluation.model_validate_json((FIXTURES_DIR / "evaluation.json").read_text())
    scopes = {d.scope for d in evaluation.diseases}
    assert scopes == {r.scope for r in evaluation.results} == {"full_eligible", "common_scorable"}
    assert len({r.manifest_hash for r in evaluation.results}) == 1
