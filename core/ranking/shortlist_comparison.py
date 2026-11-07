"""Sealed, label-blind preparation and paired comparison of two shortlist policies."""

import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
import platform
from time import perf_counter

import numpy as np
import scipy

from .artifacts import file_record, load_artifacts, write_json
from .data import DISEASE_ID, load_disease, load_drugs
from .evaluation import EvaluationSettings, canonical_hash, case_from_stage2, mean_and_interval
from .functional_graph import load_rwr_graph
from .references import parse_references
from .rwr import RWREngine, RWRSettings, enrich_ranking
from .scoring import RankingEngine, RankingSettings
from .shortlist import ShortlistSettings, project_shortlist, select_shortlist


METHODS = ("zscore", "physical_rwr")
PHYSICAL_FILTERS = {"combined_score_min": 700, "experiments_min": 400,
                    "direct_experiments_column": "experiments", "transferred_experiments_used_as_direct": False}


def implementation_contract() -> dict:
    """Contains no cohort/labels. Any algorithm/settings change needs a new seal."""
    root = Path(__file__).parent
    return {"format_version": 1, "contract": "oxhack.shortlist-comparison-implementation.v1",
            "code": {p.name: file_record(p) for p in sorted(root.glob("*.py"))},
            "software": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
            "settings": {"ranking": asdict(RankingSettings()), "rwr": asdict(RWRSettings()),
                         "shortlists": {m: asdict(ShortlistSettings(method=m)) for m in METHODS},
                         "evaluation": asdict(EvaluationSettings()), "expected_case_count": 14,
                         "physical_graph": {"version": "string-12.5", "network_kind": "human_physical_gene_undirected_unweighted", "filters": PHYSICAL_FILTERS}},
            "label_policy": "No reference labels are opened or accepted by seal. Score both methods before parsing labels.",
            "missing_score_policy": "Unavailable network scores cannot enter the network lane; positive evidence remains eligible. All eligible references stay in recall denominators.",
            "uncertainty": "Paired Disease bootstrap percentile 95% interval, 1000 resamples, PCG64 seed 0; descriptive, small-cohort caution.",
            "official_replication": "awaiting supplied frozen 14-Disease list, Targets, versioned references and published protocol"}


