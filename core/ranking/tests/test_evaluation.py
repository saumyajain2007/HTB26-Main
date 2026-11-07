"""Metric definitions, coverage, label isolation, manifests and API compatibility."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from ranking.artifacts import file_record, write_json
from ranking.evaluation import (METRICS, SCORE_METHODS, EvaluationCase, EvaluationSettings, audit_stage2_features,
                                canonical_hash, case_from_stage2, evaluate_cases, random_ranking, retrieval_metrics)
from ranking.evaluation_io import run_evaluation
from ranking.integration import adapt_ranking, validate_api_candidates
from ranking.references import extract_indication_references, parse_references


def cid(i):
    return f"CHEMBL{i}"


def example_payload(disease="TEST_1"):
    candidates = []
    for i in range(1, 13):
        candidates.append({"candidate_id": cid(i), "name": f"Candidate {i}", "status": "scored" if i <= 8 else "not_scorable",
                           "network": {"mean_distance": float(i), "degree_matched_z": float(i - 4), "rank": i, "graph_version": "string-test"} if i <= 8 else None,
                           "unscorable_reason": None if i <= 8 else "no_retained_drug_targets",
                           "direct_evidence": {"score": 1 / i, "breadth": 1 / i}, "direct_evidence_rank": i,
                           "shared_target_count": 1 if i <= 4 else 0, "selected_by": ["network"] if i <= 5 else [],
                           "targets": [{"id": "ENSG00000000001", "name": "G1", "mechanism": "unknown"}]})
    return {"format_version": 2, "disease": {"id": disease, "input_rule": {"score": "evidence_only", "excluded_datasources": ["clinical_precedence", "cancer_biomarkers"]}},
            "candidates": candidates, "shortlist": [cid(i) for i in range(1, 6)],
            "provenance": {"settings": {"seed": 0}, "releases": ["opentargets-test"]}}


class MetricTests(unittest.TestCase):
    def test_multiple_positives_recall_denominators_and_first_positive_mrr(self):
        ranking = [cid(i) for i in range(1, 31)]
        metrics = retrieval_metrics(ranking, {cid(2), cid(11), cid(21), cid(999)}, set(ranking))
        self.assertEqual(metrics["reference_total"], 4)
        self.assertEqual(metrics["positive_in_scope"], 3)
        self.assertEqual(metrics["reference_outside_scope"], 1)
        self.assertEqual(metrics["recall_at_5"], 1 / 3)
        self.assertEqual(metrics["recall_at_10"], 1 / 3)
        self.assertEqual(metrics["recall_at_20"], 2 / 3)
        self.assertEqual(metrics["mrr"], 0.5)

    def test_unretrieved_positive_is_a_miss_without_disappearing(self):
        metrics = retrieval_metrics([cid(1)], {cid(2)}, {cid(1), cid(2)})
        self.assertEqual(metrics["label_status"], "evaluated")
        self.assertTrue(all(metrics[name] == 0 for name in METRICS))
        self.assertEqual(metrics["positive_in_scope"], 1)

    def test_missing_empty_and_out_of_universe_labels_are_not_zero_filled(self):
        for known, expected in ((None, "missing_labels"), (set(), "no_positive_references"), ({cid(999)}, "no_positive_in_scope")):
            metrics = retrieval_metrics([cid(1)], known, {cid(1)})
            self.assertEqual(metrics["label_status"], expected)
            self.assertTrue(all(metrics[name] is None for name in METRICS))

    def test_duplicate_ranked_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            retrieval_metrics([cid(1), cid(1)], {cid(1)}, {cid(1)})

    def test_mrr_is_macro_over_diseases_not_over_positive_drugs(self):
        a = case_from_stage2(example_payload("TEST_1"))
        b = case_from_stage2(example_payload("TEST_2"))
        result = evaluate_cases([a, b], {"TEST_1": {cid(1), cid(2)}, "TEST_2": {cid(4)}})
        row = next(r for r in result["aggregate"] if r["scope"] == "full_eligible" and r["method"] == "raw_proximity")
        self.assertEqual(row["mrr"], (1 + 0.25) / 2)
        self.assertEqual(row["evaluated_cases"], 2)


class EvaluationTests(unittest.TestCase):
    def test_full_universe_and_common_subset_have_identical_method_scopes(self):
        case = case_from_stage2(example_payload())
        result = evaluate_cases([case], {"TEST_1": {cid(2), cid(10)}})
        full = [r for r in result["metrics"] if r["scope"] == "full_eligible"]
        common = [r for r in result["metrics"] if r["scope"] == "common_scorable"]
        self.assertTrue(all(r["universe_size"] == 12 and r["positive_in_scope"] == 2 for r in full))
        self.assertTrue(all(r["universe_size"] == 8 and r["positive_in_scope"] == 1 for r in common))
        network = next(r for r in full if r["method"] == "degree_matched_z")
        self.assertEqual(network["missing_count"], 4)
        self.assertEqual(network["missing_positive_count"], 1)
        self.assertEqual(network["recall_at_20"], 0.5)
        self.assertIn(cid(10), network["missing_candidate_ids"])
        self.assertEqual(result["coverage"][0]["positive_common"], 1)

    def test_missing_score_policy_is_explicit_and_changes_retrieval_as_declared(self):
        case = case_from_stage2(example_payload())
        missed = evaluate_cases([case], {"TEST_1": {cid(10)}})
        appended = evaluate_cases([case], {"TEST_1": {cid(10)}}, EvaluationSettings(missing_score_policy="append_by_id"))
        def row(result):
            return next(r for r in result["metrics"] if r["scope"] == "full_eligible" and r["method"] == "raw_proximity")
        self.assertEqual(row(missed)["mrr"], 0)
        self.assertEqual(row(appended)["mrr"], 1 / 9)  # lexical missing-ID order starts CHEMBL10
        self.assertEqual(row(appended)["missing_count"], 4)

    def test_missing_reference_case_is_explicit_in_macro_exclusions(self):
        case = case_from_stage2(example_payload())
        result = evaluate_cases([case], {})
        self.assertTrue(all(r["evaluated_cases"] == 0 and r["mrr"] is None for r in result["aggregate"]))
        self.assertEqual(result["aggregate"][0]["skipped_cases"], [{"disease_id": "TEST_1", "reason": "missing_labels"}])

    def test_no_positive_in_common_scope_is_not_reported_as_zero_performance(self):
        case = case_from_stage2(example_payload())
        result = evaluate_cases([case], {"TEST_1": {cid(10)}})
        rows = [r for r in result["metrics"] if r["scope"] == "common_scorable"]
        self.assertTrue(all(r["label_status"] == "no_positive_in_scope" and r["mrr"] is None for r in rows))

    def test_shortlist_recall_uses_all_positives_and_does_not_refill_common_subset(self):
        payload = example_payload()
        payload["shortlist"] = [cid(2), cid(10)]
        result = evaluate_cases([case_from_stage2(payload)], {"TEST_1": {cid(2), cid(3), cid(10)}})
        self.assertEqual(result["shortlist"][0]["recall_at_15"], 2 / 3)
        self.assertEqual(result["shortlist"][1]["recall_at_15"], 0.5)
        self.assertEqual(result["shortlist"][1]["selected_count"], 1)

    def test_deterministic_ties_and_random_order_do_not_depend_on_candidate_input_order(self):
        payload = example_payload()
        for c in payload["candidates"]:
            c["direct_evidence"] = {"score": 1, "breadth": 1}
        before = case_from_stage2(payload)
        payload["candidates"].reverse()
        after = case_from_stage2(payload)
        self.assertEqual(before, after)
        self.assertEqual(before.rankings["direct_evidence"][:2], (cid(1), cid(10)))
        universe = set(before.eligible_candidates)
        self.assertEqual(random_ranking(universe, "TEST_1", 3), random_ranking(set(reversed(before.eligible_candidates)), "TEST_1", 3))
        self.assertNotEqual(random_ranking(universe, "TEST_1", 3), random_ranking(universe, "TEST_1", 4))

    def test_direct_labels_in_candidate_features_are_rejected(self):
        for key in ("disease_ids", "known_treatment", "clinical_reports", "docking_score"):
            payload = example_payload()
            payload["candidates"][0]["targets"][0][key] = "label"
            with self.assertRaisesRegex(ValueError, "label field"):
                case_from_stage2(payload)
        payload = example_payload()
        payload["disease"]["input_rule"]["excluded_datasources"] = []
        with self.assertRaisesRegex(ValueError, "leakage-control"):
            audit_stage2_features(payload)

    def test_external_rankings_are_accepted_and_duplicate_or_ineligible_ids_rejected(self):
        ids = tuple(cid(i) for i in range(1, 5))
        case = EvaluationCase("TEST_1", ids, {m: ids for m in SCORE_METHODS}, ids[:2], {"source": "external"})
        result = evaluate_cases([case], {"TEST_1": {cid(1)}})
        self.assertEqual(result["metrics"][0]["mrr"], 1)
        case.rankings["raw_proximity"] = (*ids, cid(999))
        with self.assertRaisesRegex(ValueError, "ineligible"):
            evaluate_cases([case], {"TEST_1": {cid(1)}})


class FileAndReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_reference_extraction_uses_only_actual_ids_not_rankings_or_known_answers(self):
        path = self.root / "drugs.json"
        write_json(path, {"releases": ["source-test"], "drugs": [
            {"drug_id": cid(1), "approval": {"sources": ["FDA"], "disease_ids": ["TEST_1"]}},
            {"drug_id": cid(2), "approval": {"sources": ["FDA"], "disease_ids": ["TEST_2"]}},
            {"drug_id": cid(3), "approval": {"sources": ["ATC"], "disease_ids": ["TEST_1"]}},
        ]})
        refs = extract_indication_references(path, ["TEST_1", "TEST_3"])
        parsed = parse_references(refs)
        self.assertEqual(parsed, {"TEST_1": {cid(1)}, "TEST_3": set()})
        self.assertEqual(refs["source_files"][0]["sha256"], file_record(path)["sha256"])
        self.assertTrue(refs["limitations"])

    def test_reference_duplicates_do_not_inflate_positive_denominators(self):
        parsed = parse_references({"format_version": 1, "definition": "test", "cases": [{"disease_id": "TEST_1", "known_candidate_ids": [cid(1), cid(1)]}]})
        self.assertEqual(parsed["TEST_1"], {cid(1)})

    def test_frozen_manifest_and_exports_are_byte_reproducible_across_output_directories(self):
        rankings = []
        for i in (1, 2):
            path = self.root / f"case{i}.json"
            write_json(path, example_payload(f"TEST_{i}"))
            rankings.append(path)
        reference_path = self.root / "refs.json"
        write_json(reference_path, {"format_version": 1, "definition": "Separately defined fixture labels", "cases": [
            {"disease_id": "TEST_1", "known_candidate_ids": [cid(2), cid(10)]},
            {"disease_id": "TEST_2", "known_candidate_ids": [cid(3)]}]})
        a, b = self.root / "a", self.root / "b"
        first = run_evaluation(rankings, a, references_path=reference_path)
        second = run_evaluation(list(reversed(rankings)), b, references_path=reference_path)
        self.assertEqual(first["manifest_content_sha256"], second["manifest_content_sha256"])
        for path in a.iterdir():
            self.assertEqual(path.read_bytes(), (b / path.name).read_bytes(), path.name)
        self.assertFalse(first["ten_disease_pilot_complete"])
        manifest = json.loads((a / "manifest.json").read_text())
        self.assertEqual(first["manifest_content_sha256"], canonical_hash(manifest))
        with self.assertRaises(FileExistsError):
            run_evaluation(rankings, a, references_path=reference_path)


class IntegrationTests(unittest.TestCase):
    def test_adapter_adds_fixture_fields_and_preserves_missing_data_semantics(self):
        payload = example_payload()
        with self.assertRaisesRegex(ValueError, "Missing API"):
            validate_api_candidates(payload["candidates"])
        result = adapt_ranking(payload)
        self.assertNotIn("evidence", payload["candidates"][0])
        first = result["candidates"][0]
        self.assertEqual(first["evidence"], [])
        self.assertEqual(first["warnings"], [])
        self.assertEqual(first["safety_status"], "unknown")
        self.assertFalse(first["dockable"])
        self.assertEqual(first["enrichment_status"]["safety"], "not_supplied")
        self.assertEqual(result["integration"]["candidates_missing_enrichment"], 12)

    def test_enrichment_preserved_and_evidence_id_conflicts_rejected(self):
        item = {"id": "E1", "source": "test", "release": "test-1", "url": "https://example.test/source", "kind": "target_association"}
        enrichment = {cid(1): {"evidence": [item], "warnings": ["Documented warning"], "safety_status": "documented", "dockable": True}}
        result = adapt_ranking(example_payload(), enrichment)
        self.assertEqual(result["candidates"][0]["evidence"], [item])
        self.assertTrue(result["candidates"][0]["dockable"])
        enrichment[cid(2)] = {"evidence": [{**item, "url": "https://example.test/different"}]}
        with self.assertRaisesRegex(ValueError, "conflicting items"):
            adapt_ranking(example_payload(), enrichment)

    def test_invalid_network_status_contract_is_rejected(self):
        result = adapt_ranking(example_payload())
        result["candidates"][0]["network"]["degree_matched_z"] = None
        with self.assertRaisesRegex(ValueError, "finite z-score"):
            validate_api_candidates(result["candidates"])

    def test_adapter_is_idempotent_and_preserves_existing_enrichment(self):
        payload = example_payload()
        payload["candidates"][0].update(evidence=[], warnings=["Provided warning"], safety_status="documented", dockable=True)
        first = adapt_ranking(payload)
        second = adapt_ranking(first)
        self.assertEqual(first, second)
        self.assertEqual(first["candidates"][0]["warnings"], ["Provided warning"])
        self.assertTrue(first["candidates"][0]["dockable"])
        self.assertEqual(first["candidates"][0]["enrichment_status"]["safety"], "provided")


if __name__ == "__main__":
    unittest.main()
