"""Frozen evaluation bundles: references, manifests, CSV/JSON and a short report."""

import csv
from dataclasses import asdict
import json
from pathlib import Path
import platform
import tempfile

import numpy as np

from . import __version__
from .artifacts import file_record, sha256, write_json
from .evaluation import CLASSIFICATION, METRICS, EvaluationSettings, canonical_hash, case_from_stage2, evaluate_cases
from .references import extract_indication_references, parse_references


def read_ranking(path: Path) -> tuple[dict, dict]:
    with path.open(encoding="utf-8") as handle:
        result = json.load(handle)
    return result, {"name": path.name, **file_record(path)}


def write_csv(path: Path, rows: list[dict], omit: tuple[str, ...] = ()) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = [field for field in rows[0] if field not in omit]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def markdown_report(result: dict, manifest: dict, manifest_hash: str) -> str:
    def number(value):
        return "n/a" if value is None else f"{value:.6f}"

    count = len(manifest["case_ids"])
    lines = ["# Stage 3 — retrospective known-relationship recovery", "",
             f"**{count}-Disease smoke test; the ten-Disease research pilot is not complete.**" if not manifest["ten_disease_pilot_complete"] else f"**{count}-Disease retrospective pilot; no prospective validation is claimed.**",
             "", f"Evaluation manifest content SHA-256: `{manifest_hash}`.", "",
             "No labels were fed back into scoring. References are evaluated as recorded; unlabelled relationships are not negative controls.", "",
             "## Coverage", "", "| Disease | Eligible | Common scorable | Known eligible | Known common |",
             "|---|---:|---:|---:|---:|"]
    for row in result["coverage"]:
        lines.append(f"| {row['disease_id']} | {row['eligible_candidates']} | {row['common_scorable']} | {row['positive_eligible']} | {row['positive_common']} |")
    for scope in ("full_eligible", "common_scorable"):
        lines += ["", f"## {scope}: macro averages over labelled Diseases with positives in scope", "",
                  "| Method | Evaluated Diseases | Recall@5 | Recall@10 | Recall@20 | MRR |",
                  "|---|---:|---:|---:|---:|---:|"]
        for row in result["aggregate"]:
            if row["scope"] == scope:
                lines.append(f"| {row['method']} | {row['evaluated_cases']} | " + " | ".join(number(row[m]) for m in METRICS) + " |")
    lines += ["", "## Paired network z-score minus direct evidence", "",
              "| Scope | Paired Diseases | Δ Recall@5 | Δ Recall@10 | Δ Recall@20 | Δ MRR |",
              "|---|---:|---:|---:|---:|---:|"]
    for row in result["paired_comparisons"]:
        lines.append(f"| {row['scope']} | {row['paired_cases']} | " + " | ".join(number(row[f"delta_{m}"]) for m in METRICS) + " |")
    lines += ["", "## Frozen Stage 2 shortlist Recall@15", "",
              "| Disease | Scope | Selected | Known selected | Known in scope | Recall@15 |",
              "|---|---|---:|---:|---:|---:|"]
    for row in result["shortlist"]:
        lines.append(f"| {row['disease_id']} | {row['scope']} | {row['selected_count']} | {row['known_selected']} | {row['positive_in_scope']} | {number(row['recall_at_15'])} |")
    lines += ["", "## Interpretation and limitations", "",
              f"- Full-universe missing-score policy: `{manifest['settings']['missing_score_policy']}`. Under `unretrieved`, missing scores have no retrieved rank and count as misses; eligible positives remain in Recall denominators. `append_by_id` instead puts missing entries last, ordered by ID.",
              "- Every method uses the same eligible Candidate IDs within each Disease. The common subset is the intersection of all four score-available sets, not a method-specific filtered dataset. Missing labels or no positives in scope produce null metrics and explicit macro exclusions, not zeros.",
              "- Recall@K counts all known in-scope Candidates recovered in the first K, divided by all known in-scope Candidates. MRR averages each Disease's reciprocal rank of its first known Candidate; it does not average over every positive within a Disease.",
              "- Shortlist Recall@15 uses the saved selection unchanged. Common-scope evaluation filters that same shortlist without refilling it. The random baseline is one reproducible, seed-keyed hash permutation, not an average over many random rankings.",
              "- Bootstrap 95% intervals and exact evaluated case lists are in JSON/aggregate.csv. With only two examples, intervals are descriptive and cannot support a general research conclusion; fewer than two evaluable cases produces no interval.",
              "- These inputs were frozen for reproducibility after ranking development; this is not prospective preregistration, an out-of-time test, or clinical validation.",
              "- Direct clinical-precedence and cancer-biomarker channels are declared excluded, and explicit treatment-label fields in Candidate features are rejected. Literature co-mentions, curated targets, network study bias and shared source releases may still leak known relationships indirectly.",
              "- The supplied Disease features contain only 50 association scores each. Approval/indication labels define evaluation relationships; global approval-source provenance only defines the already-fixed eligible universe."]
    lines += [f"- Reference limitation: {limitation}" for limitation in manifest["references"].get("limitations", [])]
    lines += ["- Network proximity, retrieval recall and model agreement are not treatment-success probabilities.", "",
              "Full per-Disease metrics, ranks, missing IDs, coverage and paired comparisons are in results.json and CSV files beside this report.", ""]
    return "\n".join(lines)