def seal_implementation(path: Path) -> dict:
    payload = implementation_contract()
    payload["implementation_sha256"] = canonical_hash(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    return payload


def verify_implementation(path: Path) -> dict:
    sealed = json.loads(path.read_text(encoding="utf-8"))
    actual = implementation_contract()
    expected = {**actual, "implementation_sha256": canonical_hash(actual)}
    if sealed != expected:
        raise ValueError("Implementation seal mismatch: code, dependencies or settings changed; do not open labels")
    return sealed


def compare_shortlists(case_selections: list[dict], references: dict[str, set[str]],
                       settings: EvaluationSettings = EvaluationSettings()) -> dict:
    """Pure paired metrics; missing/empty labels are null, never invented misses."""
    cases, pairs, seen = [], [], set()
    for case in case_selections:
        disease = case["disease_id"]
        if disease in seen:
            raise ValueError(f"Duplicate Disease: {disease}")
        seen.add(disease)
        selections = case["selections"]
        a, b = (selections[m] for m in METHODS)
        if (a["eligible_universe"] != b["eligible_universe"] or
                a["eligible_universe"]["ids_sha256"] != canonical_hash(sorted(case["eligible_candidates"]))):
            raise ValueError("Methods must use the identical pinned eligible Candidate universe")
        universe = set(case["eligible_candidates"])
        if len(universe) != len(case["eligible_candidates"]):
            raise ValueError("Duplicate eligible Candidate IDs")
        for method, selection in selections.items():
            ids = selection["shortlist"]
            if method not in METHODS or len(ids) != len(set(ids)) or not set(ids) <= universe or len(ids) > 15:
                raise ValueError("Invalid shortlist in comparison")
        known = references.get(disease)
        positive = set() if known is None else set(known) & universe
        status = ("missing_labels" if known is None else "no_positive_references" if not known else
                  "no_eligible_references" if not positive else "evaluated")
        row = {"disease_id": disease, "label_status": status, "eligible_candidates": len(universe),
               "reference_total": None if known is None else len(known), "eligible_reference_pairs": len(positive),
               "references_outside_universe": None if known is None else len(set(known) - universe), "methods": {}}
        for method in METHODS:
            selection = selections[method]
            hits = positive & set(selection["shortlist"])
            row["methods"][method] = {"retrieved": len(hits), "recall_at_15": len(hits) / len(positive) if positive else None,
                                       "any_reference_retrieved": int(bool(hits)) if positive else None,
                                       "shortlist_size": len(selection["shortlist"]), "shortfall": selection["shortfall"],
                                       "coverage": selection["coverage"],
                                       "reference_network_scorable": len(positive & set(case["network_scorable"][method]))}
        for identifier in sorted(known or []):
            pairs.append({"disease_id": disease, "candidate_id": identifier, "eligible": identifier in universe,
                          **{f"in_{m}_shortlist": identifier in selections[m]["shortlist"] for m in METHODS},
                          **{f"{m}_network_scorable": identifier in set(case["network_scorable"][m]) for m in METHODS}})
        if positive:
            counts = [row["methods"][m]["retrieved"] for m in METHODS]
            row["physical_rwr_minus_zscore"] = (counts[1] - counts[0]) / len(positive)
            row["outcome"] = "physical_rwr_win" if counts[1] > counts[0] else "zscore_win" if counts[1] < counts[0] else "tie"
        else:
            row.update(physical_rwr_minus_zscore=None, outcome="not_evaluated")
        cases.append(row)
    evaluated = [c for c in cases if c["label_status"] == "evaluated"]
    total_pairs = sum(c["eligible_reference_pairs"] for c in cases)
    summary = {"diseases_supplied": len(cases), "diseases_evaluated": len(evaluated), "eligible_reference_pairs": total_pairs,
               "label_status_counts": {s: sum(c["label_status"] == s for c in cases) for s in sorted({c["label_status"] for c in cases})},
               "methods": {}}
    for method in METHODS:
        method_rows = [c["methods"][method] for c in evaluated]
        summary["methods"][method] = {"retrieved_pairs": sum(c["retrieved"] for c in method_rows),
                                      "diseases_with_any_hit": sum(c["any_reference_retrieved"] for c in method_rows)}
        for metric in ("recall_at_15", "any_reference_retrieved"):
            mean, interval = mean_and_interval([c[metric] for c in method_rows], settings)
            summary["methods"][method]["macro_" + metric] = {"mean": mean, "bootstrap_95_ci": interval}
        summary["methods"][method]["micro_recall_at_15"] = sum(c["retrieved"] for c in method_rows) / total_pairs if total_pairs else None
    paired = {"difference_direction": "physical_rwr minus zscore", "paired_diseases": len(evaluated),
              "physical_rwr_wins": sum(c["outcome"] == "physical_rwr_win" for c in evaluated),
              "zscore_wins": sum(c["outcome"] == "zscore_win" for c in evaluated),
              "ties": sum(c["outcome"] == "tie" for c in evaluated)}
    for metric in ("recall_at_15", "any_reference_retrieved"):
        values = [c["methods"]["physical_rwr"][metric] - c["methods"]["zscore"][metric] for c in evaluated]
        mean, interval = mean_and_interval(values, settings)
        paired[metric] = {"mean_difference": mean, "bootstrap_95_ci": interval, "disease_differences": values,
                          "physical_rwr_wins": sum(v > 0 for v in values), "zscore_wins": sum(v < 0 for v in values),
                          "ties": sum(v == 0 for v in values)}
    return {"format_version": 1, "classification": "retrospective_known_relationship_recovery", "settings": asdict(settings),
            "summary": summary, "paired": paired, "cases": cases, "reference_membership": pairs,
            "limitations": ["Unlabelled drugs are not known negatives; source labels may be incomplete or indirect.",
                            "Direct evidence uses evidence_only Target associations, excluding clinical_precedence and cancer_biomarkers; residual same-release indirect leakage remains possible.",
                            "Full eligible universe only: unscorable references remain denominator misses unless evidence selection retrieves them.",
                            "Disease-bootstrap intervals are descriptive and can be unstable in small cohorts. No superiority claim or tuning is justified.",
                            "Network association is not treatment-success probability. Shortest paths explain proximity, not RWR."]}


def _write_csv(path, rows):
    # Headers remain explicit even when no eligible references exist.
    keys = list(rows[0]) if rows else ["disease_id", "candidate_id", "eligible"]
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def write_results(root: Path, result: dict):
    write_json(root / "results.json", result)
    _write_csv(root / "reference_membership.csv", result["reference_membership"])
    rows = []
    for c in result["cases"]:
        for m in METHODS:
            r = c["methods"][m]
            rows.append({"disease_id": c["disease_id"], "method": m, "label_status": c["label_status"],
                         "eligible_candidates": c["eligible_candidates"], "eligible_reference_pairs": c["eligible_reference_pairs"],
                         **{k: r[k] for k in ("retrieved", "recall_at_15", "any_reference_retrieved", "shortlist_size", "shortfall", "reference_network_scorable")},
                         "network_scorable_candidates": r["coverage"]["network_scorable"],
                         "paired_difference": c["physical_rwr_minus_zscore"], "outcome": c["outcome"]})
    _write_csv(root / "per_disease.csv", rows)
    summary = result["summary"]
    lines = ["# Sealed shortlist comparison", "", "Retrospective known-relationship recovery; not treatment-success probability.", "",
             f"{summary['diseases_evaluated']}/{summary['diseases_supplied']} Diseases evaluated; {summary['eligible_reference_pairs']} eligible reference pairs.", "",
             "| Method | Macro Recall@15 | Any-hit fraction | Retrieved pairs |", "|---|---:|---:|---:|"]
    for method in METHODS:
        s = summary["methods"][method]
        lines.append(f"| {method} | {s['macro_recall_at_15']['mean']} | {s['macro_any_reference_retrieved']['mean']} | {s['retrieved_pairs']} |")
    lines += ["", "Paired differences (physical RWR minus z-score), including 95% Disease-bootstrap intervals:", "", "```json",
              json.dumps(result["paired"], indent=2), "```", "", "See per_disease.csv for all counts, coverage, missing-label cases and shortages.", ""]
    lines += ["- " + x for x in result["limitations"]]
    (root / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_comparison(*, seal: Path, cases: Path, targets_dir: Path, references: Path, drugs: Path,
                   artifacts: Path, protocol: Path, out: Path) -> dict:
    """Official inputs only. Never called for substitute or integration cohorts."""
    started = perf_counter()
    implementation = verify_implementation(seal)  # Before any reference-file access.
    if not protocol.is_file() or not protocol.stat().st_size:
        raise ValueError("The supplied published replication protocol is required")
    case_list = json.loads(cases.read_text(encoding="utf-8"))
    if case_list.get("format_version") != 1 or not case_list.get("cohort_id") or not isinstance(case_list.get("cases"), list):
        raise ValueError("Frozen cases require format_version=1, cohort_id and cases")
    rows = case_list["cases"]
    ids = [r.get("disease_id") for r in rows]
    if len(ids) != implementation["settings"]["expected_case_count"] or len(ids) != len(set(ids)):
        raise ValueError("Official comparison requires exactly 14 unique supplied Diseases")
    target_paths = {}
    for row in rows:
        identifier = row["disease_id"]
        if not isinstance(identifier, str) or not DISEASE_ID.fullmatch(identifier):
            raise ValueError("Invalid Disease ID in frozen case list")
        relative = Path(row["targets_file"])
        target_path = (targets_dir / relative).resolve()
        if relative.is_absolute() or not target_path.is_relative_to(targets_dir.resolve()):
            raise ValueError("Target files must stay within targets-dir")
        target_paths[identifier] = target_path
    pool = load_drugs(drugs)
    universe = sorted(d.id for d in pool.drugs)
    graph_files = {p.name: file_record(p) for p in sorted(artifacts.iterdir()) if p.is_file()}
    inputs = {"format_version": 1, "implementation": file_record(seal), "implementation_sha256": implementation["implementation_sha256"],
              "cohort_id": case_list["cohort_id"], "disease_order": ids, "case_list": file_record(cases),
              "published_protocol": {"path": str(protocol.resolve()), **file_record(protocol)},
              "references": {"path": str(references.resolve()), **file_record(references)},
              "drugs": {"path": str(drugs.resolve()), **file_record(drugs)}, "graph_files": graph_files,
              "targets": {i: {"path": str(p), **file_record(p)} for i, p in target_paths.items()},
              "eligible_universe": {"ids": universe, "ids_sha256": canonical_hash(universe), "count": len(universe)},
              "settings": implementation["settings"], "state": "inputs_frozen_before_scoring_and_reference_parsing"}
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "inputs.freeze.json", inputs)
    prepared, timings = [], {}
    try:
        graph = load_rwr_graph(artifacts)
        if (graph.kind != "human_physical_gene_undirected_unweighted" or "string-12.5" not in graph.manifest["releases"] or
                any(graph.manifest.get("filters", {}).get(k) != v for k, v in PHYSICAL_FILTERS.items())):
            raise ValueError("Comparison requires the pinned STRING 12.5 physical c700/e400 graph")
        rwr = RWREngine(graph)
        with load_artifacts(artifacts) as saved:
            engine = RankingEngine(saved)
            for identifier, target_path in target_paths.items():
                start = perf_counter()
                disease = load_disease(target_path, identifier)
                payload = engine.rank(disease, pool)
                payload["provenance"]["stage1_manifest"] = file_record(artifacts / "manifest.json")
                payload = enrich_ranking(payload, rwr.rank(disease, pool), "physical")
                case_from_stage2(payload)  # Existing leakage/feature audit.
                if sorted(c["candidate_id"] for c in payload["candidates"]) != universe:
                    raise ValueError("Scoring changed the pinned eligible universe")
                selections = {m: select_shortlist(payload, ShortlistSettings(method=m)) for m in METHODS}
                prepared.append({"disease_id": identifier, "eligible_candidates": universe, "selections": selections,
                                 "network_scorable": {
                                     "zscore": [c["candidate_id"] for c in payload["candidates"] if c["status"] == "scored"],
                                     "physical_rwr": [c["candidate_id"] for c in payload["candidates"] if c["rwr"]["physical"]["status"] == "scored"]}})
                dest = out / identifier
                dest.mkdir()
                write_json(dest / "ranking.json", payload)
                for m in METHODS:
                    write_json(dest / f"{m}.json", project_shortlist(payload, ShortlistSettings(method=m)))
                timings[identifier] = perf_counter() - start
        # Detect accidental mutation of pinned inputs during scoring, before labels.
        if (file_record(references) != {k: inputs["references"][k] for k in ("bytes", "sha256")} or
                file_record(drugs) != {k: inputs["drugs"][k] for k in ("bytes", "sha256")} or
                file_record(cases) != inputs["case_list"] or
                file_record(protocol) != {k: inputs["published_protocol"][k] for k in ("bytes", "sha256")} or
                any(file_record(p) != {k: inputs["targets"][i][k] for k in ("bytes", "sha256")} for i, p in target_paths.items()) or
                any(file_record(artifacts / n) != record for n, record in graph_files.items())):
            raise ValueError("Frozen inputs changed during preparation")
        verify_implementation(seal)
        write_json(out / "shortlists.freeze.json", {"format_version": 1, "cases": prepared,
                   "sha256": canonical_hash(prepared), "state": "both_shortlists_frozen_before_reference_parsing"})
        labels = json.loads(references.read_text(encoding="utf-8"))  # First semantic label access.
        if not labels.get("releases") or not labels.get("source_files"):
            raise ValueError("Versioned references require releases and source_files provenance")
        known = parse_references(labels)
        extra = set(known) - set(ids)
        if extra:
            raise ValueError(f"Reference cases outside official cohort: {sorted(extra)}")
        result = compare_shortlists(prepared, known)
        result["reference_provenance"] = {k: labels.get(k, "missing") for k in ("definition", "releases", "source_files", "limitations")}
        result["inputs_freeze_sha256"] = canonical_hash(inputs)
        write_results(out, result)
        write_json(out / "timings.json", {"per_disease_seconds": timings, "total_seconds": perf_counter() - started})
        write_json(out / "outputs.manifest.json", {"format_version": 1, "files": {
            str(p.relative_to(out)).replace("\\", "/"): file_record(p) for p in sorted(out.rglob("*")) if p.is_file()}})
        return result
    except Exception as error:
        write_json(out / "failure.json", {"error_type": type(error).__name__, "error": str(error),
                                          "note": "No retry/overwrite; resolve the blocker and use a new output directory."})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sealing = sub.add_parser("seal", help="Seal implementation without accepting any labels or case list")
    sealing.add_argument("--out", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--seal", type=Path, required=True)
    compare = sub.add_parser("compare", help="Run only with the official 14-Disease inputs and published protocol")
    for name in ("seal", "cases", "targets-dir", "references", "drugs", "artifacts", "protocol", "out"):
        compare.add_argument("--" + name, type=Path, required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    if command == "seal":
        result = seal_implementation(args["out"])
        print(result["implementation_sha256"])
    elif command == "verify":
        result = verify_implementation(args["seal"])
        print(result["implementation_sha256"])
    else:
        result = run_comparison(**args)
        print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
