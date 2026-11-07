"""Opt-in selection, sealed ingestion and paired shortlist-recall checks."""

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.sparse import csr_matrix, save_npz

from ranking.artifacts import file_record, write_json
from ranking.evaluation import canonical_hash
from ranking.scoring import RankingSettings, assign_ranks, make_shortlist
from ranking.shortlist import ShortlistSettings, project_shortlist, select_shortlist
from ranking.shortlist_comparison import (compare_shortlists, implementation_contract, run_comparison,
                                          seal_implementation, verify_implementation, write_results)
from ranking.references import parse_references


def candidate(i, z=None, mass=None, evidence=0, breadth=0):
    return {"candidate_id": f"CHEMBL{i}", "status": "scored" if z is not None else "not_scorable",
            "network": {"degree_matched_z": z, "mean_distance": 1, "graph_version": "string-12.5", "rank": None},
            "direct_evidence": {"score": evidence, "breadth": breadth}, "direct_evidence_rank": None,
            "shared_target_count": 0, "selected_by": [], "selection_reasons": [], "shortlist_rank": None,
            "rwr": {"physical": {"score": mass, "rank": None, "graph_kind": "human_physical_gene_undirected_unweighted",
                                  "status": "scored" if mass is not None else "not_scorable", "converged": True,
                                  "reason": None if mass is not None else "no_retained_drug_targets"},
                    "functional": {"score": 9, "rank": i}},
            "coverage": {"retained": 1}}


def payload(candidates=None):
    candidates = deepcopy(candidates if candidates is not None else [candidate(i, -30+i, 30-i, (30-i)/30) for i in range(1, 26)])
    assign_ranks(candidates)
    short = make_shortlist(candidates, RankingSettings())
    return {"disease": {"id": "TEST_1", "coverage": {"total": 50, "retained": 40}}, "shortlist": short,
            "candidates": candidates, "provenance": {"settings": asdict(RankingSettings()),
            "inputs": {"drugs": {"sha256": "universe"}}, "stage1_manifest": {"sha256": "physical"}},
            "rwr_provenance": {"physical": {"graph": {"graph_version": "string-12.5", "network_kind": "human_physical_gene_undirected_unweighted", "manifest": {"sha256": "physical"}},
                                            "settings": {"restart_probability": 0.3}}}}


def comparison_case(p, disease="TEST_1"):
    selections = {m: select_shortlist(p, ShortlistSettings(method=m)) for m in ("zscore", "physical_rwr")}
    return {"disease_id": disease, "eligible_candidates": [c["candidate_id"] for c in p["candidates"]],
            "selections": selections, "network_scorable": {"zscore": [c["candidate_id"] for c in p["candidates"] if c["status"] == "scored"],
            "physical_rwr": [c["candidate_id"] for c in p["candidates"] if c["rwr"]["physical"]["score"] is not None]}}


