"""Freeze and compare RWR on two graphs using the unchanged Stage 3 metrics."""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from itertools import combinations
import json
from pathlib import Path
import tempfile
from time import perf_counter

from .artifacts import file_record, write_json
from .cohort import verify_bundle as verify_original_cohort
from .data import load_disease, load_drugs
from .evaluation import METRICS, EvaluationSettings, canonical_hash, case_from_stage2, mean_and_interval, retrieval_metrics
from .evaluation_io import write_csv
from .functional_graph import load_rwr_graph
from .references import parse_references
from .rwr import RWREngine, RWRSettings, enrich_ranking


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_methods(cases: list[dict], references: dict[str, set[str]], methods: list[str], settings: EvaluationSettings):
    """Parameterize method names, reusing existing recall/MRR/bootstrap functions."""
    if settings.missing_score_policy != "unretrieved":
        raise ValueError("The frozen RWR comparison uses unretrieved missing scores")
    if len({c["disease_id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate comparison Disease")
    rows, coverage_rows = [], []
    for case in sorted(cases, key=lambda c: c["disease_id"]):
        eligible = set(case["eligible_ids"])
        if len(eligible) != len(case["eligible_ids"]) or set(case["rankings"]) != set(methods):
            raise ValueError("Invalid method universe or method list")
        for method, ranking in case["rankings"].items():
            if len(set(ranking)) != len(ranking) or not set(ranking).issubset(eligible):
                raise ValueError(f"Invalid ordered Candidate IDs: {method}")
        known = references.get(case["disease_id"])
        common = set.intersection(eligible, *(set(case["rankings"][m]) for m in methods))
        coverage_rows.append({"disease_id": case["disease_id"], "eligible_candidates": len(eligible), "common_scorable": len(common),
                              "reference_total": None if known is None else len(known),
                              "reference_eligible": None if known is None else len(known & eligible),
                              "reference_common": None if known is None else len(known & common),
                              "reference_outside_eligible": None if known is None else sorted(known - eligible),
                              "reference_outside_common": None if known is None else sorted((known & eligible) - common),
                              "method_scorable": {m: len(case["rankings"][m]) for m in methods},
                              "method_status": case.get("method_status", {})})
        for scope, universe in (("full_eligible", eligible), ("common_scorable", common)):
            for method in methods:
                available = [cid for cid in case["rankings"][method] if cid in universe]
                missing = sorted(universe - set(available))
                metrics = retrieval_metrics(available, known, universe)
                failure = case.get("method_status", {}).get(method)
                if failure and failure != "converged":
                    metrics.update(label_status="method_unavailable:" + failure, **{m: None for m in METRICS})
                rows.append({"disease_id": case["disease_id"], "scope": scope, "method": method,
                             "universe_size": len(universe), "scorable_count": len(available), "missing_count": len(missing),
                             "coverage_fraction": len(available) / len(universe) if universe else None,
                             "missing_positive_count": None if known is None else len(set(missing) & known),
                             "ranked_candidate_ids": available, "missing_candidate_ids": missing,
                             "missing_score_policy": "unretrieved", **metrics})
    aggregate, paired, case_pairs = [], [], []
    for scope in ("full_eligible", "common_scorable"):
        for method in methods:
            subset = [r for r in rows if r["scope"] == scope and r["method"] == method]
            evaluated = [r for r in subset if r["label_status"] == "evaluated"]
            summary = {"scope": scope, "method": method, "evaluated_cases": len(evaluated),
                       "evaluated_case_ids": [r["disease_id"] for r in evaluated],
                       "skipped_cases": [{"disease_id": r["disease_id"], "reason": r["label_status"]} for r in subset if r["label_status"] != "evaluated"]}
            for metric in METRICS:
                summary[metric], summary[metric + "_ci95"] = mean_and_interval([r[metric] for r in evaluated], settings)
            aggregate.append(summary)
        for first, second in combinations(methods, 2):
            pairs = []
            for case in sorted(cases, key=lambda c: c["disease_id"]):
                a = next(r for r in rows if r["disease_id"] == case["disease_id"] and r["scope"] == scope and r["method"] == first)
                b = next(r for r in rows if r["disease_id"] == case["disease_id"] and r["scope"] == scope and r["method"] == second)
                if a["label_status"] == b["label_status"] == "evaluated":
                    pair = {"disease_id": case["disease_id"], "scope": scope, "first": first, "second": second,
                            **{"delta_" + m: b[m] - a[m] for m in METRICS}}
                    pairs.append(pair)
                    case_pairs.append(pair)
            summary = {"scope": scope, "first": first, "second": second, "direction": "second_minus_first",
                       "paired_cases": len(pairs), "case_ids": [p["disease_id"] for p in pairs]}
            for metric in METRICS:
                key = "delta_" + metric
                summary[key], summary[key + "_ci95"] = mean_and_interval([p[key] for p in pairs], settings)
            paired.append(summary)
    return {"metrics": rows, "coverage": coverage_rows, "aggregate": aggregate, "paired_comparisons": paired,
            "per_disease_comparisons": case_pairs}


def verify(root):
    manifest = read_json(root / "freeze.json")
    for name, record in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or file_record(path) != record:
            raise ValueError(f"Frozen RWR input changed: {name}")
    for path, record in manifest["external_files"].items():
        if file_record(Path(path)) != record:
            raise ValueError(f"Protected RWR source/artifact/report changed: {path}")
    return manifest


def prepare(root, cohort, physical, functional, protocol_path):
    if (root / "freeze.json").exists():
        raise FileExistsError("RWR experiment is already frozen")
    original = verify_original_cohort(cohort)
    protocol = read_json(protocol_path)
    settings = RWRSettings(**protocol["rwr"])
    excluded = set(protocol["excluded_jury_development_cases"])
    if not excluded.issubset(original["included_case_ids"]):
        raise ValueError("A jury-development exclusion is not in the source cohort")
    ids = sorted(set(original["included_case_ids"]) - excluded)
    cases = read_json(cohort / "cohort.json")
    original_refs = read_json(cohort / "references.json")
    references = {**original_refs, "cases": [c for c in original_refs["cases"] if c["disease_id"] in ids]}
    if set(parse_references(references)) != set(ids):
        raise ValueError("Reference cases do not match the frozen comparison list")
    graphs = {"physical": load_rwr_graph(physical), "functional": load_rwr_graph(functional)}
    if graphs["physical"].manifest["filters"]["combined_score_min"] != 700 or graphs["physical"].manifest["filters"]["experiments_min"] != 400:
        raise ValueError("The original physical graph filters differ from the protocol")
    if graphs["functional"].manifest["filters"] != protocol["functional_filters"]:
        raise ValueError("Functional graph filters differ from the frozen protocol")
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "protocol.json", protocol)
    write_json(root / "cases.json", {"included": [c for c in cases if c["disease_id"] in ids],
                                     "excluded": [{"disease_id": i, "name": protocol["excluded_jury_development_cases"][i], "reason": "jury_development_case"} for i in sorted(excluded)]})
    write_json(root / "references.json", references)
    protected = {Path(path): record for path, record in original["external_files"].items()}
    for name, record in original["files"].items():
        protected[cohort / name] = record
    for name, record in read_json(cohort / "run.json")["outputs"].items():
        protected[cohort / name] = record
    more = [protocol_path, cohort / "freeze.json", cohort / "run.json", *sorted(Path("ranking").rglob("*.py")),
            *sorted(Path("ranking").glob("*.md")), *sorted(Path("data/string").glob("*")), Path("data/stream_a/string_id_map.json")]
    for directory in (physical, functional):
        more.extend(p for p in directory.glob("*") if p.is_file())
    for directory in Path("data/ranking/network-paths-v1").glob("MONDO_*"):
        more.extend(directory.glob("*.json"))
    integration_input = Path("data/ranking/network-paths-v1/MONDO_0100096/ranking.json")
    integration_disease = Path("data/stream_a/disease_targets_MONDO_0100096.json")
    if not integration_input.is_file() or not integration_disease.is_file():
        raise FileNotFoundError("Existing COVID-19 path-enriched integration example is missing")
    more.extend([integration_input, integration_disease])
    for path in more:
        if path.is_file():
            actual = file_record(path)
            if path in protected and protected[path] != actual:
                raise ValueError(f"Original source output changed: {path}")
            protected[path] = actual
    manifest = {"format_version": 1, "phase": "configuration_graph_filters_cases_and_labels_frozen_before_rwr_evaluation",
                "frozen_utc": datetime.now(timezone.utc).isoformat(), "experiment_id": protocol["experiment_id"],
                "case_ids": ids, "excluded_case_ids": sorted(excluded), "settings": settings.__dict__,
                "protocol_content_sha256": canonical_hash(protocol), "source_cohort": str(cohort.resolve()),
                "graphs": {k: {"path": str(p.resolve()), "manifest": graphs[k].manifest_record, "kind": graphs[k].kind} for k, p in (("physical", physical), ("functional", functional))},
                "integration_example": {"ranking": str(integration_input.resolve()), "disease": str(integration_disease.resolve()), "included_in_metrics": False},
                "files": {name: file_record(root / name) for name in ("protocol.json", "cases.json", "references.json")},
                "external_files": {str(p.resolve()): record for p, record in sorted(protected.items(), key=lambda item: str(item[0]))}}
    write_json(root / "freeze.json", manifest)
    print(json.dumps({"cases": len(ids), "references": sum(len(c["known_candidate_ids"]) for c in references["cases"]),
                      "excluded": sorted(excluded), "freeze": file_record(root / "freeze.json")}, indent=2))


def markdown_report(results, protocol, freeze, run):
    lines = ["# RWR and functional STRING comparison", "", "Retrospective source-record relationship recovery. Network scores are not treatment-success probabilities.", "",
             f"Compared **{len(freeze['case_ids'])} Diseases**, excluding all five jury-development cases. Original Stage 1–3, 16-case benchmark and path outputs are unchanged. Configuration and graph/input hashes were frozen at `{freeze['frozen_utc']}` before any RWR evaluation. No tuning was performed.", "",
             "The exclusions are rheumatoid arthritis, type 2 diabetes mellitus, Parkinson disease, COPD and hypertensive disorder. The remaining cases were already present in the previous 16-case benchmark: this is a jury-development-excluded comparison, not an unseen or prospective clinical holdout.", "",
             "## Method and graphs", "", "RWR uses the same top-50 evidence_only Disease Target pool before coverage filtering, uniform restart on each graph's retained Disease Targets, restart probability **0.3**, float64 row normalization, L1 successive-iterate tolerance **1e-12** and limit **1,000** iterations. Dangling transition rows use self-loops. Candidate score is mean stationary mass at all retained drug Targets, ranked descending then ChEMBL ID. No distance, z-score or additional normalization is mixed into RWR.", "",
             "Both graph methods score within their own largest connected component. Thus functional RWR changes both topology and retained Disease/drug Target coverage; the graph comparison does not isolate topology alone. Both graphs are binary, undirected and unweighted after filtering.", "",
             "| Graph | Nodes | Edges | Components | Largest component nodes | Largest component edges | Build time |", "|---|---:|---:|---:|---:|---:|---:|"]
    for key, entry in run["graphs"].items():
        graph = entry["report"]
        lines.append(f"| {key} | {graph['nodes']} | {graph['edges']} | {graph['components']} | {graph['largest_component_nodes']} | {graph['largest_component_edges']} | {entry['build_seconds']:.3f} s |")
    lines += ["", "The original graph is the physical subnetwork at combined score ≥700 and direct experiments ≥400. The separate functional-association graph uses the official human `9606.protein.links.v12.5.txt.gz`, combined score ≥700 and no experimental-channel condition. The file was absent initially and downloaded from the [official STRING human downloads](https://string-db.org/cgi/download?species=Homo+sapiens); its actual three columns are protein1, protein2 and combined_score. It was not substituted with physical links. Functional associations may include indirect relationships and are not physical interaction claims. Mapping exclusions, duplicate-edge handling, raw hashes and download provenance are retained. No all-pairs distance matrix was needed for the new graph."]
    for scope in ("full_eligible", "common_scorable"):
        lines += ["", f"## {scope}", "", "| Method | Evaluated Diseases | Recall@5 | Recall@10 | Recall@20 | MRR |", "|---|---:|---:|---:|---:|---:|"]
        for row in results["aggregate"]:
            if row["scope"] == scope:
                def number(value):
                    return "null" if value is None else f"{value:.6f}"
                lines.append(f"| {row['method']} | {row['evaluated_cases']} | " + " | ".join(number(row[m]) for m in METRICS) + " |")
    lines += ["", "Full-universe methods use the identical fixed 1,956-Candidate approved universe per Disease; missing scores remain unretrieved misses rather than disappearing from denominators. Common-scorable metrics use the intersection of all five method-available sets. Missing labels and failed methods have explicit null metrics/statuses. Confidence intervals, exact denominators, missing IDs and per-Disease metrics are in the CSV/JSON files.", "",
              "## Coverage and convergence", "", "| Disease | Physical/functional retained Disease Targets | Physical/functional RWR Candidate coverage | Eligible/common reference pairs |", "|---|---:|---:|---:|"]
    for row in run["case_summary"]:
        lines.append(f"| {row['name']} ({row['disease_id']}) | {row['physical_disease_targets']}/{row['functional_disease_targets']} | {row['physical_candidates']}/{row['functional_candidates']} | {row['reference_eligible']}/{row['reference_common']} |")
    lines += ["", f"Across the comparison there are **{sum(r['reference_eligible'] for r in results['coverage'])} eligible Disease–Candidate reference pairs**. Total run time: **{run['seconds']:.3f} seconds**; RWR solve/scoring timings, iteration counts, residuals and unit-mass checks are in `timings.csv` and the saved per-graph results. Failed methods: `{run['failures']}`. Candidate unscorable reasons: `{run['unscorable_reasons']}`.", "",
              "## Real leading RWR Candidates", "", "| Disease | Physical RWR leader / mean mass | Functional RWR leader / mean mass |", "|---|---|---|"]
    for row in run["case_summary"]:
        a, b = row["physical_top"], row["functional_top"]
        def leader(value):
            return "unavailable" if not value else f"{value['name']} ({value['candidate_id']}) / {value['score']:.8g}"
        lines.append(f"| {row['disease_id']} | {leader(a)} | {leader(b)} |")
    lines += ["", "## Paired differences and uncertainty", "", "Differences are second minus first on matched Diseases. The following full-universe comparisons are selected from all ten predeclared unordered pairs; every pair and both scopes are exported.", "",
              "| First → second | Paired Diseases | Δ Recall@20 [95% bootstrap interval] | Δ MRR [95% bootstrap interval] |", "|---|---:|---|---|"]
    for row in results["paired_comparisons"]:
        if row["scope"] == "full_eligible" and row["second"].startswith("rwr_") and (row["first"] == "direct_evidence" or row["first"] == "rwr_physical"):
            lines.append(f"| {row['first']} → {row['second']} | {row['paired_cases']} | {row['delta_recall_at_20']:.6f} {row['delta_recall_at_20_ci95']} | {row['delta_mrr']:.6f} {row['delta_mrr_ci95']} |")
    lines += ["", "Intervals resample Disease-level paired differences using seed 0 and 1,000 bootstrap draws, reusing the existing Stage 3 implementation. With 11 purposively chosen, related Diseases these intervals are descriptive; multiple pair comparisons are not adjusted, and they do not establish clinical superiority or generalization.", "",
              "## Integration and limitations", "", "New Candidate `rwr.physical` and `rwr.functional` objects contain standalone scores/ranks, per-graph coverage, iteration/convergence information, graph classification/version/manifest hash, and up to three highest stationary-mass Target contributions. Existing network, distance, z-score, shortlist and network_paths fields are preserved exactly. `shortest_paths_explain_this_score=false` explicitly separates RWR from shortest-path explanations. The separately generated COVID-19 integration example preserves every existing path object and is excluded from these metrics.", "",
              "The reference labels and all known limitations of the original frozen source-reference cohort are retained. Regulatory metadata can contradict cited source text; excluding the five jury-development cases also excludes the previously found trientine/RA contradiction, but does not independently validate the remaining labels. Unlabelled pairs are not proven negatives. Features omit direct clinical-precedence and cancer-biomarker channels, while literature, target curation, functional associations and degree/study biases can retain indirect known-relationship leakage. Plain RWR may favor highly connected proteins; no degree correction or tuning was added.", "",
              "Artifacts: frozen protocol/cases/references and hashes in the parent directory; enriched rankings, per-graph RWR results, complete stationary distributions, metrics.csv, coverage.csv, aggregate.csv, paired_comparisons.csv, per_disease_comparisons.csv, timings.csv, top_candidates.json, integration_example.json and run.json in this results directory. All generated assets are gitignored. No Model jury, Reactome, frontend, docking or existing scoring module was changed.", ""]
    return "\n".join(lines)


def run(root):
    freeze = verify(root)
    output = root / "results"
    if output.exists():
        raise FileExistsError("RWR comparison results already exist")
    protocol = read_json(root / "protocol.json")
    cohort = Path(freeze["source_cohort"])
    drugs = load_drugs(cohort / "drug_targets.json")
    engines = {key: RWREngine(load_rwr_graph(info["path"]), RWRSettings(**protocol["rwr"])) for key, info in freeze["graphs"].items()}
    references = parse_references(read_json(root / "references.json"))
    cases, timings, failures, top_candidates, case_summary = [], [], [], [], []
    unscorable = Counter()
    started = perf_counter()
    with tempfile.TemporaryDirectory(prefix=".rwr-comparison-", dir=root) as temporary:
        staged = Path(temporary) / "results"
        for name in ("rankings", "rwr_scores", "distributions"):
            (staged / name).mkdir(parents=True)
        for identifier in freeze["case_ids"]:
            baseline = read_json(cohort / "rankings" / f"{identifier}.json")
            base_case = case_from_stage2(baseline)
            disease = load_disease(cohort / "targets" / f"{identifier}.json", identifier)
            rankings = {m: base_case.rankings[m] for m in ("direct_evidence", "raw_proximity", "degree_matched_z")}
            status, assessments, enriched = {}, {}, baseline
            for key, engine in engines.items():
                assessment = engine.rank(disease, drugs)
                assessments[key] = assessment
                method = "rwr_" + key
                status[method] = assessment["convergence"]["status"]
                ordered = sorted((c for c in assessment["candidates"] if c["score"] is not None), key=lambda c: c["rank"])
                rankings[method] = tuple(c["candidate_id"] for c in ordered)
                if status[method] != "converged":
                    failures.append({"disease_id": identifier, "method": method, "reason": status[method]})
                unscorable.update({method + ":" + str(reason): count for reason, count in Counter(c["reason"] for c in assessment["candidates"] if c["reason"]).items()})
                timings.append({"disease_id": identifier, "method": method, **assessment["convergence"], **assessment["timing_seconds"]})
                top_candidates.append({"disease_id": identifier, "method": method, "top": [{k: c[k] for k in ("candidate_id", "name", "rank", "score")} for c in ordered[:10]]})
                write_json(staged / "distributions" / f"{identifier}_{key}.json", assessment["stationary_distribution"])
                write_json(staged / "rwr_scores" / f"{identifier}_{key}.json", {k: v for k, v in assessment.items() if k not in {"stationary_distribution", "timing_seconds"}})
                enriched = enrich_ranking(enriched, assessment, key)
            if case_from_stage2(enriched) != base_case:
                raise ValueError("RWR enrichment changed the existing Stage 3 case")
            write_json(staged / "rankings" / f"{identifier}.json", enriched)
            cases.append({"disease_id": identifier, "eligible_ids": base_case.eligible_candidates, "rankings": rankings, "method_status": status})
            def top(key):
                valid = [c for c in assessments[key]["candidates"] if c["rank"] == 1]
                return None if not valid else {k: valid[0][k] for k in ("candidate_id", "name", "score")}
            case_summary.append({"disease_id": identifier, "name": baseline["disease"]["name"],
                                 **{key + "_disease_targets": value["disease"]["coverage"]["retained"] for key, value in assessments.items()},
                                 **{key + "_candidates": sum(c["score"] is not None for c in value["candidates"]) for key, value in assessments.items()},
                                 "physical_top": top("physical"), "functional_top": top("functional")})
            print(f"RWR {identifier}: " + ", ".join(f"{k}={v['convergence']['status']}/{v['convergence']['iterations']} iterations" for k, v in assessments.items()), flush=True)
        results = evaluate_methods(cases, references, protocol["methods"], EvaluationSettings(**protocol["evaluation"]))
        for row in case_summary:
            counts = next(c for c in results["coverage"] if c["disease_id"] == row["disease_id"])
            row.update(reference_eligible=counts["reference_eligible"], reference_common=counts["reference_common"])
        example = freeze["integration_example"]
        original_example = read_json(example["ranking"])
        enriched_example = original_example
        for key, engine in engines.items():
            assessment = engine.rank(load_disease(example["disease"], original_example["disease"]["id"]), drugs)
            enriched_example = enrich_ranking(enriched_example, assessment, key)
        restored = deepcopy(enriched_example)
        restored.pop("rwr_provenance")
        for candidate in restored["candidates"]:
            candidate.pop("rwr")
        if restored != original_example:
            raise ValueError("RWR integration changed an original field or network_paths")
        write_json(staged / "integration_example.json", enriched_example)
        results.update(classification=protocol["classification"], freeze=file_record(root / "freeze.json"), case_ids=freeze["case_ids"])
        write_json(staged / "results.json", results)
        write_csv(staged / "metrics.csv", results["metrics"], ("ranked_candidate_ids", "missing_candidate_ids"))
        for name in ("coverage", "aggregate", "paired_comparisons", "per_disease_comparisons"):
            write_csv(staged / f"{name}.csv", results[name])
        write_csv(staged / "timings.csv", timings)
        write_json(staged / "top_candidates.json", top_candidates)
        run_record = {"freeze": file_record(root / "freeze.json"), "seconds": perf_counter() - started,
                      "failures": failures, "unscorable_reasons": dict(unscorable), "case_summary": case_summary,
                      "graphs": {key: {"report": e.artifacts.manifest["graph"], "build_seconds": e.artifacts.manifest.get("build_seconds", 0.0)} for key, e in engines.items()},
                      "integration_preserved_all_fields_and_paths": True}
        (staged / "report.md").write_text(markdown_report(results, protocol, freeze, run_record), encoding="utf-8")
        verify(root)
        run_record["outputs"] = {p.relative_to(staged).as_posix(): file_record(p) for p in sorted(staged.rglob("*")) if p.is_file()}
        write_json(staged / "run.json", run_record)
        staged.rename(output)
    print(json.dumps({"cases": len(cases), "seconds": run_record["seconds"], "failures": failures,
                      "aggregate": [{k: r[k] for k in ("scope", "method", *METRICS)} for r in results["aggregate"]]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cohort", type=Path, default=Path("data/evaluation/cohort-ot26.09-v1"))
    parser.add_argument("--physical", type=Path, default=Path("data/ranking/string-12.5-c700-e400"))
    parser.add_argument("--functional", type=Path, default=Path("data/ranking/string-12.5-functional-c700-v1"))
    parser.add_argument("--protocol", type=Path, default=Path(__file__).with_name("rwr_protocol.json"))
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.root, args.cohort, args.physical, args.functional, args.protocol)
        elif args.command == "run":
            run(args.root)
        else:
            freeze = verify(args.root)
            print(json.dumps({"verified_cases": len(freeze["case_ids"]), "freeze": file_record(args.root / "freeze.json")}))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Error: {exc}\n")
