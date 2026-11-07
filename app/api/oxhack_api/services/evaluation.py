"""Frozen evaluation results (plan.md section 6).

The API serves `fixtures/evaluation.json`. `scripts/import_evaluation.py` writes it from
a frozen stream B Stage 3 folder (`python -m ranking evaluate --output ...`) with
`from_stage3`, so the numbers on screen are the frozen ones, unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from ..schemas import Evaluation

RELEASE = re.compile(r"^[a-z]+-[0-9][0-9.]*$")
SCOPES = ("full_eligible", "common_scorable")


class EvaluationSource(Protocol):
    def evaluation(self) -> Evaluation: ...


class FixtureEvaluation:
    """Implements `EvaluationSource` from `fixtures/evaluation.json`."""

    def __init__(self, fixtures_dir: Path) -> None:
        self._path = fixtures_dir / "evaluation.json"

    def evaluation(self) -> Evaluation:
        return Evaluation.model_validate_json(self._path.read_bytes())


def canonical_hash(value: object) -> str:
    """Stream B's manifest hash (`ranking.evaluation.canonical_hash`)."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def from_stage3(directory: Path, rankings: list[Path]) -> Evaluation:
    """The Evaluation in a frozen Stage 3 folder.

    `rankings` are the Stage 2 ranking files the evaluation read; they give the Disease
    names, and each must match the size and SHA-256 the manifest recorded. Raises
    ValueError when the folder's manifest doesn't match its recorded hash.
    """
    manifest_path = directory / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    results: dict[str, Any] = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    manifest_hash = canonical_hash(manifest)
    if manifest_hash != results["manifest_content_sha256"]:
        raise ValueError(f"{manifest_path}: content does not match the hash in results.json")

    names: dict[str, str | None] = {}
    sources = {case["disease_id"]: case["ranking_source"] for case in manifest["cases"]}
    for path in rankings:
        payload = json.loads(path.read_text(encoding="utf-8"))
        disease_id = payload["disease"]["id"]
        recorded = sources.get(disease_id)
        if recorded is None:
            raise ValueError(f"{path}: {disease_id} is not in this evaluation")
        if (recorded["sha256"], recorded["bytes"]) != (_file_sha256(path), path.stat().st_size):
            raise ValueError(f"{path}: not the ranking file this evaluation read")
        names[disease_id] = payload["disease"].get("name")

    releases = {
        release
        for case in manifest["cases"]
        for release in case["ranking_provenance"]["ranking"].get("releases", [])
    } | set(manifest["references"].get("releases", []))
    data_releases = sorted(r for r in releases if RELEASE.fullmatch(r))
    frozen = datetime.fromtimestamp((directory / "results.json").stat().st_mtime, UTC)

    rows: list[dict[str, Any]] = []
    for aggregate in results["aggregate"]:
        scope = aggregate["scope"]
        cases = [
            row
            for row in results["metrics"]
            if row["scope"] == scope
            and row["method"] == aggregate["method"]
            and row["disease_id"] in aggregate["evaluated_case_ids"]
        ]
        metrics = {
            name: aggregate[name]
            for name in ("recall_at_5", "recall_at_10", "recall_at_20", "mrr")
            if aggregate[name] is not None
        }
        intervals = {
            name: {"low": aggregate[f"{name}_ci95"][0], "high": aggregate[f"{name}_ci95"][1]}
            for name in metrics
            if aggregate.get(f"{name}_ci95") is not None
        }
        rows.append(
            {
                "manifest_hash": manifest_hash,
                "experiment": "retrieval",
                "method": aggregate["method"],
                "scope": scope,
                "data_releases": data_releases,
                "metrics": metrics,
                "coverage": {
                    "diseases": aggregate["evaluated_cases"],
                    "diseases_tested": aggregate["total_cases"],
                    "candidates": sum(row["universe_size"] for row in cases),
                    "scored_candidates": sum(row["scorable_count"] for row in cases),
                    "known_pairs": sum(row["positive_in_scope"] for row in cases),
                },
                "confidence_intervals": intervals or None,
                "created_at": frozen.isoformat(),
            }
        )

    diseases: list[dict[str, Any]] = []
    for scope in SCOPES:
        for row in results["metrics"]:
            # Every method sees the same Diseases and drugs in a scope; one row per Disease.
            if row["scope"] != scope or row["method"] != "random":
                continue
            labelled = row["reference_total"] is not None
            diseases.append(
                {
                    "disease_id": row["disease_id"],
                    "name": names.get(row["disease_id"]),
                    "scope": scope,
                    "status": row["label_status"],
                    "candidates": row["universe_size"],
                    "known": row["positive_in_scope"] if labelled else None,
                }
            )
    return Evaluation.model_validate({"results": rows, "diseases": diseases, "fixture_note": None})