class ShortlistTests(unittest.TestCase):
    def test_default_exact_legacy_selection_and_events(self):
        p = payload()
        original = deepcopy(p)
        selection = select_shortlist(p)
        self.assertEqual(selection["selection_method"], "zscore")
        self.assertEqual(selection["shortlist"], p["shortlist"])
        for entry in selection["entries"]:
            c = next(c for c in p["candidates"] if c["candidate_id"] == entry["candidate_id"])
            self.assertEqual(entry["selected_by"], c["selected_by"])
            self.assertEqual(entry["reasons"], c["selection_reasons"])
        self.assertEqual(p, original)

    def test_physical_uses_mass_and_keeps_evidence_policy(self):
        p = payload([candidate(i, i, i, 1 if i <= 8 else 0) for i in range(1, 26)])
        r = select_shortlist(p, ShortlistSettings("physical_rwr"))
        self.assertEqual(r["shortlist"][:10], [f"CHEMBL{i}" for i in range(25, 15, -1)])
        self.assertEqual(r["shortlist"][10:], ["CHEMBL1", "CHEMBL2", "CHEMBL3", "CHEMBL4", "CHEMBL5"])
        self.assertEqual(r["seed"], 0)
        self.assertEqual(r["graph"]["manifest"]["sha256"], "physical")

    def test_overlap_deduplicates_and_refills_to_fifteen(self):
        s = select_shortlist(payload())
        self.assertEqual(len(s["shortlist"]), 15)
        self.assertEqual(len(set(s["shortlist"])), 15)
        self.assertEqual([e["source_lane"] for e in s["entries"][:5]], ["both"]*5)
        self.assertEqual(s["entries"][-1]["reasons"], ["evidence_fill_after_deduplication"])

    def test_ties_and_input_order_are_deterministic(self):
        p = payload([candidate(i, 1, 0.1, 0.7, 0.8) for i in range(1, 26)])
        for method in ("zscore", "physical_rwr"):
            s = select_shortlist(p, ShortlistSettings(method))
            p["candidates"].reverse()
            self.assertEqual(s, select_shortlist(p, ShortlistSettings(method)))
            self.assertEqual(s["shortlist"][:3], ["CHEMBL1", "CHEMBL10", "CHEMBL11"])

    def test_evidence_ties_use_breadth_then_id(self):
        p = payload([candidate(2, evidence=0.5, breadth=1), candidate(10, evidence=0.5, breadth=2), candidate(1, evidence=0.5, breadth=1)])
        self.assertEqual(select_shortlist(p)["shortlist"], ["CHEMBL10", "CHEMBL1", "CHEMBL2"])

    def test_missing_graph_scores_still_selects_evidence(self):
        p = payload([candidate(i, evidence=1) for i in range(1, 18)])
        for c in p["candidates"]:
            del c["rwr"]
        s = select_shortlist(p, ShortlistSettings("physical_rwr"))
        self.assertEqual(len(s["shortlist"]), 15)
        self.assertEqual(s["coverage"]["network_unavailable_by_reason"], {"missing_physical_rwr": 17})
        self.assertEqual(s["lane_warnings"], ["network_pool_below_quota"])
        self.assertTrue(all(e["source_lane"] == "evidence" for e in s["entries"]))

    def test_network_fills_when_evidence_unavailable(self):
        p = payload([candidate(i, -i, i) for i in range(1, 21)])
        self.assertEqual(select_shortlist(p)["selected_size"], 15)
        self.assertEqual(select_shortlist(p)["lane_warnings"], ["supported_evidence_pool_below_quota"])

    def test_shortfall_reports_union_no_unsupported_padding(self):
        p = payload([candidate(1, 1, 0.1), candidate(2, evidence=0.2), candidate(3)])
        s = select_shortlist(p, ShortlistSettings("physical_rwr"))
        self.assertEqual(s["selected_size"], 2)
        self.assertEqual(s["shortfall"], 13)
        self.assertIsNotNone(s["shortfall_reason"])
        self.assertNotIn("CHEMBL3", s["shortlist"])

    def test_unconverged_and_invalid_mass_not_used(self):
        p = payload([candidate(1, mass=1), candidate(2, mass=2), candidate(3, mass=-1), candidate(4, mass=float("inf"))])
        p["candidates"][0]["rwr"]["physical"]["converged"] = False
        self.assertEqual(select_shortlist(p, ShortlistSettings("physical_rwr"))["shortlist"], ["CHEMBL2"])

    def test_wrong_graph_and_duplicate_ids_rejected(self):
        p = payload()
        p["candidates"][0]["rwr"]["physical"]["graph_kind"] = "functional"
        with self.assertRaisesRegex(ValueError, "physical graph"):
            select_shortlist(p, ShortlistSettings("physical_rwr"))
        p["candidates"].append(deepcopy(p["candidates"][0]))
        with self.assertRaisesRegex(ValueError, "unique stable"):
            select_shortlist(p)

    def test_projection_is_additive_to_scores_paths_and_original(self):
        p = payload()
        p["candidates"][0]["network_paths"] = {"paths": [{"path": ["ENSG00000000001"]}], "hop_count": 0}
        original = deepcopy(p)
        r = project_shortlist(p, ShortlistSettings("physical_rwr"))
        for before, after in zip(p["candidates"], r["candidates"]):
            for k in before.keys() - {"selected_by", "selection_reasons", "shortlist_rank"}:
                self.assertEqual(before[k], after[k])
        self.assertEqual(p, original)
        self.assertEqual(r["legacy_shortlist_selection"]["shortlist"], original["shortlist"])
        with self.assertRaisesRegex(ValueError, "original ranking"):
            project_shortlist(r)

    def test_invalid_settings(self):
        for kwargs in ({"method": "functional_rwr"}, {"network_slots": -1}, {"evidence_slots": True}):
            with self.assertRaises(ValueError):
                ShortlistSettings(**kwargs)


