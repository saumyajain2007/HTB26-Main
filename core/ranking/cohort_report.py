"""Offline cohort diagnostics, replay checks and a measured benchmark report."""

import argparse
from collections import Counter, defaultdict
import importlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

from .artifacts import file_record, write_json
from .cohort import (alias_index, check_version, extract_labels, mechanism_scope,
                     read_json, recording_client, verify_bundle)
from .data import load_drugs
from .evaluation import canonical_hash, EvaluationSettings
from .evaluation_io import run_evaluation, write_csv
from .scoring import coverage, rank_files, RankingSettings


def interpret_mechanism(source_scope, target_records):
    """A missing organism on a metal entity is not evidence of a pathogen."""
    if source_scope["human_mechanism_targets"]:
        return "human_mechanism_supplied"
    if any(t.get("target_type") == "METAL" for t in target_records):
        return "nonprotein_metal_entity_in_supplied_mechanism"
    if any(t.get("organism") and t["organism"] != "Homo sapiens" for t in target_records):
        return "nonhuman_organism_target_in_supplied_mechanism"
    return source_scope["classification"]


def replay_inputs(root, freeze):
    """Reconstruct all labels/features offline from archived source records."""
    import duckdb
    protocol = read_json(root / "protocol.json")
    sys.path.insert(0, str((root / "pipeline_snapshot").resolve()))
    pipeline = importlib.import_module("pipeline.disease_targets")
    with patch("pipeline.opentargets.OpenTargetsClient.execute", side_effect=AssertionError("Offline replay attempted a network request")):
        with recording_client(root, protocol["release"]) as client:
            for identifier in freeze["included_case_ids"]:
                rebuilt = pipeline.disease_targets(client, identifier)
                if rebuilt != read_json(root / "targets" / f"{identifier}.json"):
                    raise ValueError(f"Disease Target replay mismatch: {identifier}")
    for path in sorted((root / "api").glob("*.json")):
        check_version(read_json(path)["data"], protocol["release"])
    with duckdb.connect() as db:
        indications = [json.loads(r[0]) for r in db.execute("SELECT to_json(i) FROM read_parquet(?) i WHERE diseaseId IN (SELECT unnest(?))",
                        [str(root / "raw/clinical_indication.parquet"), freeze["included_case_ids"]]).fetchall()]
        ids = sorted({i for row in indications for i in row["clinicalReportIds"]})
        reports = {r["id"]: r for r in (json.loads(i[0]) for i in db.execute("SELECT to_json(r) FROM read_parquet(?) r WHERE id IN (SELECT unnest(?))",
                   [str(root / "raw/clinical_report.parquet"), ids]).fetchall())}
    drugs = load_drugs(root / "drug_targets.json")
    by_id = {d.id: d for d in drugs.drugs}
    relationships, exclusions = extract_labels(indications, reports, set(by_id), alias_index(drugs.drugs),
                                                read_json(root / "variant_checks.json")["parents"], protocol["release"])
    index = read_json(Path(freeze["artifacts_path"]) / "index.json")
    graph, lcc = set(index["graph_gene_ids"]), set(index["distance_gene_ids"])
    for row in relationships:
        drug = by_id.get(row["candidate_id"]) if row["eligible"] else None
        row["mechanism_scope"] = mechanism_scope(drug)
        row["coverage"] = None if drug is None else coverage(drug.targets, list(drug.targets.rows), graph, lcc, drug.unmapped)
    for name, rebuilt in (("relationships.json", relationships), ("label_exclusions.json", exclusions)):
        if rebuilt != read_json(root / name):
            raise ValueError(f"Label replay mismatch: {name}")
    return {"disease_inputs_reconstructed": len(freeze["included_case_ids"]), "label_records_reconstructed": len(relationships),
            "label_exclusions_reconstructed": len(exclusions), "network_requests": 0}