def run_evaluation(
    ranking_paths: list[Path | str], output: Path | str, *, references_path: Path | str | None = None,
    indication_source: Path | str | None = None, settings: EvaluationSettings = EvaluationSettings(),
) -> dict:
    """Freeze inputs before metric computation; publish a new complete directory."""
    if (references_path is None) == (indication_source is None):
        raise ValueError("Choose exactly one independent reference file or Stream A indication source")
    if not ranking_paths:
        raise ValueError("At least one ranking input is required")
    cases, source_records = [], {}
    for path in ranking_paths:
        payload, record = read_ranking(Path(path))
        case = case_from_stage2(payload)
        if case.disease_id in source_records:
            raise ValueError(f"Duplicate ranking Disease: {case.disease_id}")
        cases.append(case)
        source_records[case.disease_id] = record
    cases.sort(key=lambda case: case.disease_id)
    if references_path is not None:
        with Path(references_path).open(encoding="utf-8") as handle:
            reference_payload = json.load(handle)
        reference_input = {"name": Path(references_path).name, **file_record(Path(references_path))}
    else:
        reference_payload = extract_indication_references(indication_source, [c.disease_id for c in cases])
        reference_input = {"name": Path(indication_source).name, **file_record(Path(indication_source))}
    references = parse_references(reference_payload)
    manifest = {
        "format_version": 1, "classification": CLASSIFICATION, "settings": asdict(settings),
        "case_ids": [c.disease_id for c in cases],
        "ten_disease_pilot_complete": sum(bool(references.get(c.disease_id, set()) & set(c.eligible_candidates)) for c in cases) >= 10,
        "random_baseline": "sha256_order_v1: seed, Disease ID and Candidate ID; common scope filters the same full order",
        "metrics": {"recall": "known retrieved / known eligible in scope", "mrr": "macro mean of reciprocal first-positive rank per Disease; unretrieved=0", "macro_missing_labels": "exclude with reason, never zero-fill"},
        "reference_input": reference_input,
        "references": {"definition": reference_payload["definition"], "releases": reference_payload.get("releases", []),
                       "limitations": reference_payload.get("limitations", []), "content_sha256": canonical_hash(reference_payload)},
        "cases": [{"disease_id": c.disease_id, "ranking_source": source_records[c.disease_id],
                   "universe_size": len(c.eligible_candidates), "eligible_ids_sha256": canonical_hash(sorted(c.eligible_candidates)),
                   "rankings_sha256": canonical_hash({method: c.rankings[method] for method in sorted(c.rankings)}),
                   "shortlist_sha256": canonical_hash(c.shortlist), "ranking_provenance": c.provenance} for c in cases],
        "protocol": "Inputs, label definition, case list and settings frozen before this metric computation; not prospectively preregistered before development.",
        "software": {"ranking": __version__, "python": platform.python_version(), "numpy": np.__version__},
    }
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"Evaluation output already exists; choose a new directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".evaluation-", dir=output.parent) as temporary:
        staged = Path(temporary) / "bundle"
        staged.mkdir()
        write_json(staged / "references.json", reference_payload)
        write_json(staged / "manifest.json", manifest)
        manifest_hash = canonical_hash(manifest)
        result = evaluate_cases(cases, references, settings)
        result.update(manifest_content_sha256=manifest_hash, manifest_file_sha256=sha256(staged / "manifest.json"))
        write_json(staged / "results.json", result)
        write_csv(staged / "metrics.csv", result["metrics"], ("ranked_candidate_ids", "missing_candidate_ids"))
        write_csv(staged / "coverage.csv", result["coverage"])
        write_csv(staged / "aggregate.csv", result["aggregate"])
        write_csv(staged / "comparisons.csv", result["case_comparisons"])
        write_csv(staged / "shortlist.csv", result["shortlist"])
        (staged / "report.md").write_text(markdown_report(result, manifest, manifest_hash), encoding="utf-8")
        if output.exists():
            raise FileExistsError(f"Evaluation output appeared during computation: {output}")
        staged.rename(output)
    return {"output": str(output), "manifest_content_sha256": manifest_hash, "case_ids": manifest["case_ids"],
            "ten_disease_pilot_complete": manifest["ten_disease_pilot_complete"], "aggregate": result["aggregate"], "coverage": result["coverage"]}