class ComparisonTests(unittest.TestCase):
    def test_end_to_end_synthetic_ingestion_freezes_before_labels(self):
        # Four-node path plus an isolated protein: no real cohort or labels.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            graph_dir, targets_dir = root/"graph", root/"targets"
            graph_dir.mkdir()
            targets_dir.mkdir()
            genes = [f"ENSG{i:011d}" for i in range(1, 6)]
            graph = csr_matrix((np.ones(3, dtype=np.uint8), (np.arange(3), np.arange(1, 4))), shape=(5, 5))
            graph = graph + graph.T
            save_npz(graph_dir/"graph.npz", graph)
            np.save(graph_dir/"distances.npy", np.abs(np.arange(4)[:, None] - np.arange(4)).astype(np.uint8))
            write_json(graph_dir/"index.json", {"graph_gene_ids": genes, "distance_gene_ids": genes[:4], "component_labels": [0]*4+[1]})
            write_json(graph_dir/"mapping_exclusions.json", {})
            write_json(graph_dir/"manifest.json", {"format_version": 1, "network_kind": "human_physical_gene_undirected_unweighted",
                       "releases": ["string-12.5", "opentargets-test"], "filters": {"combined_score_min": 700, "experiments_min": 400, "direct_experiments_column": "experiments", "transferred_experiments_used_as_direct": False},
                       "distances": {"shape": [4, 4], "dtype": "uint8", "unreachable_sentinel": 255},
                       "files": {p.name: file_record(p) for p in graph_dir.iterdir()}})
            drug_rows = [{"drug_id": f"CHEMBL{i}", "name": f"Synthetic {i}", "targets": [{"target_id": genes[i-1]}],
                          "approval": {"sources": ["FDA"], "disease_ids": ["LEAK_999"]}} for i in (1, 2, 5)]
            drug_rows.append({"drug_id": "CHEMBL99", "targets": [], "approval": {"sources": ["trial"]}})
            write_json(root/"drugs.json", {"releases": ["opentargets-test"], "drugs": drug_rows})
            rows = []
            for i in range(1, 15):
                disease = f"SYNTHETIC_{i}"
                filename = f"{disease}.json"
                rows.append({"disease_id": disease, "targets_file": filename})
                write_json(targets_dir/filename, {"disease_id": disease, "disease_name": "Synthetic only", "release": "opentargets-test",
                           "rule": {"score": "evidence_only", "top_n": 50, "excluded_datasources": ["clinical_precedence", "cancer_biomarkers"]},
                           "targets": [{"target_id": genes[0], "evidence_only_score": 0.8}]})
            write_json(root/"cases.json", {"format_version": 1, "cohort_id": "synthetic_unit_test_only", "cases": rows})
            write_json(root/"refs.json", {"format_version": 1, "definition": "Synthetic unit-test labels only", "releases": ["test-v1"],
                       "source_files": [{"source": "synthetic"}], "cases": [{"disease_id": r["disease_id"], "known_candidate_ids": ["CHEMBL1", "CHEMBL5", "CHEMBL99"]} for r in rows]})
            (root/"protocol.md").write_text("Synthetic test fixture, not an official replication protocol.")
            seal_implementation(root/"seal.json")
            args = dict(seal=root/"seal.json", cases=root/"cases.json", targets_dir=targets_dir, references=root/"refs.json",
                        drugs=root/"drugs.json", artifacts=graph_dir, protocol=root/"protocol.md", out=root/"out")
            def guarded_parse(labels):
                self.assertTrue((root/"out"/"shortlists.freeze.json").is_file())
                for row in rows:
                    self.assertTrue((root/"out"/row["disease_id"]/"physical_rwr.json").is_file())
                return parse_references(labels)
            with patch("ranking.shortlist_comparison.parse_references", side_effect=guarded_parse):
                result = run_comparison(**args)
            self.assertEqual(result["summary"]["eligible_reference_pairs"], 28)
            self.assertEqual(result["summary"]["diseases_evaluated"], 14)
            self.assertEqual(result["summary"]["methods"]["physical_rwr"]["macro_recall_at_15"]["mean"], 0.5)
            self.assertEqual(result["cases"][0]["references_outside_universe"], 1)
            for r in result["cases"]:
                self.assertEqual(r["methods"]["physical_rwr"]["coverage"]["network_scorable"], 2)
            self.assertNotIn("LEAK_999", (root/"out"/rows[0]["disease_id"]/"ranking.json").read_text())
            frozen = json.loads((root/"out"/"inputs.freeze.json").read_text())
            self.assertEqual(frozen["eligible_universe"]["ids"], ["CHEMBL1", "CHEMBL2", "CHEMBL5"])
            self.assertTrue((root/"out"/"outputs.manifest.json").is_file())
            with self.assertRaises(FileExistsError):
                run_comparison(**args)

    def test_multiple_positives_fraction_any_hit_and_pair_flags(self):
        c = comparison_case(payload([candidate(i, i, i) for i in range(1, 26)]))
        r = compare_shortlists([c], {"TEST_1": {"CHEMBL1", "CHEMBL25", "CHEMBL999"}})
        row = r["cases"][0]
        self.assertEqual(row["eligible_reference_pairs"], 2)
        self.assertEqual(row["references_outside_universe"], 1)
        for method in ("zscore", "physical_rwr"):
            self.assertEqual(row["methods"][method]["recall_at_15"], 0.5)
            self.assertEqual(row["methods"][method]["any_reference_retrieved"], 1)
        self.assertEqual(r["paired"]["ties"], 1)
        self.assertEqual(r["paired"]["recall_at_15"]["bootstrap_95_ci"], None)
        self.assertFalse(r["reference_membership"][-1]["eligible"])

    def test_missing_empty_outside_labels_not_zero_and_unscorable_is_miss(self):
        p = payload([candidate(1), candidate(2, z=1, mass=1)])
        cases = [comparison_case(p, f"TEST_{i}") for i in range(1, 5)]
        r = compare_shortlists(cases, {"TEST_2": set(), "TEST_3": {"CHEMBL99"}, "TEST_4": {"CHEMBL1"}})
        self.assertEqual([c["label_status"] for c in r["cases"]], ["missing_labels", "no_positive_references", "no_eligible_references", "evaluated"])
        self.assertIsNone(r["cases"][0]["methods"]["zscore"]["recall_at_15"])
        self.assertEqual(r["cases"][3]["methods"]["zscore"]["recall_at_15"], 0)
        self.assertEqual(r["summary"]["eligible_reference_pairs"], 1)
        self.assertEqual(r["summary"]["diseases_evaluated"], 1)

    def test_paired_direction_wins_losses_and_reproducible_intervals(self):
        p = payload([candidate(i, i, i) for i in range(1, 26)])
        cases = [comparison_case(p, f"TEST_{i}") for i in (1, 2, 3)]
        refs = {"TEST_1": {"CHEMBL25"}, "TEST_2": {"CHEMBL1"}, "TEST_3": {"CHEMBL25", "CHEMBL24"}}
        a = compare_shortlists(cases, refs)
        self.assertEqual(a, compare_shortlists(cases, refs))
        self.assertEqual(a["paired"]["physical_rwr_wins"], 2)
        self.assertEqual(a["paired"]["zscore_wins"], 1)
        self.assertAlmostEqual(a["paired"]["recall_at_15"]["mean_difference"], 1/3)
        self.assertEqual(a["summary"]["methods"]["physical_rwr"]["retrieved_pairs"], 3)
        self.assertEqual(a["summary"]["methods"]["physical_rwr"]["micro_recall_at_15"], 0.75)

    def test_different_universes_invalid_shortlists_rejected(self):
        c = comparison_case(payload())
        c["selections"]["physical_rwr"]["eligible_universe"]["count"] += 1
        with self.assertRaisesRegex(ValueError, "identical pinned"):
            compare_shortlists([c], {})
        c = comparison_case(payload())
        c["selections"]["physical_rwr"]["shortlist"].append("CHEMBL999")
        with self.assertRaisesRegex(ValueError, "Invalid shortlist"):
            compare_shortlists([c], {})

    def test_seal_has_no_labels_and_detects_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            seal = Path(temp)/"seal.json"
            first = seal_implementation(seal)
            self.assertEqual(verify_implementation(seal), first)
            self.assertNotIn("references", first)
            with self.assertRaises(FileExistsError):
                seal_implementation(seal)
            changed = implementation_contract()
            changed["settings"]["rwr"]["restart_probability"] = 0.4
            with patch("ranking.shortlist_comparison.implementation_contract", return_value=changed):
                with self.assertRaisesRegex(ValueError, "seal mismatch"):
                    verify_implementation(seal)

    def test_bad_seal_stops_before_any_label_access(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root/"seal.json", {})
            with self.assertRaisesRegex(ValueError, "seal mismatch"):
                run_comparison(seal=root/"seal.json", cases=root/"missing", targets_dir=root,
                               references=root/"DO_NOT_OPEN", drugs=root/"missing", artifacts=root,
                               protocol=root/"missing", out=root/"out")
            self.assertFalse((root/"out").exists())

    def test_csv_and_json_real_metric_output(self):
        r = compare_shortlists([comparison_case(payload())], {"TEST_1": {"CHEMBL1"}})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_results(root, r)
            self.assertEqual(json.loads((root/"results.json").read_text()), r)
            self.assertIn("reference_network_scorable", (root/"per_disease.csv").read_text())
            self.assertIn("not treatment-success", (root/"REPORT.md").read_text())


if __name__ == "__main__":
    unittest.main()