def generate(root, output):
    freeze = verify_bundle(root)
    run = read_json(root / "run.json")
    if run["freeze"] != file_record(root / "freeze.json"):
        raise ValueError("Ranking run does not match the frozen cohort")
    for name, record in run["outputs"].items():
        if file_record(root / name) != record:
            raise ValueError(f"Benchmark output changed: {name}")
    checks = replay_inputs(root, freeze)
    protocol = read_json(root / "protocol.json")
    ranking_paths = sorted((root / "rankings").glob("*.json"))
    replay = root / "evaluation-replay"
    if not replay.exists():
        run_evaluation(list(reversed(ranking_paths)), replay, references_path=root / "references.json",
                       settings=EvaluationSettings(**protocol["evaluation_settings"]))
    originals = sorted((root / "evaluation").glob("*"))
    if len(list(replay.glob("*"))) != len(originals) or any(file_record(path) != file_record(replay / path.name) for path in originals):
        raise ValueError("Evaluation replay is not byte-identical")
    checks["byte_identical_evaluation_files"] = len(originals)
    identifier = freeze["included_case_ids"][0]
    repeat = rank_files(freeze["artifacts_path"], root / "drug_targets.json", root / "targets" / f"{identifier}.json", identifier,
                        RankingSettings(**protocol["ranking_settings"]))
    original = read_json(root / "rankings" / f"{identifier}.json")
    for payload in (repeat, original):
        for field in ("created_utc", "ranking_seconds", "total_seconds"):
            payload.pop(field)
    if repeat != original:
        raise ValueError("Ranking replay differs beyond timestamps/runtime")
    checks.update(ranking_replay_case=identifier, ranking_replay_content_sha256=canonical_hash(repeat))
    results = read_json(root / "evaluation/results.json")
    cases = read_json(root / "cohort.json")
    relationships = read_json(root / "relationships.json")
    drugs = {d.id: d for d in load_drugs(root / "drug_targets.json").drugs}
    audit_dir = root / "mechanism_audit"
    entity_records, audit_sources = {}, {}
    if audit_dir.exists():
        for path in sorted(audit_dir.glob("*.provenance.json")):
            key = path.name.removesuffix(".provenance.json")
            source = audit_dir / (key + (".html" if key == "trientine_dailymed" else ".json"))
            provenance = read_json(path)
            if file_record(source) != {k: provenance[k] for k in ("bytes", "sha256")}:
                raise ValueError("Interpretation source hash mismatch")
            audit_sources[key] = provenance
            if key.endswith("_target"):
                target = read_json(source)
                entity_records[target["target_chembl_id"]] = target
        if read_json(audit_dir / "status.json")["chembl_db_version"] != "ChEMBL_37":
            raise ValueError("Unexpected mechanism audit source version")
    contradictions = read_json(audit_dir / "label-contradictions.json") if (audit_dir / "label-contradictions.json").exists() else []
    grouped = defaultdict(list)
    for row in relationships:
        if row["disease_id"] in freeze["included_case_ids"]:
            grouped[row["disease_id"], row["candidate_id"]].append(row)
    rankings = {path.stem: read_json(path) for path in ranking_paths}
    diagnostic, missing = [], []
    ranks = {(row["disease_id"], row["method"]): {cid: i for i, cid in enumerate(row["ranked_candidate_ids"], 1)}
             for row in results["metrics"] if row["scope"] == "full_eligible"}
    for (disease, cid), source_rows in sorted(grouped.items()):
        candidate = next((c for c in rankings[disease]["candidates"] if c["candidate_id"] == cid), None)
        drug = drugs.get(cid)
        entity_targets = [entity_records[r["item"]] for r in (drug.unmapped if drug else [])
                          if r.get("source") == "mechanism" and r.get("item") in entity_records]
        diagnostic.append({"disease_id": disease, "candidate_id": cid, "name": None if candidate is None else candidate["name"],
                           "original_drug_ids": sorted({r["original_drug_id"] for r in source_rows}),
                           "eligible": source_rows[0]["eligible"], "mechanism_scope": source_rows[0]["mechanism_scope"],
                           "mechanism_interpretation": interpret_mechanism(source_rows[0]["mechanism_scope"], entity_targets),
                           "source_validation_flags": [f for f in contradictions if f["disease_id"] == disease and f["candidate_id"] == cid],
                           "coverage": source_rows[0]["coverage"], "network_status": None if candidate is None else candidate["status"],
                           "network_reason": None if candidate is None else candidate["unscorable_reason"],
                           **{method + "_rank": ranks[disease, method].get(cid) for method in ("direct_evidence", "shared_targets", "raw_proximity", "degree_matched_z")},
                           "shortlisted": cid in rankings[disease]["shortlist"], "source_records": source_rows})
    for disease, ranking in rankings.items():
        for candidate in ranking["candidates"]:
            if candidate["status"] != "scored":
                missing.append({"disease_id": disease, "candidate_id": candidate["candidate_id"], "name": candidate["name"],
                                "status": candidate["status"], "reason": candidate["unscorable_reason"] or (candidate["network"] or {}).get("warning"),
                                "coverage": candidate["coverage"]})
    scopes = Counter(r["mechanism_scope"]["classification"] for r in diagnostic)
    interpreted_scopes = Counter(r["mechanism_interpretation"] for r in diagnostic)
    stats = {"case_count": len(rankings), "source_indication_records": len(relationships), "reference_pairs": len(diagnostic),
             "unique_reference_candidates": len({r["candidate_id"] for r in diagnostic}),
             "eligible_reference_pairs": sum(row["positive_eligible"] for row in results["coverage"]),
             "common_reference_pairs": sum(row["positive_common"] for row in results["coverage"]),
             "excluded_cases": [c for c in cases if not c["included"]], "mechanism_scopes": dict(scopes),
             "interpreted_mechanism_scopes": dict(interpreted_scopes), "label_contradictions": contradictions,
             "interpretation_audit_sources": audit_sources,
             "label_exclusion_reasons": dict(Counter(r["reason"] for r in read_json(root / "label_exclusions.json"))),
             "not_scored_records": len(missing), "not_scored_reasons": dict(Counter(r["reason"] for r in missing)),
             "run_seconds": run["total_seconds"], "ranking_seconds": sum(t["seconds"] for t in run["timings"]),
             "checks": checks, "freeze": file_record(root / "freeze.json"), "reporter": file_record(Path(__file__)),
             "environment_lock": file_record(root / "environment.lock.txt"),
             "environment_lock_timing": "Recorded after input sealing, before ranking; not included in freeze.files.",
             "source_catalog": read_json(root / "sources.json"), "aggregate": results["aggregate"],
             "paired_comparisons": results["paired_comparisons"]}
    write_json(root / "diagnostics.json", stats)
    write_csv(root / "reference_diagnostics.csv", diagnostic)
    write_csv(root / "not_scored.csv", missing)
    write_csv(root / "label_validation_flags.csv", contradictions)
    lines = ["# Expanded Open Targets 26.09 benchmark", "", "Measured 25 October 2026 for Zaid. **Retrospective known-relationship recovery**, not prospective prediction or treatment-success probability.", "",
             f"Completed **{stats['case_count']} additional Diseases**, {len({c['area'] for c in cases})} therapeutic areas, **{stats['reference_pairs']} distinct Disease–Candidate source-reference pairs** ({stats['unique_reference_candidates']} unique Candidates), from {stats['source_indication_records']} original indication records meeting the frozen metadata rule. All reference pairs are eligible in the fixed Candidate universe. No collection or ranking execution failed. **A targeted source check found a confirmed label contradiction; these are source-record recovery metrics, not a validated approved-treatment benchmark.**", "",
             f"Each method uses the same **1,956** approved Candidates per Disease. **1,307/1,956 (66.82%)** have valid raw and z-scores; 649 remain explicitly unscorable per Disease. Reference network coverage is **{stats['common_reference_pairs']}/{stats['eligible_reference_pairs']} ({stats['common_reference_pairs']/stats['eligible_reference_pairs']:.2%})**. All 16 Diseases have positives in the common subset.", "",
             "## Selection and freezing", "", "The tracked `ranking/cohort_protocol.json` predeclares 16 established-condition names across rheumatology, dermatology, respiratory, gastroenterology, metabolic, cardiovascular, oncology and neurology. This is a purposive convenience panel, not a random epidemiological sample. Unique exact canonical names take precedence over exact synonyms in the pinned Disease table. No ranks, z-scores or recovery metrics determine inclusion, and failed cases are not replaced.", "",
             "Inclusion requires at least 25 positive evidence-only Target scores among the top 50, at least 20 top-50 Targets in the largest network component, and at least one eligible reference Candidate with a supplied human mechanism Target. All 16 passed; excluded cases: **none**. Hypertension resolves through an exact synonym to hypertensive disorder; Hypercholesterolemia uses the release's HP identifier. COVID-19 and multiple myeloma remain separate smoke tests and are absent from this cohort.", "",
             f"Inputs, case decisions, labels, source tables, API responses, pipeline snapshot and scorer/evaluator source hashes were sealed **before any cohort ranking** at `{freeze['frozen_utc']}`. Freeze SHA256: `{stats['freeze']['sha256']}`. The original smoke-test and Stage 2 outputs are protected by the seal and passed verification after evaluation.", "",
             "## Actual cases", "", "Targets are retained/50; references are eligible/common-scorable. Shortlist recall uses every eligible reference in the denominator.", "",
             "| Disease | Open Targets ID | Targets | References | Shortlist Recall@15 |", "|---|---|---:|---:|---:|"]
    coverage_by_id = {r["disease_id"]: r for r in results["coverage"]}
    shortlist = {(r["disease_id"], r["scope"]): r for r in results["shortlist"]}
    for case in cases:
        if not case["included"]:
            continue
        identifier = case["disease_id"]
        row = coverage_by_id[identifier]
        selected = shortlist[identifier, "full_eligible"]
        lines.append(f"| {case['resolved_name']} | {identifier} | {case['retained_targets']}/50 | {row['positive_eligible']}/{row['positive_common']} | {selected['known_selected']}/{selected['positive_in_scope']} = {selected['recall_at_15']:.4f} |")
    for scope in ("full_eligible", "common_scorable"):
        lines += ["", f"## {scope}", "", "Macro means across all 16 Diseases; missing full-universe scores are `unretrieved` and remain misses. Common-scope evaluation uses the same 1,307-Candidate intersection for every method.", "",
                  "| Method | Recall@5 | Recall@10 | Recall@20 | MRR |", "|---|---:|---:|---:|---:|"]
        for row in results["aggregate"]:
            if row["scope"] == scope:
                lines.append(f"| {row['method']} | " + " | ".join(f"{row[k]:.6f}" for k in ("recall_at_5", "recall_at_10", "recall_at_20", "mrr")) + " |")
        comparison = next(r for r in results["paired_comparisons"] if r["scope"] == scope)
        lines += ["", f"Paired z-score minus direct evidence: Δ Recall@20 **{comparison['delta_recall_at_20']:.6f}**, Δ MRR **{comparison['delta_mrr']:.6f}**. Their bootstrap 95% intervals are `{comparison['delta_recall_at_20_ci95']}` and `{comparison['delta_mrr_ci95']}`. The unchanged degree-matched method does not improve these cohort macro metrics over direct evidence."]
    lines += ["", "## Label provenance and suitability", "",
              "Labels were extracted independently of scoring and Stream A's aggregate `approval.disease_ids`, from complete release-pinned `clinical_indication` and `clinical_report` Parquet tables. The exact `clinicalReportIds` join requires matching original drug and Disease membership, indication and report approval stage, report type `INDICATION`, a recognized regulator source (FDA, EMA Human Drugs, PMDA, DailyMed), and a source URL. A linked regulator withdrawal rejects the pair. Trials, TTD claims and stage alone do not qualify. All report IDs, URLs, years (including null), provider/type, source-release information and original drug variants are retained in the reference diagnostics.", "",
              f"Rejected source indication records: `{stats['label_exclusion_reasons']}`. No linked report is missing. All 534 accepted original records map to eligible Candidates: exact IDs or a uniquely owned Stream A variant whose Open Targets parent was verified with release-checked API responses. Parent mapping deduplicates labels to 487 Disease–Candidate pairs; it does not alter the scorer's Candidate universe or Target data.", "",
              f"Frozen source mechanism flags across distinct reference pairs: `{dict(scopes)}`. These describe supplied evidence, not an independently adjudicated primary mechanism for every clinical use. A subsequent ChEMBL 37 Target-entity check yields `{dict(interpreted_scopes)}`. In particular, `non_human_target` does not necessarily mean a pathogen: Copper (`CHEMBL2363057`) has Target type `METAL` and null organism. Penicillamine and trientine reference that entity. Azithromycin references bacterial 70S ribosome (`CHEMBL2363135`, organism Bacteria). The three affected references have no network score and remain visible in the frozen full-universe results:", ""]
    for row in diagnostic:
        if row["mechanism_scope"]["classification"] == "nonhuman_mechanism_without_human_mechanism":
            lines.append(f"- {row['disease_id']}: **{row['name']}** (`{row['candidate_id']}`), {row['mechanism_interpretation']}; supplied gene Target count {row['coverage']['total']}, retained {row['coverage']['retained']}.")
    lines += ["", "The human STRING graph cannot represent pathogen-only or nonprotein therapeutic mechanisms. Bioactivity against human proteins alone does not prove a drug's primary therapeutic mechanism acts through them. The full-universe metrics retain these limitations; the common subset measures a different, coverage-conditioned population. The entity audit is interpretation-only and did not alter frozen labels, feature inputs, selection or metrics.", "",
              "## Confirmed source-label contradiction", "",
              "The frozen trientine–rheumatoid arthritis pair (`CHEMBL609`, `MONDO_0008383`, original salt `CHEMBL3989777`) passes every metadata filter: Open Targets links a DailyMed approval-stage indication record with matching IDs and a real URL. However, that very [SYPRINE label, updated September 2020](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=c34f77a7-996b-4470-b5df-d946a7fe5dbe) indicates Wilson disease in penicillamine-intolerant patients and explicitly advises against rheumatoid arthritis use. The source metadata therefore contains at least one false positive relative to its cited regulatory text.", "",
              "This was found in a targeted mechanism/source review after ranking, not a random quality sample; it does not estimate the overall error rate. The label page, retrieval metadata and hashes are archived separately in `mechanism_audit/`, and `label_validation_flags.csv` identifies the contradiction. **No post-result label removal or metric repair was made.** All reported metrics retain the exact frozen 487-pair source-reference set. A clinically vetted approved-treatment reference set remains blocked on source-text adjudication and a newly versioned label release; the metadata-only collector cannot establish clinical indication validity. Do not describe these 487 pairs as 487 confirmed approved treatments.", "",
              "## Reproducibility, outputs and limitations", "",
              f"The offline replay reconstructed all **{checks['disease_inputs_reconstructed']} Disease Target files**, **{checks['label_records_reconstructed']} label records** and all rejected records identically, without network requests. All **{checks['byte_identical_evaluation_files']} evaluation files** replayed byte-for-byte with reversed ranking-input order. Re-running the first frozen case (`{checks['ranking_replay_case']}`) reproduced every ranking field except the three explicitly volatile timestamp/runtime fields. Source/artifact/code checksums and original smoke-test checksums passed.", "",
              f"Measured run time: **{stats['run_seconds']:.3f} seconds**, including **{stats['ranking_seconds']:.3f} seconds** in 16 Stage 2 calls. Ranking failures: **0**. There are **{stats['not_scored_records']}** unscorable Disease–Candidate records, all `no_retained_drug_targets`; no zero-variance or insufficient-pool failure occurred. These are the same 649 unique Candidates per Disease. Pipeline code is unmodified at commit `{freeze['pipeline_commit']}`; its full-association rescoring validates default API scores before selecting top-50 `evidence_only` Targets. All API snapshots assert data release 26.09. Optional collection dependencies are DuckDB 2.0.0 and HTTPX 0.28.1; the full environment lock and its hash are recorded in diagnostics (the lock was captured after input sealing, before ranking).", "",
              "Outputs under `data/evaluation/cohort-ot26.09-v1/`: `freeze.json`, `protocol.json`, `sources.json`, `cohort.json`/`cases.csv`, `references.json`, `relationships.json`/`.csv`, `label_exclusions.json`/`.csv`, `variant_checks.json`, archived raw Parquet/API files, `targets/`, `rankings/`, `evaluation/` (CSV/JSON/Markdown, intervals and paired comparisons), `run.json`/`timings.csv`, `diagnostics.json`, `reference_diagnostics.csv`, `not_scored.csv`, `label_validation_flags.csv`, `mechanism_audit/` and `evaluation-replay/`. All data and generated artifacts are gitignored. `reference_diagnostics.csv` lists every known Candidate, provenance, coverage, four baseline ranks, shortlist membership and interpretation flags. `not_scored.csv` lists every missing network calculation.", "",
              "Source versions and byte hashes for all three Parquet datasets are in `sources.json` and diagnostics. Pinned downloads: [Open Targets 26.09 Disease table](https://open-targets-public-data-releases.s3.eu-west-1.amazonaws.com/platform/26.09/output/disease/00000000.parquet), [clinical indications](https://open-targets-public-data-releases.s3.eu-west-1.amazonaws.com/platform/26.09/output/clinical_indication/00000000.parquet), [clinical reports](https://open-targets-public-data-releases.s3.eu-west-1.amazonaws.com/platform/26.09/output/clinical_report/00000000.parquet). Dataset definitions are documented on the [official downloads page](https://platform.opentargets.org/downloads).", "",
              "Approval histories in these source records are not a fresh jurisdiction-specific adjudication of current authorization or clinical benefit. Some source years are null; release 26.09 is the data cutoff, not an inferred approval date. Source URLs are preserved, but their pages were not independently re-curated one by one. Missing relationships remain unlabelled, not ineffective drugs. Current Candidate IDs can represent related formulations; metrics count Candidate IDs, not clinical regimens.", "",
              "The features exclude direct clinical-precedence and cancer-biomarker channels and treatment labels do not enter scoring. Residual indirect leakage through literature, target curation and network study bias remains possible because labels and features share Open Targets/ChEMBL sources. Related Diseases also share drugs and Targets. This is a 16-case retrospective convenience pilot; bootstrap intervals and one seeded random permutation do not establish clinical generalization. Raw proximity has stronger MRR here than the z-score, while direct evidence has stronger early recall than the z-score; no algorithm was adjusted after seeing these results. The generic Stage 3 report retains a legacy two-example caveat from the earlier smoke-test template; this cohort report supplies the correct case count and interpretation.", ""]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    verify_bundle(root)
    print(json.dumps({key: stats[key] for key in ("case_count", "reference_pairs", "unique_reference_candidates", "common_reference_pairs", "run_seconds", "checks")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("docs/method/ranking/COHORT_RESULTS.md"))
    args = parser.parse_args()
    generate(args.root, args.output)
